"""Configuration file parser.

Sections, ``KEY=VALUE`` (or ``KEY: VALUE``) settings and comments are preserved
with their source lines. Content is only ever treated as text: nothing is
evaluated, expanded, imported or executed.
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import clean_value, iter_lines, unparsed

SECTION_RE = re.compile(r"^\[([^\]]+)\]$")
SETTING_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*[=:]\s*(.*)$")
COMMENT_PREFIXES = ("#", ";", "//")


class ConfigurationParser(BaseParser):
    evidence_type = "configuration"
    name = "configuration"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        section: str | None = None
        index = 0

        for line_number, raw in iter_lines(text):
            stripped = raw.strip()
            if not stripped:
                continue

            if stripped.startswith(COMMENT_PREFIXES):
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=stripped,
                        record_type="comment",
                        start_line=line_number,
                        attributes={"section": section, "comment": stripped},
                    )
                )
                index += 1
                continue

            section_match = SECTION_RE.match(stripped)
            if section_match:
                section = clean_value(section_match.group(1))
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=stripped,
                        record_type="section",
                        start_line=line_number,
                        attributes={"section": section},
                    )
                )
                index += 1
                continue

            setting = SETTING_RE.match(stripped)
            if setting:
                key = setting.group(1)
                value = clean_value(setting.group(2))
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=stripped,
                        record_type="setting",
                        start_line=line_number,
                        attributes={
                            "section": section,
                            "key": key,
                            "value": value,
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
                reason="Line is not a section, comment or KEY=VALUE setting.",
            )
            index += 1

        if not records and text.strip():
            warnings.append(
                ParseWarning(
                    code="no_records",
                    message="No configuration settings were recognised.",
                )
            )
        return self.result(records, warnings)
