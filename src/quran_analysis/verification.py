"""Read-only Phase 5C verification and release-certification primitives."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import text

from quran_analysis import __version__
from quran_analysis.annotation_sources.capabilities import production_annotation_adapter_registry
from quran_analysis.annotation_sources.catalog import SourceLifecycleError, get_catalog_source, guard_source_ingestion
from quran_analysis.annotation_sources.service import resolve_query_scope
from quran_analysis.morphology.analytics import MorphologyAnalyticsFilter
from quran_analysis.morphology.query import MorphologyQuery
from quran_analysis.provenance import alembic_revision, canonical_hash, canonical_json, git_commit_hash, git_dirty
from quran_analysis.research import (
    AggregateQuery, AggregationError, CooccurrenceQuery, CountUnit, Metric, ResearchBoolean,
    ResearchEngine, ResearchPredicate, ResearchQuery, ResearchQueryError, SetOperation, SetQuery,
)

GOLDEN_VERSION = "phase5c-golden-v1"
RELEASE_MANIFEST_VERSION = "research-release-manifest-v1"
CERTIFICATE_VERSION = "research-certificate-v1"
INVARIANT_TABLES = (
    "source_release", "text_unit", "orthographic_token", "annotation_source_release",
    "annotation_source_record", "morphological_analysis", "morphological_segment",
    "qac_alignment_run", "qac_morphology_alignment", "analysis_run", "analysis_evidence",
)
GOLDEN_CATEGORIES = (
    "canonical-token", "root", "lemma", "pos", "feature", "grouped-frequency", "distinct-count",
    "set-intersection", "same-ayah-cooccurrence", "normalization-profile", "aggregate-report",
)
VOLATILE_METADATA_FIELDS = frozenset({"executed_at_utc", "duration_ms", "git_revision", "git_dirty"})
ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "tests" / "golden"


class VerificationError(ValueError):
    code = "verification_error"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def render(value: Mapping[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if output_format == "yaml":
        import yaml
        return yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=True)
    if output_format != "text":
        raise VerificationError("format must be text, json, or yaml")
    return "\n".join(f"{key}={json.dumps(item, ensure_ascii=False, default=str) if isinstance(item, (dict, list)) else item}" for key, item in value.items())


def database_counts(session: Any) -> dict[str, int]:
    return {name: int(session.execute(text(f"select count(*) from {name}")).scalar_one()) for name in INVARIANT_TABLES}


def _request(value: Mapping[str, Any]) -> Any:
    schema = value["schema"]
    if schema == "research-query-v1": return ResearchQuery.from_dict(value)
    if schema == "research-aggregation-v1": return AggregateQuery.from_dict(value)
    if schema == "research-set-v1": return SetQuery.from_dict(value)
    if schema == "research-cooccurrence-v1": return CooccurrenceQuery.from_dict(value)
    raise VerificationError(f"unsupported golden schema: {schema}")


def _execute(engine: ResearchEngine, request: Any) -> dict[str, Any]:
    if isinstance(request, ResearchQuery): return engine.execute(request).to_dict()
    if isinstance(request, AggregateQuery): return engine.aggregate(request).to_dict()  # type: ignore[attr-defined]
    if isinstance(request, SetQuery): return engine.set(request)  # type: ignore[attr-defined]
    return engine.cooccurrence(request)  # type: ignore[attr-defined]


def stable_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the certified representation; execution observations never enter goldens."""
    copy = json.loads(canonical_json(value))
    if isinstance(copy.get("metadata"), dict):
        for field in VOLATILE_METADATA_FIELDS:
            copy["metadata"].pop(field, None)
    return copy


def golden_specs() -> list[dict[str, Any]]:
    document = json.loads((GOLDEN_DIR / "specs.json").read_text(encoding="utf-8"))
    if document.get("golden_version") != GOLDEN_VERSION:
        raise VerificationError("golden specification version is not certified")
    return document["specs"]


def golden_snapshot_path(name: str) -> Path:
    return GOLDEN_DIR / "snapshots" / f"{name}.json"


def golden_contract() -> dict[str, Any]:
    specs = golden_specs()
    names = tuple(spec.get("name") for spec in specs)
    results = []
    for spec in specs:
        path = golden_snapshot_path(spec["name"])
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            canonical = canonical_json(snapshot) + "\n" == path.read_text(encoding="utf-8")
            volatile = sorted(set(snapshot.get("metadata", {})) & VOLATILE_METADATA_FIELDS)
            results.append({"name": spec["name"], "present": True, "canonical": canonical, "volatile_fields": volatile,
                            "passed": canonical and not volatile})
        except (OSError, json.JSONDecodeError):
            results.append({"name": spec["name"], "present": False, "canonical": False, "volatile_fields": [], "passed": False})
    complete = names == GOLDEN_CATEGORIES and len(set(names)) == len(GOLDEN_CATEGORIES)
    return {"expected_categories": list(GOLDEN_CATEGORIES), "complete": complete, "passed": complete and all(row["passed"] for row in results), "results": results}


