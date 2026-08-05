"""Small deterministic performance smoke benchmark for the verification API."""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path

from shieldfont.application.verify import shape_text


def main() -> int:
    font_path = os.environ.get("SHIELDFONT_BENCHMARK_FONT")
    if not font_path:
        print("benchmark skipped: SHIELDFONT_BENCHMARK_FONT is not set")
        return 0
    path = Path(font_path)
    sample = os.environ.get("SHIELDFONT_BENCHMARK_TEXT", "ShieldFont benchmark")
    runs = int(os.environ.get("SHIELDFONT_BENCHMARK_RUNS", "20"))
    durations: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        shape_text(path, sample)
        durations.append((time.perf_counter() - started) * 1000)
    print(
        f"runs={runs} median_ms={statistics.median(durations):.3f} "
        f"p95_ms={sorted(durations)[max(0, int(runs * 0.95) - 1)]:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
