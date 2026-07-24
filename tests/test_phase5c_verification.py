from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from quran_analysis.cli import app
from quran_analysis.db.session import get_session_local
from quran_analysis.provenance import canonical_hash
from quran_analysis.research import AggregateQuery, CountUnit, ResearchBoolean, ResearchPredicate, ResearchQuery
from quran_analysis.verification import (
    INVARIANT_TABLES,
    VOLATILE_METADATA_FIELDS,
    VerificationError,
    benchmark,
    compatibility_locks,
    database_counts,
    golden_contract,
    release_manifest,
    replay_goldens,
    research_certificate,
    verify_goldens,
)


def test_certified_golden_contract_has_exactly_eleven_canonical_nonvolatile_categories():
    contract = golden_contract()
    assert contract["passed"]
    assert contract["complete"]
    assert len(contract["results"]) == 11
    assert all(row["present"] and row["canonical"] and not row["volatile_fields"] for row in contract["results"])


def test_database_count_invariant_uses_the_certified_ordered_table_vector():
    assert INVARIANT_TABLES == (
        "source_release", "text_unit", "orthographic_token", "annotation_source_release",
        "annotation_source_record", "morphological_analysis", "morphological_segment",
        "qac_alignment_run", "qac_morphology_alignment", "analysis_run", "analysis_evidence",
    )


def test_golden_update_cannot_be_silently_blessed(monkeypatch):
    monkeypatch.delenv("QURAN_ANALYSIS_GOLDEN_UPDATE", raising=False)
    with pytest.raises(VerificationError, match="GOLDEN_CONTRACT_CHANGE"):
        verify_goldens(None, update=True)


def test_compatibility_locks_cover_public_contracts_and_hash_metamorphism():
    locks = compatibility_locks()
    assert locks["failed"] == 0
    assert {row["name"] for row in locks["results"]} == {
        "phase3b_morphology_public_api",
        "phase4a_analytics",
        "phase4b_capability_descriptor",
        "phase4d_catalog_lifecycle_error",
        "phase5_request_serialization_payload_hash",
        "phase5_hash_metamorphism",
        "phase5_structured_errors",
    }
    query = ResearchQuery(ResearchBoolean("and", (ResearchPredicate("source_release", "eq", 3), ResearchPredicate("root", "eq", "ktb"))))
    assert canonical_hash(AggregateQuery(query, CountUnit.CANONICAL_TOKEN, group_by=("surah",)).to_dict()) != canonical_hash(
        AggregateQuery(query, CountUnit.MORPHOLOGICAL_SEGMENT, group_by=("surah",)).to_dict()
    )


def test_read_only_golden_replay_benchmark_manifest_certificate_and_all_tables_are_invariant():
    with get_session_local()() as session:
        before = database_counts(session)
        golden = verify_goldens(session)
        replay = replay_goldens(session)
        workloads = benchmark(session)
        first_manifest, second_manifest = release_manifest(session), release_manifest(session)
        summary = {"passed": golden["passed"] + replay["passed"], "failed": 0, "warnings": 0, "status": "PASS"}
        first_certificate, second_certificate = research_certificate(session, summary), research_certificate(session, summary)
        after = database_counts(session)
    assert golden["failed"] == replay["failed"] == 0
    assert golden["passed"] == replay["passed"] == 11
    assert before == after and len(before) == 11
    assert workloads["persisted"] is False
    assert set(workloads["workload_classes"]) == {"query", "aggregate", "set", "cooccurrence"}
    assert len(workloads["workloads"]) == 11
    assert first_manifest == second_manifest
    assert first_manifest["manifest_hash"] == canonical_hash({key: value for key, value in first_manifest.items() if key != "manifest_hash"})
    assert first_certificate["certificate_hash"] == second_certificate["certificate_hash"]
    assert {key: value for key, value in first_certificate.items() if key != "verified_at_utc"} == {
        key: value for key, value in second_certificate.items() if key != "verified_at_utc"
    }
    assert not (set(first_certificate) & VOLATILE_METADATA_FIELDS)


@pytest.mark.parametrize("command", ["verify", "benchmark", "release-manifest", "research-certificate"])
@pytest.mark.parametrize("format", ["text", "json", "yaml"])
def test_phase5c_cli_commands_render_all_formats(command, format):
    result = CliRunner().invoke(app, [command, "--format", format])
    assert result.exit_code == 0, result.output
    assert result.output
    if format == "json":
        assert json.loads(result.output)


def test_verify_cli_reports_structured_error_for_invalid_format():
    result = CliRunner().invoke(app, ["verify", "--format", "toml"])
    assert result.exit_code == 2
    assert '"code"' in result.output
