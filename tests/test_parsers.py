"""Deterministic parser tests for all eight evidence types."""

from __future__ import annotations

from datetime import timezone

import pytest

from incidentiq.parsers import PARSERS, require_parser, supported_types

APPLICATION_LOG = """2026-11-03T09:14:05Z ERROR [checkout-api] Payment authorization timed out request_id=req-7f31 trace_id=tr-1
java.lang.RuntimeException: upstream failure
    at com.example.Checkout.authorize(Checkout.java:42)
    ... 3 more
2026-11-03T09:14:06Z INFO [checkout-api] Request completed status=200
garbage line without structure
"""

INFRASTRUCTURE_LOG = """2026-11-03T09:14:05Z host=node-1 container=api-7 component=ingress severity=ERROR message="upstream timeout" cpu=0.82 mem_mb=512
<134>Nov  3 09:14:05 node-2 nginx[123]: upstream timed out
"""

METRICS_CSV = """timestamp,metric,value,unit,labels
2026-11-03T09:00:00Z,http_latency_p99,123.4500,ms,"service=checkout,region=us-east-1"
2026-11-03T09:01:00Z,http_errors,0,count,"service=checkout"
not-a-row,broken,oops,,,
"""

TRACE = """TRACE_ID trace-abc
SPAN span-1 service=checkout-api operation="POST /pay" duration_ms=42 status=OK
  SPAN span-2 service=payments-db operation="SELECT payments" duration=8ms
  EVENT span-2 name=cache_miss
EVENT span-1 name=retry value=1
TRACE_END trace-abc
"""

DEPLOYMENT = """2026-11-03T09:00:00Z deploy service=checkout-api version=2.4.1 environment=production actor=ci-runner-7
2026-11-03T09:05:00Z config_change service=checkout-api config_changes: FEATURE_X=false->true
2026-11-03T09:06:00Z rollback service=checkout-api from=2.4.1 to=2.4.0 actor=oncall
"""

ALERTS = """Alert: Payment latency high
severity: critical
service: checkout-api
environment: production
start: 2026-11-03T09:10:00Z
observed: 1200ms
threshold: 500ms
region: us-east-1
impact: checkout failures
status: firing
- p99 above threshold

Alert: Disk pressure
severity: warning
unknown line without separator
"""

CONFIGURATION = """# checkout config
[server]
retries=3
timeout_ms=2500
this is not valid
"""

MANUAL = """# Runbook

Restart the payment workers.
They may take 30 seconds.

## Checks
- verify queues
1. open dashboard
"""


def test_registry_covers_all_eight_types() -> None:
    expected = {
        "application_log",
        "infrastructure_log",
        "metrics",
        "trace",
        "deployment_event",
        "alert",
        "configuration",
        "manual_context",
    }
    assert set(supported_types()) == expected
    assert set(PARSERS) == expected
    for evidence_type in expected:
        assert require_parser(evidence_type).evidence_type == evidence_type
    with pytest.raises(KeyError):
        require_parser("unknown_type")


@pytest.mark.parametrize("evidence_type", sorted(PARSERS))
def test_empty_or_whitespace_content_is_safe(evidence_type: str) -> None:
    parser = require_parser(evidence_type)
    assert parser.parse("", "empty.log").records == []
    assert parser.parse("   \n\n", "empty.log").records == []


def test_application_log_fields_and_stack_trace() -> None:
    result = require_parser("application_log").parse(APPLICATION_LOG, "app.log")
    events = [record for record in result.records if record.record_type == "log_event"]
    unparsed = [record for record in result.records if record.record_type == "unparsed"]

    assert len(events) == 2
    assert len(unparsed) == 1

    first = events[0]
    assert first.content == "Payment authorization timed out"
    assert first.timestamp_start is not None
    assert first.timestamp_start.tzinfo == timezone.utc
    assert first.attributes["severity"] == "ERROR"
    assert first.attributes["service"] == "checkout-api"
    assert first.attributes["request_id"] == "req-7f31"
    assert first.attributes["trace_id"] == "tr-1"
    assert first.attributes["exception"] == "java.lang.RuntimeException: upstream failure"
    assert first.attributes["stack_trace"] == [
        "java.lang.RuntimeException: upstream failure",
        "at com.example.Checkout.authorize(Checkout.java:42)",
        "... 3 more",
    ]
    assert first.source.start_line == 1
    assert first.source.end_line == 4
    assert first.source.record_index == 0

    # The unparsed line is preserved verbatim, not dropped.
    assert unparsed[0].content == "garbage line without structure"
    assert unparsed[0].source.start_line == 6
    assert any(w.code == "unparsed_line" for w in result.warnings)