def verify_goldens(session: Any, *, update: bool = False) -> dict[str, Any]:
    if update and os.environ.get("QURAN_ANALYSIS_GOLDEN_UPDATE") != "I_UNDERSTAND_GOLDEN_CONTRACT_CHANGE":
        raise VerificationError("golden updates require QURAN_ANALYSIS_GOLDEN_UPDATE=I_UNDERSTAND_GOLDEN_CONTRACT_CHANGE")
    engine, results = ResearchEngine(session), []
    for spec in golden_specs():
        generated = stable_snapshot(_execute(engine, _request(spec["request"])))
        path = golden_snapshot_path(spec["name"])
        if update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical_json(generated) + "\n", encoding="utf-8")
        expected = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        results.append({"name": spec["name"], "snapshot_hash": canonical_hash(generated), "matched": expected == generated})
    return {"golden_version": GOLDEN_VERSION, "passed": sum(x["matched"] for x in results), "failed": sum(not x["matched"] for x in results), "results": results}


def replay_goldens(session: Any) -> dict[str, Any]:
    engine, rows = ResearchEngine(session), []
    for spec in golden_specs():
        request = _request(spec["request"])
        first, second = stable_snapshot(_execute(engine, request)), stable_snapshot(_execute(engine, request))
        rows.append({"name": spec["name"], "identical": first == second, "hash": canonical_hash(first)})
    return {"passed": sum(row["identical"] for row in rows), "failed": sum(not row["identical"] for row in rows), "results": rows}


def _lock(name: str, check: Callable[[], None]) -> dict[str, Any]:
    try:
        check()
    except Exception as exc:
        return {"name": name, "passed": False, "error": {"code": getattr(exc, "code", "compatibility_lock_failed"), "message": str(exc)}}
    return {"name": name, "passed": True}


def compatibility_locks() -> dict[str, Any]:
    """Independent public-contract locks; they do not execute or persist research data."""
    query = ResearchQuery(ResearchBoolean("and", (
        ResearchPredicate("source_release", "eq", 3), ResearchPredicate("root", "eq", "ktb"),
    )))
    aggregate = AggregateQuery(query, CountUnit.CANONICAL_TOKEN, Metric.COUNT, ("surah",), evidence_samples=1)
    operation = SetQuery(query, query, CountUnit.CANONICAL_TOKEN, SetOperation.INTERSECTION, evidence_samples=1)
    cooccurrence = CooccurrenceQuery(query, query, CountUnit.CANONICAL_TOKEN, evidence_samples=1)

    def serialization() -> None:
        for item, factory in ((query, ResearchQuery.from_dict), (aggregate, AggregateQuery.from_dict),
                              (operation, SetQuery.from_dict), (cooccurrence, CooccurrenceQuery.from_dict)):
            rebuilt = factory(json.loads(canonical_json(item.to_dict())))
            if rebuilt.to_dict() != item.to_dict() or canonical_hash(item.to_dict()) != canonical_hash(rebuilt.to_dict()):
                raise VerificationError("canonical request serialization changed")

    def metamorphism() -> None:
        variants = (
            ResearchQuery(ResearchBoolean("and", (ResearchPredicate("source_release", "eq", 4), ResearchPredicate("root", "eq", "ktb")))),
            ResearchQuery(ResearchBoolean("and", (ResearchPredicate("source_release", "eq", 3), ResearchPredicate("normalization_profile", "eq", "none")))),
            AggregateQuery(query, CountUnit.MORPHOLOGICAL_SEGMENT),
            ResearchQuery(ResearchBoolean("and", (ResearchPredicate("source_release", "eq", 3), ResearchPredicate("lemma", "eq", "kitAb")))),
            AggregateQuery(query, CountUnit.CANONICAL_TOKEN, group_by=("pos",)),
            AggregateQuery(query, CountUnit.CANONICAL_TOKEN, evidence_samples=2),
        )
        hashes = {canonical_hash(item.to_dict()) for item in (query, aggregate, *variants)}
        if len(hashes) != 8:
            raise VerificationError("source release, normalization, count unit, predicate, group, or evidence policy is missing from canonical hash")

    def structured_errors() -> None:
        cases = (
            (lambda: ResearchQuery.from_dict({}), "invalid_research_query"),
            (lambda: AggregateQuery.from_dict({}), "ambiguous_count_semantics"),
            (lambda: SetQuery.from_dict({}), "incompatible_identity"),
            (lambda: CooccurrenceQuery.from_dict({}), "invalid_cooccurrence_scope"),
        )
        for action, code in cases:
            try: action()
            except (ResearchQueryError, AggregationError) as exc:
                if exc.to_dict()["code"] != code: raise VerificationError("structured error code changed")
            else: raise VerificationError("invalid public request was accepted")

    def phase3b() -> None:
        if MorphologyQuery(root="ktb").root != "ktb": raise VerificationError("Phase3B morphology public query changed")

    def phase4a() -> None:
        if MorphologyAnalyticsFilter(root="ktb").root != "ktb": raise VerificationError("Phase4A analytics filter changed")

    def phase4b() -> None:
        descriptor = production_annotation_adapter_registry().list()[0].descriptor(3).to_dict()
        if descriptor["adapter_id"] != "qac-morphology-v0.4" or "ROOT" not in descriptor["capabilities"]:
            raise VerificationError("Phase4B capability descriptor changed")

    def phase4d() -> None:
        try: guard_source_ingestion(get_catalog_source("quranmorph"))
        except SourceLifecycleError as exc:
            if exc.to_dict()["code"] != "source_lifecycle_blocked": raise
        else: raise VerificationError("Phase4D lifecycle guard changed")

    locks = [_lock("phase3b_morphology_public_api", phase3b), _lock("phase4a_analytics", phase4a),
             _lock("phase4b_capability_descriptor", phase4b), _lock("phase4d_catalog_lifecycle_error", phase4d),
             _lock("phase5_request_serialization_payload_hash", serialization), _lock("phase5_hash_metamorphism", metamorphism),
             _lock("phase5_structured_errors", structured_errors)]
    return {"passed": sum(item["passed"] for item in locks), "failed": sum(not item["passed"] for item in locks), "results": locks}


