"""Deterministic log analysis. Every number an agent sees is computed here.

The functions take parsed records and return plain dicts so they can be used
directly as MCP tool results and tested without a server.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .parser import LogRecord, level_rank

# Variable parts of a message (ids, addresses, numbers) are replaced so that
# "timeout after 2031 ms" and "timeout after 1987 ms" count as one problem.
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b0x[0-9a-f]+\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)*")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def signature(message: str) -> str:
    """Message template with variable parts replaced by placeholders."""
    text = _UUID.sub("<id>", message)
    text = _HEX.sub("<hex>", text)
    text = _QUOTED.sub("<str>", text)
    return _NUMBER.sub("<n>", text)


def filter_records(
    records: Iterable[LogRecord],
    *,
    run: str | None = None,
    service: str | None = None,
    min_level: str | None = None,
    contains: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[LogRecord]:
    rank = level_rank(min_level) if min_level else None
    needle = contains.lower() if contains else None
    out = []
    for r in records:
        if run and r.run != run:
            continue
        if service and r.service != service:
            continue
        if rank is not None and level_rank(r.level) < rank:
            continue
        if needle and needle not in r.message.lower():
            continue
        if since and r.ts < since:
            continue
        if until and r.ts > until:
            continue
        out.append(r)
    return out


def list_runs(records: Iterable[LogRecord]) -> list[dict[str, Any]]:
    by_run: dict[str, list[LogRecord]] = defaultdict(list)
    for r in records:
        by_run[r.run].append(r)
    runs = []
    for run, items in sorted(by_run.items()):
        levels = Counter(r.level for r in items)
        runs.append(
            {
                "run": run,
                "lines": len(items),
                "services": sorted({r.service for r in items}),
                "start": items[0].ts.isoformat(),
                "end": items[-1].ts.isoformat(),
                "warnings": levels["WARNING"],
                "errors": levels["ERROR"] + levels["CRITICAL"],
            }
        )
    return runs


def search(records: list[LogRecord], *, limit: int = 50, **filters: Any) -> dict[str, Any]:
    matches = filter_records(records, **filters)
    return {
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "records": [r.to_dict() for r in matches[:limit]],
    }


def _groups(records: Iterable[LogRecord]) -> dict[str, list[LogRecord]]:
    groups: dict[str, list[LogRecord]] = defaultdict(list)
    for r in records:
        groups[signature(r.message)].append(r)
    return groups


def error_summary(
    records: list[LogRecord],
    *,
    run: str | None = None,
    service: str | None = None,
    min_level: str = "ERROR",
    top: int = 10,
) -> dict[str, Any]:
    """Group problems by message signature, most frequent first."""
    matches = filter_records(records, run=run, service=service, min_level=min_level)
    groups = sorted(_groups(matches).items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return {
        "run": run,
        "service": service,
        "min_level": min_level,
        "total": len(matches),
        "distinct": len(groups),
        "groups": [
            {
                "signature": sig,
                "count": len(items),
                "services": sorted({r.service for r in items}),
                "first_seen": items[0].ts.isoformat(),
                "last_seen": items[-1].ts.isoformat(),
                "example": items[0].message,
                "example_source": f"{items[0].source}:{items[0].line}",
            }
            for sig, items in groups[:top]
        ],
    }


def find_regressions(
    records: list[LogRecord],
    *,
    baseline_run: str,
    candidate_run: str,
    min_level: str = "WARNING",
    ratio: float = 2.0,
    min_count: int = 3,
) -> dict[str, Any]:
    """Compare two runs and report new, more frequent and resolved problems.

    Counts are normalized per 1,000 log lines of each run, so a longer run does
    not look worse just because it logged more.
    """
    base_all = filter_records(records, run=baseline_run)
    cand_all = filter_records(records, run=candidate_run)
    if not base_all or not cand_all:
        missing = baseline_run if not base_all else candidate_run
        raise ValueError(f"run {missing!r} has no log lines")
    base = {s: len(v) for s, v in _groups(filter_records(base_all, min_level=min_level)).items()}
    cand_groups = _groups(filter_records(cand_all, min_level=min_level))
    cand = {s: len(v) for s, v in cand_groups.items()}

    def rate(count: int, total: int) -> float:
        return round(1000 * count / total, 2)

    new, increased, resolved = [], [], []
    for sig, count in sorted(cand.items(), key=lambda kv: -kv[1]):
        entry = {
            "signature": sig,
            "candidate_count": count,
            "candidate_per_1k": rate(count, len(cand_all)),
            "baseline_count": base.get(sig, 0),
            "baseline_per_1k": rate(base.get(sig, 0), len(base_all)),
            "services": sorted({r.service for r in cand_groups[sig]}),
            "example": cand_groups[sig][0].message,
        }
        if sig not in base:
            if count >= min_count:
                new.append(entry)
        elif count >= min_count and entry["candidate_per_1k"] >= ratio * entry["baseline_per_1k"]:
            increased.append(entry)
    for sig, count in sorted(base.items(), key=lambda kv: -kv[1]):
        if sig not in cand and count >= min_count:
            resolved.append({"signature": sig, "baseline_count": count})
    return {
        "baseline_run": baseline_run,
        "candidate_run": candidate_run,
        "baseline_lines": len(base_all),
        "candidate_lines": len(cand_all),
        "new": new,
        "increased": increased,
        "resolved": resolved,
    }


def correlate(
    records: list[LogRecord],
    *,
    anchor: str,
    window_s: float = 30.0,
    run: str | None = None,
    min_level: str = "WARNING",
    top: int = 10,
) -> dict[str, Any]:
    """Which other problems show up around each occurrence of ``anchor``?

    ``anchor`` is a substring of the error message to investigate. For every
    occurrence, warnings and errors of other signatures within ``window_s``
    seconds are collected. ``share`` is the fraction of anchor occurrences a
    signature appears near; ``before_share`` how often it came first, which
    makes it a candidate cause rather than a consequence.
    """
    scoped = filter_records(records, run=run, min_level=min_level)
    needle = anchor.lower()
    anchors = [r for r in scoped if needle in r.message.lower()]
    if not anchors:
        return {"anchor": anchor, "occurrences": 0, "related": []}
    anchor_sigs = {signature(r.message) for r in anchors}
    window = timedelta(seconds=window_s)
    near: Counter[tuple[str, str]] = Counter()
    before: Counter[tuple[str, str]] = Counter()
    for a in anchors:
        seen: dict[tuple[str, str], bool] = {}
        for r in scoped:
            if r is a or abs(r.ts - a.ts) > window or signature(r.message) in anchor_sigs:
                continue
            key = (r.service, signature(r.message))
            seen[key] = seen.get(key, False) or r.ts < a.ts
        for key, came_first in seen.items():
            near[key] += 1
            before[key] += came_first
    related = [
        {
            "service": service,
            "signature": sig,
            "share": round(count / len(anchors), 2),
            "before_share": round(before[(service, sig)] / count, 2),
        }
        for (service, sig), count in near.most_common(top)
    ]
    return {
        "anchor": anchor,
        "occurrences": len(anchors),
        "window_s": window_s,
        "related": related,
    }
