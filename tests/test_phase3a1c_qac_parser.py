from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from quran_analysis.annotation_sources.contracts import (
    ParserStatus,
    PhysicalEnding,
    RecordKind,
    reconstruct_physical_bytes,
)
from quran_analysis.annotation_sources.qac_v04 import QACV04Parser, iter_raw_records, parse_features


LOCAL_QAC = Path("data/incoming/quranic-corpus-morphology-0.4.txt")


def test_lossless_stream_classifies_structural_and_invalid_records(tmp_path: Path):
    source = tmp_path / "synthetic.tsv"
    source.write_bytes(
        b"# copyright synthetic\r\n"
        b"# comment\r\n"
        b"\r\n"
        b"LOCATION\tFORM\tTAG\tFEATURES\r\n"
        b"(1:2:3:4)\tform\tTAG\tPOS:N|POS:V|FUTURE\r\n"
        b"(0:2:3:4)\tform\tTAG\tPOS:N\r\n"
        b"(1:2:3:4)\ttoo-few\tTAG\r\n"
        b"@structural-extension\r\n"
    )

    parser = QACV04Parser()
    records = list(parser.iter_raw_records(source))
    assert [record.record_kind for record in records] == [
        RecordKind.COPYRIGHT,
        RecordKind.COMMENT,
        RecordKind.BLANK,
        RecordKind.HEADER,
        RecordKind.MORPHOLOGY,
        RecordKind.MORPHOLOGY,
        RecordKind.MORPHOLOGY,
        RecordKind.UNKNOWN,
    ]
    assert [record.parser_status for record in records] == [
        ParserStatus.UNKNOWN,
        ParserStatus.UNKNOWN,
        ParserStatus.UNKNOWN,
        ParserStatus.UNKNOWN,
        ParserStatus.PARSED,
        ParserStatus.MALFORMED,
        ParserStatus.MALFORMED,
        ParserStatus.UNKNOWN,
    ]
    assert all(record.physical_ending is PhysicalEnding.CRLF for record in records)
    assert reconstruct_physical_bytes(records) == source.read_bytes()

    result = parser.parse_file(source)
    assert len(result.parsed_records) == 1
    assert len(result.malformed_records) == 2
    assert len(result.unknown_records) == 5
    parsed = result.parsed_records[0]
    assert parsed.payload == {
        "LOCATION": "(1:2:3:4)",
        "FORM": "form",
        "TAG": "TAG",
        "FEATURES": "POS:N|POS:V|FUTURE",
    }
    assert parsed.locator.surah == 1
    assert parsed.features.raw_text == "POS:N|POS:V|FUTURE"
    assert parsed.features.fragments == ("POS:N", "POS:V", "FUTURE")
    assert parsed.features.native["POS"] == "V"


def test_feature_parser_preserves_duplicates_unknown_and_separator():
    features = parse_features("POS:N|POS:V|UNKNOWN|X:one:two")
    assert features.raw_text == "POS:N|POS:V|UNKNOWN|X:one:two"
    assert features.fragments == ("POS:N", "POS:V", "UNKNOWN", "X:one:two")
    assert features.separator == "|"
    assert features.native == {"POS": "V", "X": "one:two"}


def test_iter_raw_records_is_lazy_and_preserves_nonfinal_line_ending(tmp_path: Path):
    source = tmp_path / "one-line.tsv"
    source.write_bytes(b"@unknown")
    stream = iter_raw_records(source)
    assert hasattr(stream, "__next__")
    record = next(stream)
    assert record.physical_ending is PhysicalEnding.NONE
    assert record.decoded_text == "@unknown"
    with pytest.raises(StopIteration):
        next(stream)


@pytest.mark.skipif(not LOCAL_QAC.is_file(), reason="local ignored QAC v0.4 source is absent")
def test_local_qac_stream_reconstructs_exact_bytes_and_sha256():
    parser = QACV04Parser()
    raw_records = tuple(parser.iter_raw_records(LOCAL_QAC))
    original = LOCAL_QAC.read_bytes()
    rebuilt = reconstruct_physical_bytes(raw_records)
    assert rebuilt == original
    assert hashlib.sha256(rebuilt).hexdigest() == hashlib.sha256(original).hexdigest()
    assert len(raw_records) > 100_000
    assert raw_records[56].record_kind is RecordKind.HEADER
    assert raw_records[56].decoded_text == "LOCATION\tFORM\tTAG\tFEATURES"
    result = parser.parse_file(LOCAL_QAC)
    assert len(result.raw_records) == len(raw_records)
    assert result.parsed_records
