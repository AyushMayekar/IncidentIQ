from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

EvidenceType = Literal[
    "application_log",
    "infrastructure_log",
    "metrics",
    "trace",
    "deployment_event",
    "alert",
    "configuration",
    "manual_context",
]


class EvidenceRead(BaseModel):
    """Evidence metadata. Deliberately has no raw_content field.

    Processing fields are derived from the evidence job and are safe to expose:
    no stack traces, paths or secrets are ever stored in ``error_message``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    source_name: str
    # Legacy (seeded) rows have no evidence type, so reads must allow None.
    evidence_type: str | None
    content_type: str
    content_hash: str
    byte_size: int
    parse_status: str
    created_at: datetime
    error_message: str | None = None
    record_count: int = 0
    processed_at: datetime | None = None
    processing_duration_ms: int | None = None
