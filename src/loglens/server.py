"""MCP server that exposes the LogLens analysis as read-only tools.

An agent (any MCP client) calls these tools to look at service logs. The tools
only read ``.jsonl`` files below ``LOGLENS_LOG_DIR`` and every number they
return is computed by ``analysis``, so the agent can explain findings but not
invent them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import analysis
from .parser import LogRecord, parse_timestamp, read_logs

INSTRUCTIONS = """\
Tools for troubleshooting from service logs (test runner, driver, game build,
telemetry). Start with list_runs, use error_summary for one run,
find_regressions to compare a candidate run with a known-good baseline, and
correlate_errors to see what happens around a specific error. Quote the
numbers the tools return; do not estimate counts yourself."""

MAX_LIMIT = 500
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

server = MCPServer(name="loglens", instructions=INSTRUCTIONS)

_cache: dict[Path, tuple[tuple[Any, ...], list[LogRecord], int]] = {}


def log_root() -> Path:
    return Path(os.environ.get("LOGLENS_LOG_DIR", "logs")).resolve()


def resolve_path(subpath: str | None) -> Path:
    """Map a tool argument to a path inside the log root; reject everything else."""
    root = log_root()
    target = (root / subpath).resolve() if subpath else root
    if target != root and root not in target.parents:
        raise ValueError("path must stay inside the log directory")
    if not target.exists():
        raise ValueError(f"no logs found at {subpath or str(root)!r}")
    return target


def load(subpath: str | None = None) -> tuple[list[LogRecord], int]:
    """Parsed records for a path, re-read only when a file changed."""
    target = resolve_path(subpath)
    files = sorted(target.rglob("*.jsonl")) if target.is_dir() else [target]
    stamp = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    cached = _cache.get(target)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]
    records, skipped = read_logs(target)
    _cache[target] = (stamp, records, skipped)
    return records, skipped


@server.tool(annotations=READ_ONLY)
def list_runs(path: str | None = None) -> dict[str, Any]:
    """List the test runs in the logs with line, warning and error counts."""
    records, skipped = load(path)
    return {"runs": analysis.list_runs(records), "skipped_lines": skipped}


@server.tool(annotations=READ_ONLY)
def search_logs(
    run: str | None = None,
    service: str | None = None,
    min_level: str | None = None,
    contains: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    path: str | None = None,
) -> dict[str, Any]:
    """Find log lines by run, service, minimum level, text and time range (ISO 8601)."""
    records, _ = load(path)
    return analysis.search(
        records,
        run=run,
        service=service,
        min_level=min_level,
        contains=contains,
        since=parse_timestamp(since) if since else None,
        until=parse_timestamp(until) if until else None,
        limit=max(1, min(limit, MAX_LIMIT)),
    )


@server.tool(annotations=READ_ONLY)
def error_summary(
    run: str | None = None,
    service: str | None = None,
    min_level: str = "ERROR",
    top: int = 10,
    path: str | None = None,
) -> dict[str, Any]:
    """Group errors by message signature (numbers and ids removed), most frequent first."""
    records, _ = load(path)
    return analysis.error_summary(records, run=run, service=service, min_level=min_level, top=top)


@server.tool(annotations=READ_ONLY)
def find_regressions(
    baseline_run: str,
    candidate_run: str,
    min_level: str = "WARNING",
    ratio: float = 2.0,
    min_count: int = 3,
    path: str | None = None,
) -> dict[str, Any]:
    """Compare a candidate run with a baseline: new, more frequent and resolved problems."""
    records, _ = load(path)
    return analysis.find_regressions(
        records,
        baseline_run=baseline_run,
        candidate_run=candidate_run,
        min_level=min_level,
        ratio=ratio,
        min_count=min_count,
    )


@server.tool(annotations=READ_ONLY)
def correlate_errors(
    anchor: str,
    window_s: float = 30.0,
    run: str | None = None,
    top: int = 10,
    path: str | None = None,
) -> dict[str, Any]:
    """Show which warnings and errors of other services appear around an error.

    before_share close to 1 means the problem usually comes first: a candidate
    cause. Close to 0 means it follows: more likely a consequence.
    """
    records, _ = load(path)
    return analysis.correlate(records, anchor=anchor, window_s=window_s, run=run, top=top)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