def test_infrastructure_log_structured_and_syslog() -> None:
    result = require_parser("infrastructure_log").parse(
        INFRASTRUCTURE_LOG, "infra.log"
    )
    assert len(result.records) == 2

    structured = result.records[0]
    assert structured.content == "upstream timeout"
    assert structured.timestamp_start is not None
    assert structured.attributes["host"] == "node-1"
    assert structured.attributes["container"] == "api-7"
    assert structured.attributes["component"] == "ingress"
    assert structured.attributes["severity"] == "ERROR"
    assert structured.attributes["resources"] == {"cpu": "0.82", "mem_mb": "512"}

    syslog = result.records[1]
    assert syslog.timestamp_start is None  # no year: never invented
    assert syslog.attributes["host"] == "node-2"
    assert syslog.attributes["component"] == "nginx"
    assert syslog.attributes["pid"] == 123
    assert syslog.content == "upstream timed out"


def test_metrics_values_units_labels_and_precision() -> None:
    result = require_parser("metrics").parse(METRICS_CSV, "metrics.csv")
    samples = [record for record in result.records if record.record_type == "metric_sample"]
    unparsed = [record for record in result.records if record.record_type == "unparsed"]

    assert len(samples) == 2
    assert len(unparsed) == 1

    first = samples[0]
    assert first.attributes["metric"] == "http_latency_p99"
    assert first.attributes["value"] == "123.4500"  # precision preserved as text
    assert first.attributes["value_number"] == 123.45
    assert first.attributes["unit"] == "ms"
    assert first.attributes["labels"] == {"service": "checkout", "region": "us-east-1"}
    assert first.timestamp_start is not None
    assert first.source.start_line == 2

    assert samples[1].attributes["unit"] == "count"
    assert unparsed[0].source.start_line == 4
    assert unparsed[0].content.startswith("not-a-row")


def test_trace_hierarchy_durations_and_events() -> None:
    result = require_parser("trace").parse(TRACE, "trace.txt")
    spans = {
        record.attributes["span_id"]: record
        for record in result.records
        if record.record_type == "span"
    }
    events = [record for record in result.records if record.record_type == "event"]

    assert set(spans) == {"span-1", "span-2"}
    assert spans["span-1"].attributes["parent_span_id"] is None
    assert spans["span-2"].attributes["parent_span_id"] == "span-1"  # indentation
    assert spans["span-1"].attributes["trace_id"] == "trace-abc"
    assert spans["span-1"].attributes["duration_ms"] == 42
    assert spans["span-2"].attributes["duration_ms"] == 8
    assert spans["span-1"].attributes["service"] == "checkout-api"
    assert spans["span-1"].attributes["status"] == "OK"

    assert len(events) == 2
    assert spans["span-2"].attributes["events"][0]["name"] == "cache_miss"
    assert spans["span-1"].attributes["events"][0]["name"] == "retry"
    assert [record.source.record_index for record in result.records] == [0, 1, 2, 3]


