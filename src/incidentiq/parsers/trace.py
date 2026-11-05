"""Trace text parser.

Supported directives::

    TRACE_ID trace-abc
    SPAN span-1 parent=span-0 service=checkout-api operation="POST /pay" duration_ms=42 status=OK
      SPAN span-2 service=payments-db operation="SELECT payments" duration=8ms
      EVENT span-2 name=cache_miss detail="cold cache"
    EVENT span-1 name=retry_count value=2
    TRACE_END trace-abc

Parent spans are only taken from an explicit ``parent``/``parent_span_id``
attribute or from indentation of a currently open span. No relationship is
ever invented.
"""

from __future__ import annotations

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
    clean_value,
    iter_lines,
    parse_duration_ms,
    parse_kv,
    parse_timestamp,
    split_leading_timestamp,
    unparsed,
)


class TraceParser(BaseParser):
    evidence_type = "trace"
    name = "trace"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        spans: dict[str, object] = {}
        stack: list[tuple[int, str]] = []
        current_trace: str | None = None
        index = 0

        for line_number, raw in iter_lines(text):
            stripped = raw.strip()
            if not stripped:
                continue

            keyword = stripped.split(None, 1)[0].upper()

            if keyword == "TRACE_ID":
                current_trace = stripped.split(None, 1)[1].strip() or None
                if not current_trace:
                    warnings.append(
                        ParseWarning(
                            code="missing_trace_id",
                            message="TRACE_ID directive had no value.",
                            line=line_number,
                        )
                    )
                continue

            if keyword == "TRACE_END":
                parts = stripped.split(None, 1)
                ended = parts[1].strip() if len(parts) > 1 else None
                if current_trace and ended and ended != current_trace:
                    warnings.append(
                        ParseWarning(
                            code="trace_end_mismatch",
                            message=f"TRACE_END {ended!r} did not match open trace {current_trace!r}.",
                            line=line_number,
                        )
                    )
                stack.clear()
                current_trace = None
                continue

            if keyword == "SPAN":
                body = stripped[len("SPAN") :].strip()
                identifier, body = _span_identifier(body)
                kv = parse_kv(body)
                if not identifier:
                    identifier = kv.get("id") or kv.get("span_id")
                if not identifier:
                    unparsed(
                        self,
                        records,
                        warnings,
                        filename=filename,
                        index=index,
                        line_number=line_number,
                        line=raw,
                        reason="SPAN line had no span identifier.",
                    )
                    index += 1
                    continue

                indent = len(raw) - len(raw.lstrip())
                explicit_parent = kv.get("parent") or kv.get("parent_span_id")
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                inferred_parent = stack[-1][1] if stack else None
                parent = explicit_parent or inferred_parent

                trace_id = kv.get("trace_id") or current_trace
                timestamp_token, body_without_time = split_leading_timestamp(body)
                duration_raw = (
                    kv.get("duration_ms")
                    or kv.get("duration")
                    or kv.get("elapsed")
                )
                attributes = {
                    "trace_id": trace_id,
                    "span_id": identifier,
                    "parent_span_id": parent,
                    "service": clean_value(kv.get("service")),
                    "operation": clean_value(kv.get("operation") or kv.get("name")),
                    "duration_ms": parse_duration_ms(duration_raw),
                    "status": clean_value(kv.get("status")),
                    "events": [],
                }
                content = (
                    attributes["operation"]
                    or kv.get("message")
                    or f"span {identifier}"
                )
                record = self.record(
                    filename=filename,
                    index=index,
                    content=content,
                    record_type="span",
                    start_line=line_number,
                    timestamp_start=parse_timestamp(timestamp_token),
                    attributes=attributes,
                )
                records.append(record)
                spans[identifier] = record
                stack.append((indent, identifier))
                index += 1
                continue

            if keyword == "EVENT":
                body = stripped[len("EVENT") :].strip()
                span_id, body = _span_identifier(body)
                kv = parse_kv(body)
                if not span_id:
                    span_id = kv.get("span_id") or kv.get("span")
                if not span_id and stack:
                    span_id = stack[-1][1]
                if not span_id:
                    unparsed(
                        self,
                        records,
                        warnings,
                        filename=filename,
                        index=index,
                        line_number=line_number,
                        line=raw,
                        reason="EVENT line could not be associated with a span.",
                    )
                    index += 1
                    continue

                name = clean_value(kv.get("name") or kv.get("event")) or "event"
                event = {
                    "name": name,
                    "detail": clean_value(kv.get("detail") or kv.get("message")),
                    "value": clean_value(kv.get("value")),
                    "span_id": span_id,
                }
                span_record = spans.get(span_id)
                if span_record is not None:
                    span_record.attributes.setdefault("events", []).append(event)
                    span_record.source.end_line = max(
                        span_record.source.end_line, line_number
                    )
                else:
                    warnings.append(
                        ParseWarning(
                            code="orphan_event",
                            message=f"Event referenced unknown span {span_id!r}.",
                            line=line_number,
                        )
                    )

                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=name,
                        record_type="event",
                        start_line=line_number,
                        timestamp_start=None,
                        attributes={
                            "trace_id": current_trace,
                            "span_id": span_id,
                            "name": name,
                            "detail": event["detail"],
                            "value": event["value"],
                        },
                    )
                )
                index += 1
                continue

            unparsed(
                self,
                records,
                warnings,
                filename=filename,
                index=index,
                line_number=line_number,
                line=raw,
                reason="Line did not start with TRACE_ID, SPAN, EVENT or TRACE_END.",
            )
            index += 1

        if not records and text.strip():
            warnings.append(
                ParseWarning(code="no_records", message="No trace spans were recognised.")
            )
        return self.result(records, warnings)


def _span_identifier(body: str) -> tuple[str | None, str]:
    """Pop a leading bare identifier, leaving key/value attributes behind."""
    parts = body.split(None, 1)
    if not parts:
        return None, ""
    first = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if "=" in first:
        return None, body
    return first.rstrip(",;:"), rest
