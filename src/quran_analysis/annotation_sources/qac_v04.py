"""Lossless streaming parser for a local Quranic Arabic Corpus v0.4 file.

This module only reads and parses bytes.  It does not register a source, write a
DB, align text, or alter the input file.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
import re
from typing import TypeAlias

from quran_analysis.annotation_sources.contracts import (
    FeatureBundle,
    MalformedRecord,
    ParserConfiguration,
    ParserError,
    ParserResult,
    ParserStatus,
    ParsedRecord,
    PhysicalEnding,
    QAC_MORPHOLOGY_V04_IDENTITY,
    RawRecord,
    RecordKind,
    SegmentLocator,
    UnknownRecord,
)

QAC_HEADER = "LOCATION\tFORM\tTAG\tFEATURES"
_LOCATOR = re.compile(r"^\(([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*)\)$")
QACRecord: TypeAlias = ParsedRecord | UnknownRecord | MalformedRecord


def _split_ending(line: bytes) -> tuple[bytes, PhysicalEnding]:
    if line.endswith(b"\r\n"):
        return line[:-2], PhysicalEnding.CRLF
    if line.endswith(b"\n"):
        return line[:-1], PhysicalEnding.LF
    if line.endswith(b"\r"):
        return line[:-1], PhysicalEnding.CR
    return line, PhysicalEnding.NONE


def _classify(text: str) -> tuple[ParserStatus, RecordKind]:
    if text == "":
        return ParserStatus.UNKNOWN, RecordKind.BLANK
    if text == QAC_HEADER:
        return ParserStatus.UNKNOWN, RecordKind.HEADER
    if text.startswith("#"):
        kind = RecordKind.COPYRIGHT if "COPYRIGHT" in text.upper() else RecordKind.COMMENT
        return ParserStatus.UNKNOWN, kind
    # A tabular row or QAC's parenthesised locator is intended morphology.  Errors
    # in either are malformed, not silently treated as an unknown line.
    if "\t" in text or text.startswith("("):
        fields = text.split("\t")
        if len(fields) != 4 or _LOCATOR.fullmatch(fields[0]) is None:
            return ParserStatus.MALFORMED, RecordKind.MORPHOLOGY
        return ParserStatus.PARSED, RecordKind.MORPHOLOGY
    return ParserStatus.UNKNOWN, RecordKind.UNKNOWN


def iter_raw_records(path: str | Path) -> Iterator[RawRecord]:
    """Yield physical UTF-8 lines without universal-newline translation."""
    with Path(path).open("rb") as source:
        for line_number, physical_line in enumerate(source, start=1):
            body, ending = _split_ending(physical_line)
            text = body.decode("utf-8")
            status, kind = _classify(text)
            yield RawRecord(line_number, body, ending, status, text, kind)


def parse_features(raw_text: str) -> FeatureBundle:
    """Split QAC features on literal pipes while preserving every fragment."""
    fragments = tuple(raw_text.split("|"))
    native: dict[str, str] = {}
    for fragment in fragments:
        if ":" in fragment:
            key, value = fragment.split(":", 1)
            native[key] = value
    return FeatureBundle(native, raw_text, fragments, "|")


def _parse_record(raw_record: RawRecord) -> QACRecord:
    if raw_record.parser_status is ParserStatus.UNKNOWN:
        return UnknownRecord(raw_record, raw_record.record_kind.value)
    if raw_record.parser_status is ParserStatus.MALFORMED:
        field_count = raw_record.decoded_text.count("\t") + 1
        message = "morphology row must contain exactly four tab-separated fields"
        if field_count == 4:
            message = "morphology row has an invalid locator"
        return MalformedRecord(raw_record, ParserError(raw_record.line_number, message))

    location, form, tag, features = raw_record.decoded_text.split("\t")
    match = _LOCATOR.fullmatch(location)
    if match is None:  # Defensive: statuses are assigned by iter_raw_records.
        raise ValueError("parsed QAC record has an invalid locator")
    locator = SegmentLocator(*(int(part) for part in match.groups()))
    return ParsedRecord(
        raw_record,
        locator,
        parse_features(features),
        {"LOCATION": location, "FORM": form, "TAG": tag, "FEATURES": features},
    )


class QACV04Parser:
    """Streaming, pure parser for the local QAC morphology v0.4 format."""

    identity = QAC_MORPHOLOGY_V04_IDENTITY

    def iter_raw_records(self, path: str | Path) -> Iterator[RawRecord]:
        return iter_raw_records(path)

    def iter_records(self, path: str | Path) -> Iterator[QACRecord]:
        for raw_record in self.iter_raw_records(path):
            yield _parse_record(raw_record)

    def parse_file(self, path: str | Path) -> ParserResult:
        return self.parse(tuple(self.iter_raw_records(path)), ParserConfiguration("qac-morphology-v0.4", "0.4"))

    def parse(self, raw_records: Sequence[RawRecord], configuration: ParserConfiguration) -> ParserResult:
        del configuration
        records = tuple(raw_records)
        parsed: list[ParsedRecord] = []
        unknown: list[UnknownRecord] = []
        malformed: list[MalformedRecord] = []
        for raw_record in records:
            result = _parse_record(raw_record)
            if isinstance(result, ParsedRecord):
                parsed.append(result)
            elif isinstance(result, UnknownRecord):
                unknown.append(result)
            else:
                malformed.append(result)
        return ParserResult(records, tuple(parsed), tuple(unknown), tuple(malformed))


__all__ = [
    "QAC_HEADER",
    "QACRecord",
    "QACV04Parser",
    "iter_raw_records",
    "parse_features",
]
