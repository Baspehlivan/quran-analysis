from datetime import date
from pathlib import Path
import subprocess

import pytest

from quran_analysis.annotation_sources.contracts import (
    FeatureBundle,
    MalformedRecord,
    ParserConfiguration,
    ParserConfigurationHash,
    ParserError,
    ParserResult,
    ParserStatus,
    PhysicalEnding,
    QAC_MORPHOLOGY_V04_IDENTITY,
    RawRecord,
    SegmentLocator,
    SourceAcquisition,
    SourceClass,
    SourceFingerprint,
    SourceIdentity,
    SourceIntegrity,
    SourceMetadata,
    reconstruct_physical_bytes,
)


def test_local_qac_path_is_ignored_without_writing_source():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/incoming/quranic-corpus-morphology-0.4.txt"], check=False
    )
    assert result.returncode == 0
    assert Path("tests/fixtures/annotation_synthetic_qac.tsv").is_file()


def test_qac_adapter_identity_is_distinct_from_synthetic_fixture():
    synthetic = SourceIdentity("fixture", SourceClass.SYNTHETIC_FIXTURE, "synthetic-qac-tsv-v1", "v1")
    assert QAC_MORPHOLOGY_V04_IDENTITY.source_class is SourceClass.USER_LOCAL_DATASET
    assert QAC_MORPHOLOGY_V04_IDENTITY.adapter_identifier != synthetic.adapter_identifier


def test_metadata_uses_canonical_serialization_and_hashing():
    fingerprint = SourceFingerprint("a" * 64, "b" * 128, 12, "LF", "utf-8")
    metadata = SourceMetadata(
        SourceIdentity("qac", SourceClass.USER_LOCAL_DATASET, "qac-morphology-v0.4", "0.4"),
        SourceAcquisition(date(2025, 1, 1), "local.txt", "download.txt"),
        SourceIntegrity("local license", "local citation", fingerprint),
        ParserConfiguration("qac-morphology-v0.4", "0.4", {"strict": True}),
    )
    assert metadata.canonical_json() == metadata.canonical_json()
    assert metadata.canonical_hash() == metadata.canonical_hash()
    assert ParserConfigurationHash.from_configuration(metadata.parser_configuration).digest == ParserConfigurationHash.from_configuration(metadata.parser_configuration).digest


def test_raw_records_reconstruct_exact_physical_bytes_and_enforce_invariants():
    records = (
        RawRecord(1, b"one", PhysicalEnding.CRLF, ParserStatus.PARSED),
        RawRecord(2, b"two", PhysicalEnding.NONE, ParserStatus.UNKNOWN),
    )
    assert reconstruct_physical_bytes(records) == b"one\r\ntwo"
    with pytest.raises(ValueError, match="exclude"):
        RawRecord(1, b"bad\n", PhysicalEnding.NONE, ParserStatus.PARSED)
    with pytest.raises(ValueError, match="consecutive"):
        ParserResult((records[1],))


def test_parser_contract_status_and_configuration_invariants():
    raw = RawRecord(1, b"bad", PhysicalEnding.LF, ParserStatus.MALFORMED)
    malformed = MalformedRecord(raw, ParserError(1, "invalid record"))
    assert ParserResult((raw,), malformed_records=(malformed,)).malformed_records == (malformed,)
    with pytest.raises(ValueError, match="positive"):
        SegmentLocator(0, 1, 1)
    with pytest.raises(TypeError, match="strings"):
        FeatureBundle({"POS": 1})  # type: ignore[dict-item]
