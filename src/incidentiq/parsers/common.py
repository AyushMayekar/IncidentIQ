"""Shared, allocation-conscious helpers for the evidence parsers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterator

# Anchored ISO-8601 timestamps. Pre-compiled once for the whole process.
ISO_TIMESTAMP = (
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
)
LEADING_TIMESTAMP_RE = re.compile(rf"^({ISO_TIMESTAMP})(?=\s|$)")
ISO_TIMESTAMP_RE = re.compile(rf"^{ISO_TIMESTAMP}$")
EPOCH_SECONDS_RE = re.compile(r"^\d{10}$")
EPOCH_MILLIS_RE = re.compile(r"^\d{13}$")

KV_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)="
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,]+)"
)
SEVERITY_TOKEN_RE = re.compile(
    r"^(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|CRIT|CRITICAL|FATAL|"
    r"ALERT|EMERG|EMERGENCY)\b[:\-\s]*",
    re.IGNORECASE,
)
INLINE_SEVERITY_RE = re.compile(
    r"\b(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|CRIT|CRITICAL|FATAL|"
    r"ALERT|EMERG|EMERGENCY)\b",
    re.IGNORECASE,
)
BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*")
BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.*)$")
CONFIG_CHANGE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.-]*)=([^\s,>-]+)->([^\s,]+)"
)

SEVERITY_MAP = {
    "TRACE": "TRACE",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "NOTICE",
    "WARN": "WARN",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "CRIT": "CRITICAL",
    "CRITICAL": "CRITICAL",
    "FATAL": "FATAL",
    "ALERT": "ALERT",
    "EMERG": "EMERGENCY",
    "EMERGENCY": "EMERGENCY",
}


def iter_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(1-based line number, line)`` without copying the whole file."""
    for number, line in enumerate(text.splitlines(), start=1):
        yield number, line


def parse_timestamp(value: str | None) -> datetime | None:
    """Best-effort UTC timestamp. Returns ``None`` rather than guessing."""
    if not value:
        return None
    raw = value.strip().strip(",")
    if not raw:
        return None

    if EPOCH_SECONDS_RE.match(raw):
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    if EPOCH_MILLIS_RE.match(raw):
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    if ISO_TIMESTAMP_RE.match(raw):
        candidate = raw.replace(",", ".")
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def split_leading_timestamp(line: str) -> tuple[str | None, str]:
    """Return the leading timestamp token (if any) and the remaining text."""
    match = LEADING_TIMESTAMP_RE.match(line)
    if not match:
        return None, line
    return match.group(1), line[match.end() :].lstrip()


def parse_kv(text: str) -> dict[str, str]:
    """Extract ``key=value`` pairs, unquoting where needed."""
    values: dict[str, str] = {}
    for match in KV_RE.finditer(text):
        value = match.group("value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[match.group("key")] = value
    return values


def strip_kv(text: str) -> str:
    """Remove ``key=value`` tokens, leaving the human-readable message."""
    return KV_RE.sub("", text)


def pop_first_token(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, ""
    parts = stripped.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def normalize_severity(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().strip("[]():,").upper()
    return SEVERITY_MAP.get(cleaned, cleaned or None)


def detect_severity(text: str) -> tuple[str | None, str]:
    """Pop a leading severity token, or find one anywhere as a fallback."""
    match = SEVERITY_TOKEN_RE.match(text)
    if match:
        return normalize_severity(match.group(1)), text[match.end() :]
    match = INLINE_SEVERITY_RE.search(text)
    if match:
        return normalize_severity(match.group(1)), text
    return None, text


def parse_decimal(value: str | None) -> tuple[str | None, float | None]:
    """Return a precision-preserving string and a float for charts.

    The string is authoritative; the float is a convenience and may lose
    precision. Neither value is invented: unparsable input yields ``(None, None)``.
    """
    if value is None:
        return None, None
    raw = value.strip()
    if not raw:
        return None, None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None, None
    if not number.is_finite():
        return None, None
    return str(number), float(number)


def parse_duration_ms(value: str | None) -> float | None:
    """Parse ``42``, ``42ms``, ``1.5s`` or ``250us`` into milliseconds."""
    if not value:
        return None
    raw = value.strip().lower().replace(",", "")
    try:
        if raw.endswith("ms"):
            return float(raw[:-2])
        if raw.endswith("us"):
            return float(raw[:-2]) / 1000
        if raw.endswith("µs"):
            return float(raw[:-2]) / 1000
        if raw.endswith("s"):
            return float(raw[:-1]) * 1000
        if raw.endswith("m"):
            return float(raw[:-1]) * 60_000
        return float(raw)
    except ValueError:
        return None


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    return None


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def unparsed(
    parser: object,
    records: list,
    warnings: list,
    *,
    filename: str,
    index: int,
    line_number: int,
    line: str,
    reason: str,
) -> None:
    """Append a preserved fallback record plus a warning. Never drop input."""
    from incidentiq.parsers.base import ParseWarning

    records.append(
        parser.record(
            filename=filename,
            index=index,
            content=line,
            record_type="unparsed",
            start_line=line_number,
            attributes={"unparsed": True, "raw": line},
        )
    )
    warnings.append(
        ParseWarning(code="unparsed_line", message=reason, line=line_number)
    )
