"""Advisory parser benchmarks (not absolute acceptance gates).

Run explicitly with::

    uv run pytest -m perf -s

Targets come from settings (``parser_perf_target_seconds``) and only fail when
``INCIDENTIQ_PERF_GATE=1`` is set. ``tracemalloc`` measures **Python
allocations only** — it is not process RSS and does not include interpreter or
C-extension memory.
"""

from __future__ import annotations

import os
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor

import pytest

from incidentiq.config import get_settings
from incidentiq.parsers import require_parser

pytestmark = pytest.mark.perf


def _application_log(rows: int = 10_000) -> str:
    return "\n".join(
        f"2026-11-03T09:14:{number % 60:02d}Z ERROR [checkout-api] "
        f"Payment failed request_id=req-{number} trace_id=tr-{number}"
        for number in range(rows)
    )


def _metrics_csv(rows: int = 50_000) -> str:
    header = "timestamp,metric,value,unit,labels\n"
    body = "\n".join(
        f"2026-11-03T09:{(number // 60) % 60:02d}:{number % 60:02d}Z,"
        f'latency_ms,{number}.{number % 1000:03d},ms,"service=checkout"'
        for number in range(rows)
    )
    return header + body


def _report(name: str, rows: int, seconds: float, peak_bytes: int | None) -> None:
    rate = rows / seconds if seconds else float("inf")
    memory = f", python_alloc_peak={peak_bytes / (1024 * 1024):.2f} MiB" if peak_bytes else ""
    print(f"\n[perf] {name}: {rows} records in {seconds:.3f}s ({rate:,.0f}/s){memory}")


def test_application_log_throughput(capsys: pytest.CaptureFixture[str]) -> None:
    settings = get_settings()
    text = _application_log()
    parser = require_parser("application_log")

    started = time.perf_counter()
    result = parser.parse(text, "application.log")
    elapsed = time.perf_counter() - started
    assert len(result.records) == 10_000

    # Separate pass so measurement overhead does not distort the timing above.
    tracemalloc.start()
    parser.parse(text, "application.log")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    _report("application_log", len(result.records), elapsed, peak)
    if os.environ.get("INCIDENTIQ_PERF_GATE") == "1":
        assert elapsed <= settings.parser_perf_target_seconds


def test_metrics_csv_throughput(capsys: pytest.CaptureFixture[str]) -> None:
    settings = get_settings()
    rows = max(settings.parser_perf_target_csv_rows, 50_000)
    text = _metrics_csv(rows)
    parser = require_parser("metrics")

    started = time.perf_counter()
    result = parser.parse(text, "metrics.csv")
    elapsed = time.perf_counter() - started
    assert len(result.records) == rows

    _report("metrics", len(result.records), elapsed, None)
    if os.environ.get("INCIDENTIQ_PERF_GATE") == "1":
        # The CSV target is advisory: rows-per-target at the configured ceiling.
        assert elapsed <= settings.parser_perf_target_seconds * 3


def test_threads_do_not_change_results_and_report_actual_gain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Threads may overlap I/O, but CPython's GIL serialises parsing bytecode.

    This test never asserts a speed-up; it prints the measured reality so the
    shipped default can be chosen from evidence.
    """
    text = _application_log(5_000)
    parser = require_parser("application_log")

    started = time.perf_counter()
    sequential = [parser.parse(text, f"seq-{i}.log") for i in range(3)]
    sequential_seconds = time.perf_counter() - started

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        threaded = list(
            pool.map(lambda i: parser.parse(text, f"thr-{i}.log"), range(3))
        )
    threaded_seconds = time.perf_counter() - started

    assert [len(r.records) for r in sequential] == [5_000, 5_000, 5_000]
    assert [len(r.records) for r in threaded] == [5_000, 5_000, 5_000]
    print(
        f"\n[perf] executor comparison: inline={sequential_seconds:.3f}s "
        f"thread={threaded_seconds:.3f}s (GIL: no CPU parallelism claimed)"
    )
