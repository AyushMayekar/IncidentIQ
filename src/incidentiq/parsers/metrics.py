"""Metrics parser.

Uses the standard-library ``csv`` module (C-accelerated) so quoted fields and
large files stay fast. Values are stored as precision-preserving strings; a
float copy is added for convenience only.
"""

from __future__ import annotations

import csv
import io
import json

from incidentiq.parsers.base import BaseParser, ParseResult, ParseWarning
from incidentiq.parsers.common import (
    parse_decimal,
    parse_kv,
    parse_timestamp,
    unparsed,
)

TIMESTAMP_NAMES = {"timestamp", "time", "ts", "date", "datetime"}
METRIC_NAMES = {"metric", "metric_name", "name"}
VALUE_NAMES = {"value", "val", "measurement"}
UNIT_NAMES = {"unit", "units"}
LABEL_NAMES = {"labels", "tags", "label"}
ALL_KNOWN = TIMESTAMP_NAMES | METRIC_NAMES | VALUE_NAMES | UNIT_NAMES | LABEL_NAMES


def _normalized(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _looks_like_header(row: list[str]) -> bool:
    names = {_normalized(cell) for cell in row if cell and cell.strip()}
    return bool(names & ALL_KNOWN)


def _split_labels(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"labels_raw": text}
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items()}
        return {"labels_raw": text}
    return parse_kv(text)


class MetricsParser(BaseParser):
    evidence_type = "metrics"
    name = "metrics"

    def parse(self, text: str, filename: str) -> ParseResult:
        records: list = []
        warnings: list[ParseWarning] = []
        lines = text.splitlines()
        index = 0
        header: list[str] | None = None

        reader = csv.reader(io.StringIO(text))
        try:
            for row in reader:
                line_number = reader.line_num
                if not row or all(not cell.strip() for cell in row):
                    continue

                if header is None:
                    if _looks_like_header(row):
                        header = [_normalized(cell) for cell in row]
                        continue
                    # Headerless CSV: assume timestamp,metric,value,unit[,labels]
                    header = ["timestamp", "metric", "value", "unit", "labels"]

                raw_line = (
                    lines[line_number - 1]
                    if 0 <= line_number - 1 < len(lines)
                    else ",".join(row)
                )

                values = {
                    name: (row[position] if position < len(row) else "")
                    for position, name in enumerate(header)
                    if name
                }
                timestamp_raw = next(
                    (values[name] for name in TIMESTAMP_NAMES if name in values),
                    "",
                )
                metric = next(
                    (values[name] for name in METRIC_NAMES if name in values),
                    "",
                ).strip()
                value_raw = next(
                    (values[name] for name in VALUE_NAMES if name in values),
                    "",
                ).strip()
                unit = next(
                    (values[name] for name in UNIT_NAMES if name in values),
                    "",
                ).strip() or None
                label_raw = next(
                    (values[name] for name in LABEL_NAMES if name in values),
                    "",
                )

                precision_value, numeric_value = parse_decimal(value_raw)
                if not metric or precision_value is None:
                    unparsed(
                        self,
                        records,
                        warnings,
                        filename=filename,
                        index=index,
                        line_number=line_number,
                        line=raw_line,
                        reason="Row is not a valid metric sample (name or value missing).",
                    )
                    index += 1
                    continue

                timestamp = parse_timestamp(timestamp_raw or None)
                if timestamp_raw.strip() and timestamp is None:
                    warnings.append(
                        ParseWarning(
                            code="timestamp_unparsed",
                            message=f"Could not parse timestamp {timestamp_raw!r}.",
                            line=line_number,
                        )
                    )

                labels = _split_labels(label_raw)
                for name, value in values.items():
                    if name and name not in ALL_KNOWN and value.strip():
                        labels[name] = value.strip()

                attributes: dict = {
                    "metric": metric,
                    "value": precision_value,
                    "value_number": numeric_value,
                    "unit": unit,
                    "labels": labels,
                }
                content = f"{metric}={precision_value}"
                if unit:
                    content = f"{content} {unit}"

                records.append(
                    self.record(
                        filename=filename,
                        index=index,
                        content=content,
                        record_type="metric_sample",
                        start_line=line_number,
                        timestamp_start=timestamp,
                        attributes=attributes,
                    )
                )
                index += 1
        except csv.Error as error:
            warnings.append(
                ParseWarning(
                    code="csv_error",
                    message=f"CSV parsing stopped at line {reader.line_num}: {error}",
                    line=reader.line_num,
                )
            )

        if not records and text.strip() and not warnings:
            warnings.append(
                ParseWarning(code="no_records", message="No metric samples were recognised.")
            )
        return self.result(records, warnings)