def test_deployment_events_and_config_changes() -> None:
    result = require_parser("deployment_event").parse(DEPLOYMENT, "deploy.log")
    assert len(result.records) == 3

    deploy, config, rollback = result.records
    assert deploy.attributes["event_type"] == "deploy"
    assert deploy.attributes["service"] == "checkout-api"
    assert deploy.attributes["version"] == "2.4.1"
    assert deploy.attributes["environment"] == "production"
    assert deploy.attributes["actor"] == "ci-runner-7"

    assert config.attributes["event_type"] == "config_change"
    assert config.attributes["config_changes"] == [
        {"key": "FEATURE_X", "old": "false", "new": "true"}
    ]

    assert rollback.attributes["event_type"] == "rollback"
    assert rollback.attributes["version"] == "2.4.0"
    assert rollback.attributes["previous_version"] == "2.4.1"
    assert rollback.attributes["actor"] == "oncall"


def test_alert_key_values_bullets_and_notes() -> None:
    result = require_parser("alert").parse(ALERTS, "alerts.txt")
    assert len(result.records) == 2

    first, second = result.records
    assert first.content == "Payment latency high"
    assert first.attributes["severity"] == "CRITICAL"
    assert first.attributes["observed_value"] == "1200ms"
    assert first.attributes["threshold"] == "500ms"
    assert first.attributes["region"] == "us-east-1"
    assert first.attributes["impact"] == "checkout failures"
    assert first.attributes["bullets"] == ["p99 above threshold"]
    assert first.timestamp_start is not None
    assert first.source.start_line == 1
    assert first.source.end_line == 11

    assert second.content == "Disk pressure"
    assert second.attributes["severity"] == "WARN"
    assert second.attributes["notes"] == ["unknown line without separator"]
    assert any(w.code == "unstructured_alert_line" for w in result.warnings)


def test_configuration_preserves_sections_keys_and_comments() -> None:
    result = require_parser("configuration").parse(CONFIGURATION, "app.conf")
    kinds = [record.record_type for record in result.records]
    assert kinds == ["comment", "section", "setting", "setting", "unparsed"]

    section = result.records[1]
    assert section.attributes["section"] == "server"

    retries = result.records[2]
    assert retries.attributes == {
        "section": "server",
        "key": "retries",
        "value": "3",
    }
    assert retries.source.start_line == 3

    assert result.records[4].content == "this is not valid"


def test_manual_context_headings_paragraphs_and_lists() -> None:
    result = require_parser("manual_context").parse(MANUAL, "notes.txt")
    kinds = [record.record_type for record in result.records]
    assert kinds == [
        "heading",
        "paragraph",
        "heading",
        "list_item",
        "list_item",
    ]

    heading = result.records[0]
    assert heading.content == "Runbook"
    assert heading.attributes["level"] == 1

    paragraph = result.records[1]
    assert paragraph.content == (
        "Restart the payment workers.\nThey may take 30 seconds."
    )

    assert result.records[3].content == "verify queues"
    assert result.records[3].attributes["ordered"] is False
    assert result.records[4].attributes["ordered"] is True


@pytest.mark.parametrize("evidence_type", sorted(PARSERS))
def test_provenance_and_parser_version_are_always_recorded(
    evidence_type: str,
) -> None:
    samples = {
        "application_log": APPLICATION_LOG,
        "infrastructure_log": INFRASTRUCTURE_LOG,
        "metrics": METRICS_CSV,
        "trace": TRACE,
        "deployment_event": DEPLOYMENT,
        "alert": ALERTS,
        "configuration": CONFIGURATION,
        "manual_context": MANUAL,
    }
    parser = require_parser(evidence_type)
    result = parser.parse(samples[evidence_type], f"{evidence_type}.txt")

    assert result.records, "each evidence type should produce records"
    for index, record in enumerate(result.records):
        assert record.source.filename == f"{evidence_type}.txt"
        assert record.source.record_index == index
        assert record.source.start_line >= 1
        assert record.source.end_line >= record.source.start_line
        assert record.parser_name == evidence_type
        assert record.parser_version == "1"
        assert record.evidence_type == evidence_type
        assert record.record_id
    # Ordering is stable, so record IDs are deterministic across runs.
    again = parser.parse(samples[evidence_type], f"{evidence_type}.txt")
    assert [record.record_id for record in result.records] == [
        record.record_id for record in again.records
    ]
