"""Infrastructure log parser.

Supports structured key/value lines and traditional syslog-shaped lines::

    2026-11-03T09:14:05Z host=node-1 container=api-7 component=ingress severity=ERROR message="upstream timeout" cpu=0.82
    <134>Nov  3 09:14:05 node-1 nginx[123]: upstream timed out
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
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

SYSLOG_RE = re.compile(
    r"^<(?P<priority>\d{1,3})>(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<host>\S+)\s+"
    r"(?P<component>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<message>.*)$"
)

HOST_KEYS = ("host", "hostname", "node", "node_name")
RESOURCE_KEYS = {
    "cpu",
    "cpu_percent",
    "memory",
    "mem",
    "memory_mb",
    "mem_mb",
    "disk",
    "disk_percent",
    "load",
    "load_1m",
    "network",
    "gpu",
}
KNOWN_KEYS = {
    "host",
    "hostname",
    "node",
    "node_name",
    "container",
    "component",
    "service",
    "unit",
    "app",
    "severity",
    "level",
    "message",
    "msg",
    "event",
}


class InfrastructureLogParser(BaseParser):
    evidence_type = "infrastructure_log"
    name = "infrastructure_log"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        index = 0

        for line_number, raw in iter_lines(text):
            if not raw.strip():
                continue

            syslog = SYSLOG_RE.match(raw.strip())
            if syslog:
                attributes = {
                    "host": syslog.group("host"),
                    "component": syslog.group("component"),
                    "priority": int(syslog.group("priority")),
                }
                if syslog.group("pid"):
                    attributes["pid"] = int(syslog.group("pid"))
                message = clean_value(syslog.group("message"))
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=message or raw.strip(),
                        record_type="infra_event",
                        start_line=line_number,
                        # No year in syslog timestamps: never invent one.
                        timestamp_start=None,
                        attributes=attributes,
                    )
                )
                index += 1
                continue

            timestamp_token, remainder = split_leading_timestamp(raw.strip())
            timestamp = parse_timestamp(timestamp_token)
            kv = parse_kv(remainder)
            severity = normalize_severity(
                kv.get("severity") or kv.get("level")
            ) or detect_severity(remainder)[0]

            host = next((kv[key] for key in HOST_KEYS if key in kv), None)
            attributes: dict = {}
            for key, value in (
                ("host", host),
                ("container", kv.get("container")),
                ("component", kv.get("component") or kv.get("unit") or kv.get("app")),
                ("service", kv.get("service")),
                ("severity", severity),
            ):
                if value:
                    attributes[key] = value

            resources = {
                key: kv[key] for key in RESOURCE_KEYS if key in kv
            }
            if resources:
                attributes["resources"] = resources
            extra = {
                key: value
                for key, value in kv.items()
                if key not in KNOWN_KEYS and key not in RESOURCE_KEYS
            }
            if extra:
                attributes["labels"] = extra

            message = clean_value(
                kv.get("message") or kv.get("msg") or kv.get("event")
            )
            if message is None:
                message = clean_value(strip_kv(remainder))
            message = re.sub(r"\s{2,}", " ", message or "").strip(" -:|")

            if not timestamp and not kv and not severity:
                unparsed(
                    self,
                    records,
                    warnings,
                    filename=filename,
                    index=index,
                    line_number=line_number,
                    line=raw,
                    reason="Line did not match an infrastructure log format.",
                )
                index += 1
                continue

            records.append(
                self.record(
                    filename=filename,
                    index=index,
                    content=message or raw.strip(),
                    record_type="infra_event",
                    start_line=line_number,
                    timestamp_start=timestamp,
                    attributes=attributes,
                )
            )
            index += 1

        if not records and text.strip():
            warnings.append(
                ParseWarning(
                    code="no_records",
                    message="No infrastructure events were recognised.",
                )
            )
        return self.result(records, warnings)
