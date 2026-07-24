from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from typer.testing import CliRunner

from quran_analysis.cli import app
from quran_analysis.db.session import get_session_local
from quran_analysis.morphology.analytics import MorphologyAnalyticsFilter, MorphologyAnalyticsService
from quran_analysis.research import (
    AggregateQuery,
    AggregationError,
    CooccurrenceQuery,
    CountUnit,
    Metric,
    PairPolicy,
    ResearchBoolean,
    ResearchEngine,
    ResearchPredicate,
    ResearchQuery,
    SetOperation,
    SetQuery,
    load_query,
)

SOURCE_RELEASE = 3
IDENTITIES = {
    CountUnit.MATCH_ROW: "qma.id",
    CountUnit.CANONICAL_TOKEN: "qma.orthographic_token_id",
    CountUnit.CANONICAL_AYAH: "tu.id",
    CountUnit.CANONICAL_SURAH: "tu.surah_id",
    CountUnit.ANNOTATION_RECORD: "rec.id",
    CountUnit.MORPHOLOGICAL_ANALYSIS: "ma.id",
    CountUnit.MORPHOLOGICAL_SEGMENT: "ms.id",
    CountUnit.SOURCE_NATIVE_RECORD: "rec.id",
}
JOIN = """
 from qac_morphology_alignment qma
 join qac_alignment_run ar on ar.id=qma.alignment_run_id
 join morphological_segment ms on ms.id=qma.morphological_segment_id
 join morphological_analysis ma on ma.id=ms.morphological_analysis_id
 join annotation_source_record rec on rec.id=ma.annotation_source_record_id
 left join orthographic_token ot on ot.id=qma.orthographic_token_id
 left join text_unit tu on tu.id=ot.text_unit_id
"""


def session():
    return get_session_local()()


def source_query(*predicates: ResearchPredicate, limit: int = 100) -> ResearchQuery:
    return ResearchQuery(
        ResearchBoolean("and", (ResearchPredicate("source_release", "eq", SOURCE_RELEASE), *predicates)), limit=limit
    )


def root_query(root: str = "ktb") -> ResearchQuery:
    return source_query(ResearchPredicate("root", "eq", root))


def request_payload(request) -> str:
    return json.dumps(request.to_dict(), ensure_ascii=False)


def exact_identity_count(db, unit: CountUnit, extra: str = "") -> int:
    return int(
        db.execute(
            text(
                f"select count(distinct {IDENTITIES[unit]}) {JOIN} "
                "where ar.status='completed' and qma.status <> 'unmatched' "
                "and qma.annotation_source_release_id=:source and "
                f"{IDENTITIES[unit]} is not null {extra}"
            ),
            {"source": SOURCE_RELEASE},
        ).scalar_one()
    )


def test_all_eight_count_units_use_exact_stable_ids_not_display_strings():
    with session() as db:
        engine = ResearchEngine(db)
        for unit in CountUnit:
            result = engine.aggregate(AggregateQuery(source_query(), unit, limit=1))
            assert result.total_groups == 1
            assert result.groups[0]["metric"] == exact_identity_count(db, unit)
            assert result.metadata["dedup_identity"] == IDENTITIES[unit]
            assert result.groups[0]["unit"] == unit.value
        token_count = exact_identity_count(db, CountUnit.CANONICAL_TOKEN)
        display_count = int(
            db.execute(
                text(
                    f"select count(distinct ot.surface_raw) {JOIN} "
                    "where ar.status='completed' and qma.status <> 'unmatched' "
                    "and qma.annotation_source_release_id=:source and ot.surface_raw is not null"
                ),
                {"source": SOURCE_RELEASE},
            ).scalar_one()
        )
    assert token_count > display_count


