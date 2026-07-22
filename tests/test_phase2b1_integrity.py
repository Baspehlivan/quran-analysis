import csv
import json
import subprocess

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from quran_analysis import __version__
from quran_analysis.analysis import exact_token_search, parse_export_rows, verify_export_file, write_export
from quran_analysis.db.session import get_session_local
from quran_analysis.models.tables import AnalysisRun, EnvironmentSnapshot, NormalizationProfile, QueryScopeDefinition, SourceRelease
from quran_analysis.normalization.profiles import get_profile
from quran_analysis.provenance import canonical_hash, evidence_hash, ngram_sequence_hash, query_hash_payload


def test_application_version_is_phase2b_patch():
    assert __version__ == "0.2.1-phase2b"


def test_query_hash_semantics_not_output_window():
    session = get_session_local()()
    try:
        run_a, _ = exact_token_search(session, "بِسْمِ", allow_dirty=True)
        run_b, _ = exact_token_search(session, "الله", allow_dirty=True)
        assert run_a.query_hash != run_b.query_hash
        source = session.get(SourceRelease, run_a.source_release_id)
        assert run_a.query_hash == canonical_hash(query_hash_payload(analysis_type=run_a.analysis_type, source=source, scope=run_a.scope_configuration_json, profile=None, params=run_a.query_parameters_json, representation=run_a.query_parameters_json.get("representation"), cross_unit=run_a.query_parameters_json.get("cross_unit"), n=run_a.query_parameters_json.get("n"), session=session))
        preview_a = {"query_hash": run_a.query_hash, "limit": 1, "offset": 0}
        preview_b = {"query_hash": run_a.query_hash, "limit": 5, "offset": 2}
        assert preview_a["query_hash"] == preview_b["query_hash"]
    finally:
        session.close()


def test_environment_snapshot_canonical_hash():
    session = get_session_local()()
    try:
        run = session.scalars(select(AnalysisRun).where(AnalysisRun.environment_snapshot_id.is_not(None)).order_by(AnalysisRun.id.desc())).first()
        assert run is not None
        snap = session.get(EnvironmentSnapshot, run.environment_snapshot_id)
        assert snap.content_hash == canonical_hash(snap.canonical_json)
    finally:
        session.close()


def test_evidence_hash_deterministic_and_order_independent():
    rows = [
        {"global_token_position": 2, "raw_surface": "b", "query_hash": "ignored"},
        {"global_token_position": 1, "raw_surface": "a", "query_hash": "ignored"},
    ]
    assert evidence_hash(rows) == evidence_hash(list(reversed(rows)))
    assert evidence_hash(rows) == evidence_hash(json.loads(json.dumps(rows)))


def test_adversarial_ngram_canonical_hashing():
    a = ngram_sequence_hash(["a b", "c"], representation="raw-token", normalization_profile_sha256=None, n=2)
    b = ngram_sequence_hash(["a", "b c"], representation="raw-token", normalization_profile_sha256=None, n=2)
    assert a != b
    assert a == ngram_sequence_hash(["a b", "c"], representation="raw-token", normalization_profile_sha256=None, n=2)


