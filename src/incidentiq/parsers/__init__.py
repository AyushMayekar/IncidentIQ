"""Parser registry and dispatch.

Parsers are pure and stateless; the registry holds one instance per evidence
type. Unknown types raise ``KeyError`` from :func:`require_parser` so the
processing service can fail the job with a safe, specific message.
"""

from __future__ import annotations

from incidentiq.parsers.alert import AlertParser
from incidentiq.parsers.application_log import ApplicationLogParser
from incidentiq.parsers.base import (
    BaseParser,
    ParsedRecord,
    ParseResult,
    ParseWarning,
    SourceRef,
)
from incidentiq.parsers.configuration import ConfigurationParser
from incidentiq.parsers.deployment_event import DeploymentEventParser
from incidentiq.parsers.infrastructure_log import InfrastructureLogParser
from incidentiq.parsers.manual_context import ManualContextParser
from incidentiq.parsers.metrics import MetricsParser
from incidentiq.parsers.trace import TraceParser

PARSERS: dict[str, BaseParser] = {
    parser.evidence_type: parser
    for parser in (
        ApplicationLogParser(),
        InfrastructureLogParser(),
        MetricsParser(),
        TraceParser(),
        DeploymentEventParser(),
        AlertParser(),
        ConfigurationParser(),
        ManualContextParser(),
    )
}


def get_parser(evidence_type: str | None) -> BaseParser | None:
    if not evidence_type:
        return None
    return PARSERS.get(evidence_type)


def require_parser(evidence_type: str | None) -> BaseParser:
    parser = get_parser(evidence_type)
    if parser is None:
        raise KeyError(f"No parser is registered for evidence type {evidence_type!r}.")
    return parser


def supported_types() -> tuple[str, ...]:
    return tuple(PARSERS)


__all__ = [
    "BaseParser",
    "PARSERS",
    "ParseResult",
    "ParseWarning",
    "ParsedRecord",
    "SourceRef",
    "get_parser",
    "require_parser",
    "supported_types",
]
