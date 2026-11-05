"""Manual context parser.

Keeps the operator's notes verbatim: headings, paragraphs, bullet/numbered
lists and fenced code are identified, never summarised or rewritten.
"""

from __future__ import annotations

import re

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import BULLET_RE, NUMBERED_RE, iter_lines

ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SETEXT_RE = re.compile(r"^(=+|-+)\s*$")
FENCE_RE = re.compile(r"^(```|~~~)(.*)$")


class ManualContextParser(BaseParser):
    evidence_type = "manual_context"
    name = "manual_context"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        lines = list(iter_lines(text))
        index = 0
        position = 0
        paragraph: list[tuple[int, str]] = []

        def flush_paragraph() -> None:
            nonlocal index
            if not paragraph:
                return
            start = paragraph[0][0]
            end = paragraph[-1][0]
            content = "\n".join(line for _, line in paragraph).strip()
            if content:
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=content,
                        record_type="paragraph",
                        start_line=start,
                        end_line=end,
                        attributes={"line_count": len(paragraph)},
                    )
                )
                index += 1
            paragraph.clear()

        while position < len(lines):
            line_number, raw = lines[position]
            stripped = raw.strip()

            if not stripped:
                flush_paragraph()
                position += 1
                continue

            fence = FENCE_RE.match(stripped)
            if fence:
                flush_paragraph()
                marker = fence.group(1)
                language = fence.group(2).strip() or None
                start = line_number
                body: list[str] = []
                position += 1
                while position < len(lines):
                    inner_number, inner_raw = lines[position]
                    if inner_raw.strip().startswith(marker):
                        break
                    body.append(inner_raw)
                    position += 1
                end = lines[position][0] if position < len(lines) else start
                if position >= len(lines):
                    warnings.append(
                        ParseWarning(
                            code="unclosed_fence",
                            message="Code fence was not closed; kept to end of file.",
                            line=start,
                        )
                    )
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content="\n".join(body),
                        record_type="code_block",
                        start_line=start,
                        end_line=end,
                        attributes={"language": language},
                    )
                )
                index += 1
                position += 1
                continue

            heading = ATX_HEADING_RE.match(stripped)
            if heading:
                flush_paragraph()
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=heading.group(2).strip(),
                        record_type="heading",
                        start_line=line_number,
                        attributes={
                            "level": len(heading.group(1)),
                            "raw": stripped,
                        },
                    )
                )
                index += 1
                position += 1
                continue

            # Setext heading: a single paragraph line underlined with === or ---.
            if (
                SETEXT_RE.match(stripped)
                and len(paragraph) == 1
            ):
                start_line, title = paragraph[0]
                paragraph.clear()
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=title.strip(),
                        record_type="heading",
                        start_line=start_line,
                        end_line=line_number,
                        attributes={
                            "level": 1 if stripped.startswith("=") else 2,
                            "raw": title.strip(),
                        },
                    )
                )
                index += 1
                position += 1
                continue

            bullet = BULLET_RE.match(stripped)
            numbered = NUMBERED_RE.match(stripped)
            if bullet or numbered:
                flush_paragraph()
                text_value = (bullet or numbered).group(1).strip()
                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=text_value,
                        record_type="list_item",
                        start_line=line_number,
                        attributes={
                            "ordered": numbered is not None,
                            "level": max(0, (len(raw) - len(raw.lstrip())) // 2),
                            "raw": raw,
                        },
                    )
                )
                index += 1
                position += 1
                continue

            paragraph.append((line_number, raw.rstrip()))
            position += 1

        flush_paragraph()

        if not records and text.strip():
            warnings.append(
                ParseWarning(
                    code="no_records",
                    message="No headings, paragraphs or lists were recognised.",
                )
            )
        return self.result(records, warnings)