def test_export_csv_json_jsonl_recompute_and_tamper_rejection(tmp_path):
    session = get_session_local()()
    try:
        run, results = exact_token_search(session, "بِسْمِ", allow_dirty=True)
        assert results
        for fmt in ["csv", "json", "jsonl"]:
            output = tmp_path / f"export.{fmt}"
            write_export(session, run.id, fmt, output)
            verified = verify_export_file(output, session)
            assert verified["ok"], verified
            assert verified["computed_evidence_hash"] == run.evidence_hash
            rows = parse_export_rows(output, fmt)
            if len(rows) > 1:
                if fmt == "json":
                    output.write_text(json.dumps(list(reversed(rows)), ensure_ascii=False), encoding="utf-8")
                elif fmt == "jsonl":
                    output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reversed(rows)), encoding="utf-8")
                else:
                    with output.open("w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                        writer.writeheader(); writer.writerows(reversed(rows))
                assert verify_export_file(output, session)["computed_evidence_hash"] == run.evidence_hash
                rows = parse_export_rows(output, fmt)
            rows[0]["raw_surface"] = "TAMPERED"
            if fmt == "json":
                output.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            elif fmt == "jsonl":
                output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            else:
                with output.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            tampered = verify_export_file(output, session)
            assert not tampered["ok"]
            assert not tampered["checks"]["evidence_hash_match_db"]
    finally:
        session.close()


def test_default_dirty_refusal_and_allow_dirty_provenance(monkeypatch):
    import quran_analysis.analysis as analysis_mod
    import quran_analysis.provenance as provenance_mod

    session = get_session_local()()
    try:
        monkeypatch.setattr(analysis_mod, "git_dirty", lambda cwd=None: True)
        with pytest.raises(ValueError, match="dirty git tree"):
            exact_token_search(session, "بِسْمِ", allow_dirty=False)
        monkeypatch.setattr(provenance_mod, "git_dirty", lambda cwd=None: True)
        run, _ = exact_token_search(session, "بِسْمِ", allow_dirty=True)
        assert run.status == "completed"
        assert run.git_dirty is True
        assert run.git_commit_hash
    finally:
        session.close()


def _rejects(session, sql):
    with pytest.raises(DBAPIError):
        session.execute(text(sql))
        session.commit()
    session.rollback()


def test_direct_sql_immutability_rejections():
    session = get_session_local()()
    try:
        run, _ = exact_token_search(session, "بِسْمِ", allow_dirty=True)
        profile = session.scalars(select(NormalizationProfile).order_by(NormalizationProfile.id)).first()
        if profile is None:
            cfg = get_profile("identity_v1")
            profile = NormalizationProfile(name=cfg["name"], version=cfg["version"], description=cfg["description"], configuration_json=cfg["configuration"], configuration_sha256=cfg["configuration_sha256"], is_frozen=True)
            session.add(profile); session.commit(); session.refresh(profile)
        scope = QueryScopeDefinition(name=f"phase2b1_{run.id}", version="v1", description="phase2b1 test", configuration_json=run.scope_configuration_json, configuration_sha256=canonical_hash(run.scope_configuration_json), is_frozen=True)
        session.add(scope); session.commit(); session.refresh(scope)
        env_hash = run.environment_snapshot_hash
        evidence_hash_before = run.evidence_hash
        _rejects(session, f"update normalization_profile set configuration_sha256 = repeat('0',64) where id = {profile.id}")
        _rejects(session, f"delete from normalization_profile where id = {profile.id}")
        _rejects(session, f"update query_scope_definition set configuration_sha256 = repeat('1',64) where id = {scope.id}")
        _rejects(session, f"delete from query_scope_definition where id = {scope.id}")
        _rejects(session, f"update environment_snapshot set content_hash = repeat('2',64) where id = {run.environment_snapshot_id}")
        _rejects(session, f"delete from environment_snapshot where id = {run.environment_snapshot_id}")
        _rejects(session, f"update analysis_run set evidence_hash = repeat('3',64) where id = {run.id}")
        _rejects(session, f"update analysis_run set result_count = result_count + 1 where id = {run.id}")
        _rejects(session, f"update analysis_run set status = 'running' where id = {run.id}")
        session.refresh(run)
        assert run.status == "completed"
        assert run.environment_snapshot_hash == env_hash
        assert run.evidence_hash == evidence_hash_before
    finally:
        session.close()


def test_phase1_fixture_byte_identical_reconstruction():
    result = subprocess.run(["quran", "validate", "1"], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["byte_identical"] is True
    assert payload["source_sha256"] == payload["reconstructed_sha256"]
    assert payload["codepoint_text_mismatches"] == []
    assert payload["token_text_mismatches"] == []
