"""Deployment event parser.

Examples::

    2026-11-03T09:00:00Z deploy service=checkout-api version=2.4.1 environment=production actor=ci-runner-7
    2026-11-03T09:05:00Z config_change service=checkout-api key=FEATURE_X old=false new=true
    2026-11-03T09:06:00Z rollback service=checkout-api from=2.4.1 to=2.4.0 actor=oncall
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
    CONFIG_CHANGE_RE,
    clean_value,
    iter_lines,
    parse_kv,
    parse_timestamp,
    split_leading_timestamp,
    strip_kv,
    unparsed,
)

EVENT_TYPES = {
    "deploy",
    "deployment",
    "rollback",
    "restart",
    "scale",
    "config_change",
    "config",
    "release",
    "canary",
}
TRAILING_CONFIG_RE = re.compile(r"config_changes?:\s*(.+)", re.IGNORECASE)


class DeploymentEventParser(BaseParser):
    evidence_type = "deployment_event"
    name = "deployment_event"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        index = 0

        for line_number, raw in iter_lines(text):
            if not raw.strip():
                continue

            timestamp_token, remainder = split_leading_timestamp(raw.strip())
            timestamp = parse_timestamp(timestamp_token)
            tokens = remainder.split(None, 1)
            event_type = tokens[0].lower() if tokens else ""
            body = tokens[1] if len(tokens) > 1 else ""

            kv = parse_kv(body)
            if event_type not in EVENT_TYPES and kv:
                # Allow "service=... event=deploy" ordering.
                event_type = (kv.get("event") or kv.get("event_type") or "").lower()
            if event_type not in EVENT_TYPES:
                event_type = event_type or (kv.get("event") or "").lower()

            config_changes: list[dict] = []
            for match in CONFIG_CHANGE_RE.finditer(body):
                config_changes.append(
                    {
                        "key": match.group(1),
                        "old": match.group(2),
                        "new": match.group(3),
                    }
                )
            trailing = TRAILING_CONFIG_RE.search(body)
            if trailing:
                for match in CONFIG_CHANGE_RE.finditer(trailing.group(1)):
                    change = {
                        "key": match.group(1),
                        "old": match.group(2),
                        "new": match.group(3),
                    }
                    if change not in config_changes:
                        config_changes.append(change)

            single_key = kv.get("key") or kv.get("config_key")
            if single_key and (kv.get("old") is not None or kv.get("new") is not None):
                config_changes.append(
                    {
                        "key": single_key,
                        "old": kv.get("old"),
                        "new": kv.get("new") if "new" in kv else kv.get("value"),
                    }
                )

            attributes = {
                "event_type": event_type or None,
                "service": clean_value(kv.get("service")),
                "version": clean_value(kv.get("version") or kv.get("to")),
                "previous_version": clean_value(kv.get("from") or kv.get("old_version")),
                "environment": clean_value(kv.get("environment") or kv.get("env")),
                "actor": clean_value(kv.get("actor") or kv.get("user")),
                "config_changes": config_changes,
                "old_value": clean_value(kv.get("old")),
                "new_value": clean_value(kv.get("new")),
            }

            message = clean_value(strip_kv(body))
            if not timestamp and not kv and not event_type:
                unparsed(
                    self,
                    records,
                    warnings,
                    filename=filename,
                    index=index,
                    line_number=line_number,
                    line=raw,
                    reason="Line did not match a deployment event format.",
                )
                index += 1
                continue

            content = message or (
                f"{event_type or 'deployment'} {attributes['service'] or ''}".strip()
            )
            records.append(
                self.record(
                    filename=filename,
                    index=index,
                    content=content,
                    record_type="deployment_event",
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
                    message="No deployment events were recognised.",
                )
            )
        return self.result(records, warnings)
