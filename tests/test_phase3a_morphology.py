from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from quran_analysis.db.session import get_session_local
from quran_analysis.morphology.core import export_entity, ingest_morphology, inspect_annotation_source, register_annotation_source, unresolved, validate_annotation_source, validate_ingestion, verify_export

FIXTURE = Path("tests/fixtures/annotation_synthetic_qac.tsv")


def session():
    return get_session_local()()


def test_synthetic_fixture_inspect_preserves_records():
    info = inspect_annotation_source(FIXTURE, "synthetic-qac-tsv-v1")
    assert info["byte_identical_reconstruction"] is True
    assert info["counts"]["parsed"] >= 10
    assert info["counts"]["unknown"] >= 1
    assert info["counts"]["malformed"] >= 1


def test_register_validate_ingest_export_and_immutability(tmp_path, monkeypatch):
    with session() as s:
        # The production helpers commit completed immutable provenance rows.  Keep this
        # test's owned rows in the session transaction so close() rolls them back.
        monkeypatch.setattr(s, "commit", s.flush)
        reg = register_annotation_source(s, FIXTURE, name=f"synthetic-test-{uuid4()}", version="v1", fmt="synthetic-qac-tsv-v1", publisher="synthetic", license="synthetic-fixture")
        sid = reg["annotation_source_release_id"]
        assert validate_annotation_source(s, sid)["byte_identical"] is True
        st = ingest_morphology(s, sid, 1, "qac-tanzil-alignment-v1", allow_dirty=True)
        run_id = st["ingestion_run_id"]
        assert validate_ingestion(s, run_id)["ok"] is True
        assert st["malformed"] >= 1 and st["unknown"] >= 1
        assert unresolved(s, sid, "ambiguous")
        assert unresolved(s, sid, "unaligned")
        with pytest.raises(Exception), s.begin_nested():
            s.execute(text("update annotation_source_record set raw_record_content='tamper' where annotation_source_release_id=:sid"), {"sid": sid})
        with pytest.raises(Exception), s.begin_nested():
            s.execute(text("update morphology_ingestion_run set status='failed' where id=:id"), {"id": run_id})
        out = tmp_path / "alignments.json"
        manifest = export_entity(s, run_id, "alignments", "json", out)
        assert manifest["row_count"] == st["alignments"]
        assert verify_export(s, out)["ok"] is True
        out.write_text(out.read_text() + "\n", encoding="utf-8")
        assert verify_export(s, out)["ok"] is False
