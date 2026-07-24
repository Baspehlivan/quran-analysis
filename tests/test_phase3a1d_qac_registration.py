from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from quran_analysis.annotation_sources.registration import EXPECTED_CONFIGURATION_HASH, register_local_qac


class FakeRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []

    def find_by_sha256(self, sha256: str) -> Mapping[str, Any] | None:
        return next((row for row in self.rows if row["raw_sha256"] == sha256), None)

    def create(self, values: Mapping[str, Any]) -> int:
        row = dict(values) | {"id": len(self.rows) + 1}
        self.rows.append(row)
        self.created.append(row)
        return row["id"]


def qac_file(tmp_path: Path) -> Path:
    path = tmp_path / "quranic-corpus-morphology-0.4.txt"
    path.write_bytes(b"LOCATION\tFORM\tTAG\tFEATURES\n(1:1:1:1)\tX\tN\tPOS:N\n")
    return path


def test_successful_metadata_only_registration_does_not_create_records(tmp_path: Path):
    repo = FakeRepository()
    source = qac_file(tmp_path)
    result = register_local_qac(repo, source)

    assert result["status"] == "registered"
    assert result["annotation_source_release_id"] == 1
    row = repo.created[0]
    assert row["stored_raw_path"].startswith("metadata-only://")
    assert not list(tmp_path.glob("annotation_raw/*"))
    assert result["metadata"]["file"]["filename"] == source.name
    assert len(result["metadata"]["file"]["sha256"]) == 64
    assert len(result["metadata"]["file"]["sha512"]) == 128
    assert result["metadata"]["acquisition"]["local_only"] is True
    assert result["metadata"]["parser_configuration"]["canonical_hash"] == EXPECTED_CONFIGURATION_HASH.digest


def test_duplicate_logical_registration_is_idempotent(tmp_path: Path):
    repo = FakeRepository()
    source = qac_file(tmp_path)
    first = register_local_qac(repo, source)
    second = register_local_qac(repo, source)
    assert second["status"] == "already_registered"
    assert second["annotation_source_release_id"] == first["annotation_source_release_id"]
    assert len(repo.created) == 1


def test_existing_sha_with_incompatible_integrity_is_rejected(tmp_path: Path):
    repo = FakeRepository()
    source = qac_file(tmp_path)
    register_local_qac(repo, source)
    repo.rows[0]["metadata_json"] = {"file": {"sha512": "0" * 128}, "source_identity": {"adapter_identifier": "qac-morphology-v0.4"}}
    with pytest.raises(ValueError, match="incompatible"):
        register_local_qac(repo, source)


def test_missing_file_is_rejected(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="not found"):
        register_local_qac(FakeRepository(), tmp_path / "missing.txt")


def test_unsupported_adapter_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported"):
        register_local_qac(FakeRepository(), qac_file(tmp_path), adapter_id="other")


def test_configuration_hash_mismatch_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="configuration hash"):
        register_local_qac(FakeRepository(), qac_file(tmp_path), expected_parser_configuration_hash="0" * 64)


def test_db_registration_creates_no_morphology_rows_when_postgresql_available(tmp_path: Path):
    """Use a unique, rolled-back source so a persistent DB remains repeatable and untouched."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from quran_analysis.annotation_sources.registration import SqlRegistrationRepository
    from quran_analysis.db.session import get_session_local

    marker = uuid4().hex
    source = qac_file(tmp_path)
    source.write_bytes(source.read_bytes() + f"# test-owned isolation {marker}\n".encode())
    try:
        with get_session_local()() as session:
            session.execute(text("select 1 from annotation_source_release limit 1"))
            before = {
                table: session.execute(text(f"select count(*) from {table}")).scalar_one()
                for table in ("annotation_source_record", "morphological_analysis", "morphological_segment", "annotation_alignment")
            }
            result = register_local_qac(
                SqlRegistrationRepository(session), source, source_name=f"QAC registration integration {marker}"
            )
            after = {
                table: session.execute(text(f"select count(*) from {table}")).scalar_one()
                for table in before
            }
            session.rollback()
    except OperationalError:
        pytest.skip("PostgreSQL unavailable for optional registration integration test")

    assert result["status"] == "registered"
    assert after == before


def test_supplied_integrity_fingerprint_mismatch_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="SHA-256"):
        register_local_qac(FakeRepository(), qac_file(tmp_path), expected_sha256="0" * 64)
