"""Generate synthetic performance-lab logs with a known regression.

Two nightly runs on the same benchmark scenes and GPUs. The candidate run uses
a newer driver; in two scenes a slow shader compilation is followed by a GPU
timeout (TDR) and an aborted benchmark. The baseline has a fan-curve warning
that the candidate no longer shows. Tests and demos use this data because the
expected findings are known in advance. All names and values are made up.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCENES = ["CityNight", "DesertRace", "ForestFlyover", "IndoorArena"]
GPUS = ["RTX 4070", "RTX 4080", "RTX 4090"]
REGRESSED_SCENES = {"CityNight", "IndoorArena"}
FRAME_BUDGET_MS = 16.7


def _line(ts: datetime, service: str, level: str, run: str, message: str, **extra: Any) -> dict:
    return {
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "service": service,
        "level": level,
        "run": run,
        "message": message,
        **extra,
    }


def _benchmark(
    rng: random.Random, run: str, t: datetime, scene: str, gpu: str, driver: str, regression: bool
) -> list[dict]:
    """Log lines for one benchmark of one scene on one GPU, starting at ``t``."""
    ctx = {"scene": scene, "gpu": gpu, "driver": driver}
    lines: list[dict] = []

    def emit(seconds: float, service: str, level: str, message: str) -> None:
        lines.append(_line(t + timedelta(seconds=seconds), service, level, run, message, **ctx))

    emit(0, "test-runner", "INFO", f"Started benchmark {scene} on {gpu}")
    emit(1, "game-build", "INFO", f"Loaded build 2.14.{rng.randint(100, 999)} for {scene}")
    if not regression and rng.random() < 0.3:
        emit(2, "driver", "WARNING", "Fan curve fallback on GPU 0")
    if rng.random() < 0.15:
        retry = rng.randint(1, 3)
        emit(3, "game-build", "ERROR", f"Asset download retry {retry} for 'textures/{scene}.pak'")

    if regression and scene in REGRESSED_SCENES and rng.random() < 0.7:
        compile_ms = rng.randint(800, 2000)
        pipeline = f"0x{rng.getrandbits(32):08x}"
        timeout_ms = rng.randint(2000, 2100)
        emit(
            4,
            "game-build",
            "WARNING",
            f"Shader compilation took {compile_ms} ms for pipeline {pipeline}",
        )
        emit(9, "driver", "ERROR", f"Device removed: TDR timeout after {timeout_ms} ms on GPU 0")
        emit(10, "test-runner", "ERROR", f"Benchmark {scene} aborted: device lost")
        return lines

    fps = []
    for sample in range(10):
        p99 = rng.gauss(13.0, 1.6)
        fps.append(1000 / max(p99 - 3.0, 1.0))
        if p99 > FRAME_BUDGET_MS:
            text = f"Frame time p99 {p99:.1f} ms above budget {FRAME_BUDGET_MS} ms in {scene}"
            emit(5 + 4 * sample, "telemetry", "WARNING", text)
        else:
            emit(5 + 4 * sample, "telemetry", "INFO", f"Frame time p99 {p99:.1f} ms in {scene}")
    avg = sum(fps) / len(fps)
    emit(50, "test-runner", "INFO", f"Benchmark {scene} finished: avg {avg:.1f} FPS")
    return lines


def _run(
    rng: random.Random, run: str, start: datetime, driver: str, regression: bool
) -> list[dict]:
    """Three passes over every scene and GPU, one benchmark per minute."""
    lines: list[dict] = []
    t = start
    for _ in range(3):
        for scene in SCENES:
            for gpu in GPUS:
                lines += _benchmark(rng, run, t, scene, gpu, driver, regression)
                t += timedelta(minutes=1)
    return lines


def generate(out: Path, seed: int = 7) -> list[Path]:
    """Write ``<out>/<run>/<service>.jsonl`` for a baseline and a candidate run."""
    rng = random.Random(seed)
    start = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)
    runs = {
        "nightly-1041": _run(rng, "nightly-1041", start, "551.20", regression=False),
        "nightly-1042": _run(
            rng, "nightly-1042", start + timedelta(days=1), "551.31", regression=True
        ),
    }
    written = []
    for run, lines in runs.items():
        by_service: dict[str, list[dict]] = {}
        for line in sorted(lines, key=lambda x: x["ts"]):
            by_service.setdefault(line["service"], []).append(line)
        for service, items in by_service.items():
            path = out / run / f"{service}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write synthetic performance-lab logs.")
    parser.add_argument("out", nargs="?", default="logs", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    files = generate(args.out, args.seed)
    print(f"wrote {len(files)} files to {args.out}")


if __name__ == "__main__":
    main()
