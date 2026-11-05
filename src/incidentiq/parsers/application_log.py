"""Application log parser.

Handles the common shape::

    2026-11-03T09:14:05Z ERROR [checkout-api] Payment authorization timed out request_id=req-7f31
    java.lang.RuntimeException: upstream failure
        at com.example.Checkout.authorize(Checkout.java:42)
        ... 3 more

Continuation lines (indented stack frames, ``Caused by:`` and ``... n more``)
are attached to the preceding event instead of becoming noise records.
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
    BRACKET_RE,
    clean_value,
    detect_severity,
    iter_lines,
    normalize_severity,
    parse_kv,
    parse_timestamp,
    split_leading_timestamp,
    strip_kv,
    unparsed,
)

STACK_CONTINUATION_RE = re.compile(r"^\s+(at\s|\.\.\.\s|Caused by:|Suppressed:)")
EXCEPTION_RE = re.compile(
    r"^(?:[a-z][\w]*\.)*[A-Z][\w$]*(?:Exception|Error)(?::.*)?$"
)
KNOWN_KEYS = {
    "service",
    "logger",
    "request_id",
    "trace_id",
    "correlation_id",
    "span_id",
    "user_id",
    "severity",
    "level",
}


class ApplicationLogParser(BaseParser):
    evidence_type = "application_log"
    name = "application_log"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        last = None
        index = 0

        for line_number, raw in iter_lines(text):
            if not raw.strip():
                continue

            raw_stripped = raw.strip()

            # An unindented exception header also belongs to the event above.
            if (
                last is not None
                and EXCEPTION_RE.match(raw_stripped)
                and parse_timestamp(raw_stripped.split(None, 1)[0]) is None
                and not detect_severity(raw_stripped)[0]
            ):
                stack = last.attributes.setdefault("stack_trace", [])
                stack.append(raw_stripped)
                last.attributes["exception"] = raw_stripped
                last.source.end_line = line_number
                continue

            # A stack frame belongs to the event directly above it.
            if last is not None and STACK_CONTINUATION_RE.match(raw):
                frame = raw.strip()
                stack = last.attributes.setdefault("stack_trace", [])
                stack.append(frame)
                last.source.end_line = line_number
                if frame.startswith(("Caused by:", "Suppressed:")):
                    last.attributes["exception"] = frame
                continue

            timestamp_token, remainder = split_leading_timestamp(raw.strip())
            timestamp = parse_timestamp(timestamp_token)
            severity, remainder = detect_severity(remainder)

            service = None
            bracket = BRACKET_RE.match(remainder)
            if bracket:
                service = bracket.group(1)
                remainder = remainder[bracket.end() :]

            kv = parse_kv(remainder)
            service = kv.get("service") or service or kv.get("logger")
            severity = normalize_severity(kv.get("severity") or kv.get("level")) or severity
            message = clean_value(kv.get("message") or kv.get("msg"))
            if message is None:
                message = strip_kv(remainder)
            message = re.sub(r"\s{2,}", " ", message).strip(" -:|")
            message = clean_value(message) or raw.strip()

            attributes: dict = {}
            if service:
                attributes["service"] = service
            if severity:
                attributes["severity"] = severity
            for key in (
                "request_id",
                "trace_id",
                "correlation_id",
                "span_id",
                "user_id",
            ):
                if key in kv:
                    attributes[key] = kv[key]
            extra = {key: value for key, value in kv.items() if key not in KNOWN_KEYS}
            if extra:
                attributes["labels"] = extra

            # A line without a timestamp, severity, service or structured data
            # is still preserved verbatim as an unparsed record.
            if not timestamp and not severity and not service and not kv:
                unparsed(
                    self,
                    records,
                    warnings,
                    filename=filename,
                    index=index,
                    line_number=line_number,
                    line=raw,
                    reason="Line did not match the application log format.",
                )
                index += 1
                last = records[-1]
                continue

            if EXCEPTION_RE.match(raw.strip()):
                attributes["exception"] = raw.strip()

            record = self.record(
                filename=filename,
                index=index,
                content=message,
                record_type="log_event",
                start_line=line_number,
                timestamp_start=timestamp,
                attributes=attributes,
            )
            records.append(record)
            last = record
            index += 1

        if not records and text.strip():
            warnings.append(
                ParseWarning(
                    code="no_records",
                    message="No application log events were recognised.",
                )
            )
        return self.result(records, warnings)
