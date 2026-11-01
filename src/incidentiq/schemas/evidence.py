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
    """Evidence metadata. Deliberately has no raw_content field."""

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