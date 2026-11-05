import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    """Path to the settings file, overridable so tests never read the real ``.env``."""
    return os.environ.get("INCIDENTIQ_ENV_FILE", ".env")


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str

    # --- worker loop ---------------------------------------------------------
    worker_poll_interval_seconds: float = 1.0
    worker_max_files_global: int = 3
    worker_max_files_per_type: int = 1
    worker_stale_after_seconds: int = 300
    worker_max_attempts: int = 3
    worker_heartbeat_seconds: int = 15
    worker_batch_size: int = 10

    # --- single-worker lease -------------------------------------------------
    worker_lease_seconds: int = 60
    worker_lease_renew_seconds: int = 20

    # --- parsing performance -------------------------------------------------
    # "thread" overlaps database round-trips with parsing. Parsing is CPU-bound
    # Python, so threads do not provide true CPU parallelism (the GIL serialises
    # bytecode). The benchmark showed no gain on the reference workload, so the
    # shipped default is "inline"; "thread" remains configurable.
    parser_executor: str = "inline"
    parser_threads: int = 3
    parser_batch_size: int = 500
    parser_skip_unchanged: bool = True
    parser_max_records: int = 200_000

    # Advisory benchmark targets, never hard gates.
    parser_perf_target_seconds: float = 1.5
    parser_perf_target_csv_rows: int = 50_000

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
