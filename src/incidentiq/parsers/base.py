"""Common parsed-record contract shared by every evidence parser.

Nothing here touches the database. Parsers are pure functions so they can run
inline, in a thread pool, or (later) in worker processes without changes.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

PARSER_VERSION = "1"


class SourceRef(BaseModel):
    """Where a record came from. Lines are 1-based and inclusive."""

    filename: str
    start_line: int
    end_line: int
    record_index: int


class ParsedRecord(BaseModel):
    """One derived record. IDs are filled in by the processing service."""

    record_id: str
    incident_id: str | None = None
    evidence_id: str | None = None
    evidence_type: str
    record_type: str
    content: str
    timestamp_start: datetime | None = None
    timestamp_end: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: SourceRef
    parser_name: str
    parser_version: str


class ParseWarning(BaseModel):
    """A non-fatal problem. Warnings never cause records to be dropped."""

    code: str
    message: str
    line: int | None = None


class ParseResult(BaseModel):
    records: list[ParsedRecord] = Field(default_factory=list)
    warnings: list[ParseWarning] = Field(default_factory=list)
    parser_name: str
    parser_version: str


def stable_record_id(
    parser_name: str,
    filename: str,
    start_line: int,
    end_line: int,
    record_index: int,
    content: str,
) -> str:
    """Deterministic within a file, so retries cannot duplicate or churn IDs."""
    material = "\x1f".join(
        [
            parser_name,
            filename,
            str(start_line),
            str(end_line),
            str(record_index),
            content,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class BaseParser(ABC):
    """Base class for the eight deterministic evidence parsers."""

    evidence_type: str
    name: str
    version: str = PARSER_VERSION

    @abstractmethod
    def parse(self, text: str, filename: str) -> ParseResult:
        """Parse ``text``. Never raises for malformed input; returns warnings."""

    # -- helpers ---------------------------------------------------------
    def result(
        self, records: list[ParsedRecord], warnings: list[ParseWarning] | None = None
    ) -> ParseResult:
        return ParseResult(
            records=records,
            warnings=warnings or [],
            parser_name=self.name,
            parser_version=self.version,
        )

    def record(
        self,
        *,
        filename: str,
        index: int,
        content: str,
        record_type: str,
        start_line: int,
        end_line: int | None = None,
        timestamp_start: datetime | None = None,
        timestamp_end: datetime | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> ParsedRecord:
        end = start_line if end_line is None else end_line
        return ParsedRecord(
            record_id=stable_record_id(
                self.name, filename, start_line, end, index, content
            ),
            evidence_type=self.evidence_type,
            record_type=record_type,
            content=content,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            attributes=attributes or {},
            source=SourceRef(
                filename=filename,
                start_line=start_line,
                end_line=end,
                record_index=index,
            ),
            parser_name=self.name,
            parser_version=self.version,
        )