def test_scalar_grouped_multigroup_order_and_database_pagination_are_exact():
    query = root_query()
    with session() as db:
        engine = ResearchEngine(db)
        scalar = engine.aggregate(AggregateQuery(query, CountUnit.MORPHOLOGICAL_SEGMENT, limit=1))
        assert scalar.groups[0]["metric"] == exact_identity_count(
            db,
            CountUnit.MORPHOLOGICAL_SEGMENT,
            "and coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT')='ktb'",
        )
        request = AggregateQuery(query, CountUnit.MORPHOLOGICAL_SEGMENT, Metric.FREQUENCY, ("surah", "pos"), limit=3)
        first = engine.aggregate(request)
        second = engine.aggregate(
            AggregateQuery(
                query, CountUnit.MORPHOLOGICAL_SEGMENT, Metric.FREQUENCY, ("surah", "pos"), limit=3, offset=3
            )
        )
        ascending = engine.aggregate(
            AggregateQuery(query, CountUnit.MORPHOLOGICAL_SEGMENT, group_by=("surah",), order="asc", limit=3)
        )
    assert first.returned_groups == len(first.groups) == 3
    assert first.total_groups >= first.returned_groups
    assert first.truncated is (first.total_groups > 3)
    assert [group["metric"] for group in first.groups] == sorted(
        (group["metric"] for group in first.groups), reverse=True
    )
    assert [group["metric"] for group in ascending.groups] == sorted(group["metric"] for group in ascending.groups)
    assert {tuple(group["key"].items()) for group in first.groups}.isdisjoint(
        tuple(group["key"].items()) for group in second.groups
    )
    assert first == ResearchEngine(session()).aggregate(request)


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (
            lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, group_by=("unknown",)),
            "unsupported_group_dimension",
        ),
        (
            lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, group_by=("surah", "ayah", "root", "pos")),
            "excessive_group_dimensions",
        ),
        (lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, limit=0), "unbounded_aggregation"),
        (lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, offset=-1), "unbounded_aggregation"),
        (lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, evidence_samples=21), "unbounded_aggregation"),
        (lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, Metric.MIN), "unsupported_metric"),
        (lambda: AggregateQuery(root_query(), CountUnit.MATCH_ROW, order="sideways"), "unsupported_metric"),
        (lambda: AggregateQuery.from_dict({"query": root_query().to_dict()}), "ambiguous_count_semantics"),
        (
            lambda: SetQuery(root_query(), root_query(), CountUnit.MATCH_ROW, SetOperation.UNION),
            "incompatible_identity_unit",
        ),
        (lambda: SetQuery.from_dict({}), "incompatible_identity"),
        (lambda: CooccurrenceQuery(root_query(), root_query(), CountUnit.CANONICAL_AYAH), "incompatible_identity_unit"),
        (
            lambda: CooccurrenceQuery(root_query(), root_query(), CountUnit.CANONICAL_TOKEN, scope="SAME_SURAH"),
            "invalid_cooccurrence_scope",
        ),
        (lambda: CooccurrenceQuery.from_dict({}), "invalid_cooccurrence_scope"),
    ],
)
def test_all_aggregation_input_errors_are_structured(factory, code):
    with pytest.raises(AggregationError) as error:
        factory()
    assert error.value.to_dict()["code"] == code


def test_source_scope_metadata_normalization_and_raw_evidence_are_explicit():
    with session() as db:
        result = ResearchEngine(db).aggregate(
            AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN, group_by=("surah",), evidence_samples=1, limit=1)
        )
    metadata = result.metadata
    scope = metadata["source_scope"]
    assert scope["requested_release_ids"] == [SOURCE_RELEASE]
    assert scope["effective_release_ids"] == [SOURCE_RELEASE]
    assert scope["excluded_release_ids"] == scope["rejected_release_ids"] == []
    assert scope["adapter_ids"] == ["qac-morphology-v0.4"]
    assert {item["source_release_id"] for item in scope["adapters"]} == {SOURCE_RELEASE}
    assert "ROOT" in metadata["required_capabilities"] == scope["required_capabilities"]
    assert metadata["normalization"] == {
        "implicit": False,
        "profile_id": None,
        "profile_version": None,
        "raw_evidence_preserved": True,
    }
    evidence = result.groups[0]["representative_evidence"][0]
    assert evidence["canonical_id"]["unit_identity"] == IDENTITIES[CountUnit.CANONICAL_TOKEN]
    assert evidence["canonical"]["raw_token"] is not None
    assert evidence["annotation"]["raw_record"]
    assert evidence["source_release"]["id"] == SOURCE_RELEASE


def test_explicit_and_incompatible_mixed_source_scopes_are_distinguished():
    mixed = ResearchQuery(
        ResearchBoolean(
            "and",
            (ResearchPredicate("source_release", "in", (1, SOURCE_RELEASE)), ResearchPredicate("root", "eq", "ktb")),
        )
    )
    with session() as db, pytest.raises(AggregationError) as error:
        ResearchEngine(db).aggregate(AggregateQuery(mixed, CountUnit.CANONICAL_TOKEN, limit=1))
    details = error.value.to_dict()
    assert details["code"] == "incompatible_source_scope"
    assert details["requested_release_ids"] == details["rejected_release_ids"] == [1, SOURCE_RELEASE]
    assert details["effective_release_ids"] == details["excluded_release_ids"] == details["adapters"] == []
    assert "ROOT" in details["required_capabilities"]


