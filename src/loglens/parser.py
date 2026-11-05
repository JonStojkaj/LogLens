"""Read service logs stored as JSON Lines.

Every line is one JSON object. Required keys: ``ts`` (ISO 8601), ``service``,
``level`` and ``message``. ``run`` names the test run or build the line belongs
to; any other keys are kept in ``fields``. Lines that are not valid are counted
and skipped instead of aborting the whole read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LEVEL_RANK = {name: rank for rank, name in enumerate(LEVELS)}
_ALIASES = {"WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL"}
_CORE_KEYS = {"ts", "service", "level", "message", "run"}


@dataclass(slots=True)
class LogRecord:
    ts: datetime
    service: str
    level: str
    message: str
    run: str = "unknown"
    fields: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "service": self.service,
            "level": self.level,
            "run": self.run,
            "message": self.message,
            "fields": self.fields,
            "source": f"{self.source}:{self.line}",
        }


def normalize_level(level: str) -> str:
    name = level.strip().upper()
    return _ALIASES.get(name, name)


def level_rank(level: str) -> int:
    """Severity as a number, so levels can be compared (DEBUG=0 ... CRITICAL=4)."""
    name = normalize_level(level)
    if name not in _LEVEL_RANK:
        raise ValueError(f"unknown level {level!r}, expected one of {', '.join(LEVELS)}")
    return _LEVEL_RANK[name]


def parse_timestamp(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Logs without a zone are treated as UTC so that all timestamps compare.
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def parse_line(text: str, source: str = "", line: int = 0) -> LogRecord | None:
    """Parse one line; returns None for blank or malformed lines."""
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        level = normalize_level(str(obj["level"]))
        if level not in _LEVEL_RANK:
            return None
        return LogRecord(
            ts=parse_timestamp(str(obj["ts"])),
            service=str(obj["service"]),
            level=level,
            message=str(obj["message"]),
            run=str(obj.get("run", "unknown")),
            fields={k: v for k, v in obj.items() if k not in _CORE_KEYS},
            source=source,
            line=line,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None


def read_logs(path: Path) -> tuple[list[LogRecord], int]:
    """Read one ``.jsonl`` file or every ``.jsonl`` file below a directory.

    Returns the records sorted by timestamp and the number of skipped lines.
    """
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    records: list[LogRecord] = []
    skipped = 0
    for file in files:
        with file.open(encoding="utf-8") as handle:
            for number, text in enumerate(handle, start=1):
                record = parse_line(text, source=file.name, line=number)
                if record is None:
                    skipped += bool(text.strip())
                else:
                    records.append(record)
    records.sort(key=lambda r: r.ts)
    return records, skipped
