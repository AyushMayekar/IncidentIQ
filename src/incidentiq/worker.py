"""Standalone evidence-processing worker.

Run with::

    uv run python -m incidentiq.worker

Only ONE worker process is supported. The database-backed lease makes a second
process exit instead of competing, so the global (3) and per-type (1) limits
are effective for the whole deployment. Scaling out horizontally would require
moving those limits into cross-process database locks first.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from incidentiq.config import Settings, get_settings
from incidentiq.database import SessionLocal
from incidentiq.services import (
    acquire_lease,
    claim_jobs,
    recover_stale_jobs,
    release_lease,
    renew_lease,
    run_job,
)

logger = logging.getLogger("incidentiq.worker")


def _process(job_id: UUID, settings: Settings) -> None:
    """Each job gets its own session; one failure cannot poison the batch."""
    with SessionLocal() as db:
        try:
            run_job(db, job_id, settings)
        except Exception:  # noqa: BLE001 - the service records safe failures
            db.rollback()
            logger.exception("worker job crashed", extra={"job_id": str(job_id)})


def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(signum: int, _frame: object) -> None:
        logger.info("shutdown requested", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _start_lease_heartbeat(
    owner: str, settings: Settings, stop: threading.Event
) -> threading.Thread:
    """Renew the lease while a long batch is running.

    Without this, a slow batch could outlive ``worker_lease_seconds`` and let a
    second process start. The heartbeat uses its own session and stops with the
    main loop's event.
    """

    def beat() -> None:
        while not stop.wait(max(1, settings.worker_lease_renew_seconds)):
            with SessionLocal() as db:
                if not renew_lease(db, owner, settings):
                    logger.error("lost the worker lease; stopping")
                    stop.set()
                    return

    thread = threading.Thread(
        target=beat, name="worker-lease-heartbeat", daemon=True
    )
    thread.start()
    return thread


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    owner = f"{socket.gethostname()}:{os.getpid()}"

    logger.info(
        "starting IncidentIQ worker (single process; lease-enforced)",
        extra={
            "owner": owner,
            "executor": settings.parser_executor,
            "max_files_global": settings.worker_max_files_global,
            "max_files_per_type": settings.worker_max_files_per_type,
        },
    )

    with SessionLocal() as db:
        if not acquire_lease(db, owner, settings):
            logger.error(
                "another worker already holds the lease; exiting. "
                "Only one worker process is supported by this implementation."
            )
            return 1

    stop = threading.Event()
    _install_signal_handlers(stop)
    _start_lease_heartbeat(owner, settings, stop)

    executor: ThreadPoolExecutor | None = None
    if settings.parser_executor == "thread":
        executor = ThreadPoolExecutor(
            max_workers=max(1, settings.parser_threads),
            thread_name_prefix="evidence-parser",
        )

    try:
        while not stop.is_set():
            with SessionLocal() as db:
                if not renew_lease(db, owner, settings):
                    logger.error("lost the worker lease; exiting")
                    return 1
                recovered = recover_stale_jobs(db, settings)
                if recovered:
                    logger.info("recovered stale jobs", extra={"count": len(recovered)})
                job_ids = claim_jobs(db, settings)

            if not job_ids:
                stop.wait(settings.worker_poll_interval_seconds)
                continue

            if executor is not None:
                futures = [executor.submit(_process, job_id, settings) for job_id in job_ids]
                for future in futures:
                    future.result()
            else:
                for job_id in job_ids:
                    _process(job_id, settings)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        with SessionLocal() as db:
            release_lease(db, owner)
        logger.info("worker stopped", extra={"owner": owner})

    return 0


if __name__ == "__main__":
    sys.exit(main())