def test_representative_aggregate_set_and_cooccurrence_evidence_is_bounded_and_deterministic():
    left, right = root_query("ktb"), source_query(ResearchPredicate("pos", "eq", "N"))
    with session() as db:
        engine = ResearchEngine(db)
        aggregate = engine.aggregate(
            AggregateQuery(left, CountUnit.CANONICAL_TOKEN, group_by=("surah",), evidence_samples=1, limit=1)
        )
        operation = SetQuery(
            left, right, CountUnit.CANONICAL_TOKEN, SetOperation.INTERSECTION, limit=5, evidence_samples=2
        )
        first, second = engine.set(operation), engine.set(operation)
        cooccurrence = engine.cooccurrence(
            CooccurrenceQuery(left, right, CountUnit.CANONICAL_TOKEN, limit=5, evidence_samples=2)
        )
    assert len(aggregate.groups[0]["representative_evidence"]) == 1
    assert len(first["representative_evidence"]) <= 2
    assert first == second
    assert first["representative_evidence"] == sorted(
        first["representative_evidence"], key=lambda row: (row["canonical_id"]["id"], row["alignment"]["id"])
    )
    assert len(cooccurrence["representative_evidence"]) <= 2
    assert all(row["source_release"]["id"] == SOURCE_RELEASE for row in first["representative_evidence"])


@pytest.mark.parametrize("operation", list(SetOperation))
def test_all_set_operations_match_stable_id_algebra_and_empty_operands(operation):
    left, right = root_query("ktb"), source_query(ResearchPredicate("pos", "eq", "N"))
    empty = source_query(ResearchPredicate("root", "eq", "definitely-not-a-qac-root"))
    with session() as db:
        engine = ResearchEngine(db)
        result = engine.set(SetQuery(left, right, CountUnit.CANONICAL_TOKEN, operation, limit=100))
        empty_result = engine.set(SetQuery(empty, empty, CountUnit.CANONICAL_TOKEN, operation))
    left_count, right_count, overlap = (
        result["left_cardinality"],
        result["right_cardinality"],
        result["overlap_cardinality"],
    )
    expected = {
        SetOperation.INTERSECTION: overlap,
        SetOperation.UNION: left_count + right_count - overlap,
        SetOperation.DIFFERENCE: left_count - overlap,
        SetOperation.SYMMETRIC_DIFFERENCE: left_count + right_count - 2 * overlap,
    }[operation]
    assert result["result_cardinality"] == expected
    assert result["ids"] == sorted(set(result["ids"]))
    assert empty_result["result_cardinality"] == 0 and empty_result["ids"] == []


def test_same_ayah_both_pair_policies_deduplicate_alignment_rows_before_pairing():
    left, right = root_query("ktb"), source_query(ResearchPredicate("pos", "eq", "N"))
    with session() as db:
        engine = ResearchEngine(db)
        unique = engine.cooccurrence(
            CooccurrenceQuery(
                left, right, CountUnit.CANONICAL_TOKEN, pair_policy=PairPolicy.UNIQUE_TOKEN_PAIRS, limit=10
            )
        )
        all_pairs = engine.cooccurrence(
            CooccurrenceQuery(
                left, right, CountUnit.CANONICAL_TOKEN, pair_policy=PairPolicy.ALL_CROSS_PRODUCT_PAIRS, limit=10
            )
        )
    assert unique["pair_cardinality"] == all_pairs["pair_cardinality"]
    assert unique["pairs"] == all_pairs["pairs"]
    assert len({(item["left_token_id"], item["right_token_id"], item["ayah_id"]) for item in unique["pairs"]}) == len(
        unique["pairs"]
    )
    assert unique["pair_cardinality"] >= len(unique["pairs"])


def test_canonical_json_yaml_request_payload_and_hashes_are_repeatable_and_unit_sensitive():
    aggregate = AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN, Metric.FREQUENCY, ("root",), evidence_samples=0)
    assert AggregateQuery.from_dict(json.loads(json.dumps(aggregate.to_dict()))) == aggregate.canonical()
    assert yaml.safe_load(yaml.safe_dump(aggregate.to_dict(), sort_keys=True)) == aggregate.to_dict()
    changed = AggregateQuery(root_query(), CountUnit.MORPHOLOGICAL_SEGMENT, Metric.FREQUENCY, ("root",))
    assert aggregate.to_dict() != changed.to_dict()
    with session() as db:
        engine = ResearchEngine(db)
        first, second = engine.aggregate(aggregate), engine.aggregate(aggregate)
        changed_result = engine.aggregate(changed)
    assert first.canonical_payload() == second.canonical_payload()
    assert first.reproducibility_hash() == second.reproducibility_hash()
    assert first.metadata["canonical_payload_hash"] == second.metadata["canonical_payload_hash"]
    assert first.metadata["canonical_payload_hash"] != changed_result.metadata["canonical_payload_hash"]


