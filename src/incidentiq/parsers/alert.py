"""Alert parser for multiline key/value alerts and bullet lists.

A block ends at a blank line::

    Alert: Payment latency high
    severity: critical
    service: checkout-api
    environment: production
    start: 2026-11-03T09:10:00Z
    observed: 1200ms
    threshold: 500ms
    region: us-east-1
    impact: checkout failures
    status: firing
    - p99 above threshold for 10 minutes
    - customer reports timeouts
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
    BULLET_RE,
    clean_value,
    iter_lines,
    normalize_severity,
    parse_timestamp,
    unparsed,
)

KEY_MAP = {
    "name": "name",
    "alert": "name",
    "alert_name": "name",
    "title": "name",
    "severity": "severity",
    "level": "severity",
    "service": "service",
    "environment": "environment",
    "env": "environment",
    "start": "start_time",
    "start_time": "start_time",
    "started": "start_time",
    "started_at": "start_time",
    "observed": "observed_value",
    "observed_value": "observed_value",
    "value": "observed_value",
    "threshold": "threshold",
    "region": "region",
    "regions": "region",
    "impact": "impact",
    "status": "status",
}
KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 _-]*?)\s*[:=]\s*(.*)$")


class AlertParser(BaseParser):
    evidence_type = "alert"
    name = "alert"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        index = 0

        for block in _blocks(text):
            if not block:
                continue
            attributes: dict = {}
            bullets: list[str] = []
            notes: list[str] = []
            start_line = block[0][0]
            end_line = block[-1][0]
            first_line = block[0][1].strip()

            # "Alert: ..." is a header, not just another key.
            header = re.match(r"^alert\s*:\s*(.+)$", first_line, re.IGNORECASE)
            if header:
                attributes["name"] = clean_value(header.group(1))
            elif first_line.startswith("#"):
                attributes["name"] = clean_value(first_line.lstrip("#"))
            elif first_line.startswith("**") and first_line.endswith("**"):
                attributes["name"] = clean_value(first_line.strip("*"))

            for line_number, raw in block:
                stripped = raw.strip()
                if not stripped:
                    continue

                bullet = BULLET_RE.match(stripped)
                if bullet:
                    bullets.append(bullet.group(1).strip())
                    continue

                key_match = KEY_RE.match(stripped)
                if key_match:
                    key = key_match.group(1).strip().lower().replace(" ", "_")
                    value = clean_value(key_match.group(2))
                    canonical = KEY_MAP.get(key, key)
                    if canonical == "severity":
                        attributes[canonical] = normalize_severity(value) or value
                    elif value is not None:
                        attributes[canonical] = value
                    continue

                if stripped.startswith("alert") and "name" not in attributes:
                    attributes["name"] = clean_value(stripped[5:].lstrip(": "))
                    continue

                notes.append(stripped)
                warnings.append(
                    ParseWarning(
                        code="unstructured_alert_line",
                        message="Alert line had no key/value structure; kept as a note.",
                        line=line_number,
                    )
                )

            if not attributes and not bullets and not notes:
                continue

            if not attributes and not bullets:
                # Nothing structured at all: preserve the raw block instead of
                # pretending it is an alert.
                unparsed(
                    self,
                    records,
                    warnings,
                    filename=filename,
                    index=index,
                    line_number=start_line,
                    line="\n".join(raw for _, raw in block),
                    reason="Block did not contain an alert key/value structure.",
                )
                index += 1
                continue

            if bullets:
                attributes["bullets"] = bullets
            if notes:
                attributes["notes"] = notes
            attributes.setdefault("severity", None)

            content = (
                attributes.get("name")
                or (bullets[0] if bullets else None)
                or (notes[0] if notes else None)
                or "Alert"
            )
            records.append(
                self.record(
                    filename=filename,
                    index=index,
                    content=content,
                    record_type="alert",
                    start_line=start_line,
                    end_line=end_line,
                    timestamp_start=parse_timestamp(attributes.get("start_time")),
                    attributes=attributes,
                )
            )
            index += 1

        if not records and text.strip():
            warnings.append(
                ParseWarning(code="no_records", message="No alerts were recognised.")
            )
        return self.result(records, warnings)


def _blocks(text: str) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line_number, line in iter_lines(text):
        if line.strip():
            current.append((line_number, line))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks
