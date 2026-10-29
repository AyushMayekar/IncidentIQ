from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["open", "investigating", "resolved", "closed"]


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)
    service: str | None = Field(default=None, max_length=200)
    severity: Severity = "medium"
    occurred_at: datetime | None = None

    @field_validator("title", "description")
    @classmethod
    def required_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("service")
    @classmethod
    def clean_service(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=20_000)
    service: str | None = Field(default=None, max_length=200)
    severity: Severity | None = None
    status: IncidentStatus | None = None
    occurred_at: datetime | None = None

    @field_validator("title", "description")
    @classmethod
    def update_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str
    service: str | None
    severity: Severity
    status: IncidentStatus
    occurred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentListRead(BaseModel):
    items: list[IncidentRead]
    total: int
    limit: int
    offset: int