def test_logical_explain_discloses_stages_dedup_and_scope_without_internals():
    with session() as db:
        explain = ResearchEngine(db).explain(
            AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN, group_by=("surah",))
        )
    assert explain["stages"] == [
        "completed_alignment",
        "parameterized_predicate",
        "stable_identity_dedup",
        "database_aggregate",
        "bounded_page",
    ]
    assert explain["dedup_identity"] == IDENTITIES[CountUnit.CANONICAL_TOKEN]
    assert explain["sql_exposed"] is False
    rendered = json.dumps(explain)
    assert (
        "select " not in rendered.lower() and "postgres" not in rendered.lower() and "password" not in rendered.lower()
    )


@pytest.mark.parametrize(
    "command,phase_request",
    [
        ("aggregate", AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN, group_by=("surah",), limit=1)),
        (
            "set",
            SetQuery(
                root_query(),
                source_query(ResearchPredicate("pos", "eq", "N")),
                CountUnit.CANONICAL_TOKEN,
                SetOperation.INTERSECTION,
                limit=1,
            ),
        ),
        (
            "cooccurrence",
            CooccurrenceQuery(
                root_query(), source_query(ResearchPredicate("pos", "eq", "N")), CountUnit.CANONICAL_TOKEN, limit=1
            ),
        ),
        ("explain", AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN, limit=1)),
    ],
)
@pytest.mark.parametrize("format", ["text", "json", "yaml"])
def test_cli_all_operations_all_formats_inline_and_query_file(command, phase_request, format, tmp_path):
    runner = CliRunner()
    inline = runner.invoke(app, ["research", command, "--query", request_payload(phase_request), "--format", format])
    path = tmp_path / f"{command}.yaml"
    path.write_text(yaml.safe_dump(phase_request.to_dict(), sort_keys=True), encoding="utf-8")
    file_result = runner.invoke(app, ["research", command, "--query-file", str(path), "--format", format])
    assert inline.exit_code == file_result.exit_code == 0
    assert inline.output and file_result.output
    if format == "text":
        assert "reproducibility_hash=" in inline.output


def test_cli_errors_write_structured_stderr_and_exit_two():
    result = CliRunner().invoke(app, ["research", "aggregate", "--query", "{}", "--format", "json"])
    assert result.exit_code == 2
    assert '"code"' in result.output


def test_phase4a_source3_root_lemma_tag_equivalence_and_documented_incompatible_metrics():
    filters = MorphologyAnalyticsFilter(source_release_id=SOURCE_RELEASE)
    with session() as db:
        engine, phase4 = ResearchEngine(db), MorphologyAnalyticsService(db)
        for dimension, method in (
            ("root", phase4.root_frequency),
            ("lemma", phase4.lemma_frequency),
            ("pos", phase4.tag_frequency),
        ):
            old = method(filters, limit=10)
            new = engine.aggregate(
                AggregateQuery(source_query(), CountUnit.MORPHOLOGICAL_SEGMENT, group_by=(dimension,), limit=11)
            )
            assert [(row.value, row.segment_count) for row in old.results] == [
                (group["key"][dimension], group["metric"])
                for group in new.groups
                if group["key"][dimension] is not None
            ][: len(old.results)]
    assert Metric.MIN not in {Metric.COUNT, Metric.COUNT_DISTINCT, Metric.FREQUENCY}


def test_phase5a_regression_and_six_bounded_examples_execute():
    phase5 = root_query()
    assert ResearchQuery.loads(phase5.dumps()) == phase5.canonical()
    examples = sorted(Path("examples/research").glob("*.yaml"))[:6]
    assert len(examples) == 6
    with session() as db:
        engine = ResearchEngine(db)
        for path in examples:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            schema = data["schema"]
            if schema == "research-aggregation-v1":
                engine.aggregate(AggregateQuery.from_dict(data))
            elif schema == "research-set-v1":
                engine.set(SetQuery.from_dict(data))
            elif schema == "research-cooccurrence-v1":
                engine.cooccurrence(CooccurrenceQuery.from_dict(data))
            else:
                pytest.fail(f"unexpected research example schema: {schema}")
            assert load_query(phase5.dumps()) == phase5.canonical()


def test_immutable_values_and_count_unit_enums_are_stable():
    assert {unit.value for unit in CountUnit} == {
        "MATCH_ROW",
        "CANONICAL_TOKEN",
        "CANONICAL_AYAH",
        "CANONICAL_SURAH",
        "ANNOTATION_RECORD",
        "MORPHOLOGICAL_ANALYSIS",
        "MORPHOLOGICAL_SEGMENT",
        "SOURCE_NATIVE_RECORD",
    }
    aggregate = AggregateQuery(root_query(), CountUnit.CANONICAL_TOKEN)
    with pytest.raises(FrozenInstanceError):
        aggregate.limit = 2  # type: ignore[misc]