def benchmark(session: Any) -> dict[str, Any]:
    engine, workloads = ResearchEngine(session), []
    for spec in golden_specs():
        start = time.perf_counter(); result = _execute(engine, _request(spec["request"])); elapsed = round((time.perf_counter() - start) * 1000, 3)
        summary = result.get("summary", {})
        workloads.append({"identity": spec["name"], "schema": spec["request"]["schema"], "execution_ms": elapsed, "returned_rows": summary.get("returned_rows", result.get("returned_groups", len(result.get("ids", result.get("pairs", []))))), "cardinality": summary.get("total_matching_rows", result.get("result_cardinality", result.get("pair_cardinality", result.get("total_groups")))), "database_rows_scanned": None})
    return {"workload_version": GOLDEN_VERSION, "persisted": False, "workload_classes": ["query", "aggregate", "set", "cooccurrence"], "workloads": workloads}


def release_manifest(session: Any) -> dict[str, Any]:
    releases = [dict(row) for row in session.execute(text("select id,name,version,raw_sha256,format,parser_name from annotation_source_release order by id")).mappings()]
    descriptors = [item.to_dict() for item in resolve_query_scope(session, type("Scope", (), {"source_release_id": None})())]
    payload = {"schema": RELEASE_MANIFEST_VERSION, "repository": {"revision": git_commit_hash(ROOT), "dirty": git_dirty(ROOT)}, "alembic_revision": alembic_revision(session), "source_releases": releases, "adapters": descriptors, "normalization_profiles": [dict(row) for row in session.execute(text("select name,version,configuration_sha256 from normalization_profile order by name,version")).mappings()], "capability_matrix": [{"source_release_id": row["source_release_id"], "adapter_id": row["adapter_id"], "capabilities": row["capabilities"]} for row in descriptors], "golden_version": GOLDEN_VERSION, "research_engine_version": __version__}
    return payload | {"manifest_hash": canonical_hash(payload)}


def research_certificate(session: Any, verification: Mapping[str, Any] | None = None) -> dict[str, Any]:
    verification = verification or {"passed": 0, "failed": 0, "warnings": 1, "status": "NOT_RUN"}
    payload = {"schema": CERTIFICATE_VERSION, "repository": {"revision": git_commit_hash(ROOT), "dirty": git_dirty(ROOT)}, "verified_releases": release_manifest(session)["source_releases"], "golden_version": GOLDEN_VERSION, "summary": dict(verification)}
    return payload | {"certificate_hash": canonical_hash(payload), "verified_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
