"""Read-only reproducible research queries over canonical text and aligned morphology."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from sqlalchemy import text

from quran_analysis.annotation_sources.capabilities import AnnotationCapability, UnsupportedDimensionError
from quran_analysis.annotation_sources.service import resolve_query_scope
from quran_analysis.morphology.query import MAX_LIMIT, morphology_filter_predicates
from quran_analysis.provenance import alembic_revision, canonical_hash, canonical_json, environment

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is declared by this project
    yaml = None

RESEARCH_SCHEMA_VERSION = "research-query-v1"
DEFAULT_LIMIT = 50

_DIMENSIONS = {
    "canonical_text": {"eq", "contains", "prefix"},
    "token": {"eq", "contains", "prefix"},
    "segment": {"eq", "in"},
    "root": {"eq", "in"},
    "lemma": {"eq", "in"},
    "pos": {"eq", "in"},
    "feature": {"eq", "in"},
    "surah": {"eq", "in"},
    "ayah": {"eq", "in"},
    "source_release": {"eq", "in"},
    "alignment_method": {"eq", "in"},
    "parser_status": {"eq", "in"},
    "normalization_profile": {"eq", "in"},
}


class ResearchQueryError(ValueError):
    code = "invalid_research_query"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class ResearchPredicate:
    dimension: str
    operator: str
    value: str | int | tuple[str | int, ...]

    def __post_init__(self) -> None:
        if self.dimension in {"juz", "hizb", "page"}:
            raise UnsupportedDimensionError(
                f"dimension {self.dimension} is not available in verified data", dimension=self.dimension
            )
        if self.dimension not in _DIMENSIONS:
            raise UnsupportedDimensionError(
                f"unsupported research dimension: {self.dimension}", dimension=self.dimension
            )
        if self.operator not in _DIMENSIONS[self.dimension]:
            raise ResearchQueryError(f"operator {self.operator} is not valid for {self.dimension}")
        if self.operator == "in":
            if not isinstance(self.value, tuple) or not self.value:
                raise ResearchQueryError("in requires a non-empty list value")
        elif isinstance(self.value, tuple):
            raise ResearchQueryError(f"{self.operator} requires a scalar value")
        if self.dimension in {"segment", "surah", "ayah", "source_release"}:
            values = self.value if isinstance(self.value, tuple) else (self.value,)
            if any(not isinstance(value, int) or value < 1 for value in values):
                raise ResearchQueryError(f"{self.dimension} values must be positive integers")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "operator": self.operator,
            "value": list(self.value) if isinstance(self.value, tuple) else self.value,
        }


@dataclass(frozen=True)
class ResearchBoolean:
    operator: str
    children: tuple["ResearchExpression", ...]

    def __post_init__(self) -> None:
        if self.operator not in {"and", "or", "not"}:
            raise ResearchQueryError("boolean operator must be and, or, or not")
        if not self.children or (self.operator == "not" and len(self.children) != 1):
            raise ResearchQueryError(f"{self.operator} has invalid child count")

    def canonical(self) -> "ResearchExpression":
        children = tuple(child.canonical() if isinstance(child, ResearchBoolean) else child for child in self.children)
        if self.operator in {"and", "or"}:
            flat: list[ResearchExpression] = []
            for child in children:
                if isinstance(child, ResearchBoolean) and child.operator == self.operator:
                    flat.extend(child.children)
                else:
                    flat.append(child)
            deduplicated = {canonical_json(item.to_dict()): item for item in flat}
            children = tuple(deduplicated[key] for key in sorted(deduplicated))
        return ResearchBoolean(self.operator, children)

    def to_dict(self) -> dict[str, Any]:
        return {self.operator: [child.to_dict() for child in self.children]}


ResearchExpression = ResearchPredicate | ResearchBoolean


def _expression(value: Any) -> ResearchExpression:
    if not isinstance(value, Mapping) or len(value) != 1:
        raise ResearchQueryError("an expression must be one predicate or one explicit boolean object")
    if "dimension" in value:  # unreachable for normal mappings with three keys, retained for clarity
        raise ResearchQueryError("predicate must contain dimension, operator, and value")
    key, payload = next(iter(value.items()))
    if key in {"and", "or", "not"}:
        if not isinstance(payload, list):
            raise ResearchQueryError(f"{key} requires a list")
        return ResearchBoolean(key, tuple(_parse_expression(item) for item in payload))
    raise ResearchQueryError("boolean expressions use exactly one of and, or, not")


def _parse_expression(value: Any) -> ResearchExpression:
    if isinstance(value, Mapping) and set(value) == {"dimension", "operator", "value"}:
        raw = value["value"]
        return ResearchPredicate(
            str(value["dimension"]), str(value["operator"]), tuple(raw) if isinstance(raw, list) else raw
        )
    return _expression(value)


@dataclass(frozen=True)
class ResearchQuery:
    where: ResearchExpression
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ResearchQueryError(f"limit must be between 1 and {MAX_LIMIT}")
        if self.offset < 0:
            raise ResearchQueryError("offset must be nonnegative")

    def canonical(self) -> "ResearchQuery":
        expression = self.where.canonical() if isinstance(self.where, ResearchBoolean) else self.where
        return ResearchQuery(expression, self.limit, self.offset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESEARCH_SCHEMA_VERSION,
            "where": self.canonical().where.to_dict(),
            "limit": self.limit,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchQuery":
        allowed = {"schema", "where", "limit", "offset"}
        unknown = set(value) - allowed
        if unknown or "where" not in value or value.get("schema", RESEARCH_SCHEMA_VERSION) != RESEARCH_SCHEMA_VERSION:
            raise ResearchQueryError("invalid research query schema")
        return cls(
            _parse_expression(value["where"]), int(value.get("limit", DEFAULT_LIMIT)), int(value.get("offset", 0))
        ).canonical()

    @classmethod
    def loads(cls, payload: str, format: str = "json") -> "ResearchQuery":
        if format == "json":
            data = json.loads(payload)
        elif format == "yaml":
            if yaml is None:
                raise ResearchQueryError("YAML support is unavailable")
            data = yaml.safe_load(payload)
        else:
            raise ResearchQueryError("format must be json or yaml")
        return cls.from_dict(data)

    def dumps(self, format: str = "json") -> str:
        if format == "json":
            return canonical_json(self.to_dict())
        if format == "yaml":
            if yaml is None:
                raise ResearchQueryError("YAML support is unavailable")
            return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=True)
        raise ResearchQueryError("format must be json or yaml")


@dataclass(frozen=True)
class ResearchEvidence:
    annotation_id: int
    annotation_record_id: int
    alignment_run_id: int
    alignment_method: str
    alignment_confidence: float
    parser_status: str
    source_native: Mapping[str, Any]
    source_release: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchMatch:
    coordinate: Mapping[str, int | None]
    canonical_text: str | None
    token: str | None
    segment: int
    root: str | None
    lemma: str | None
    pos: str | None
    features: tuple[str, ...]
    evidence: ResearchEvidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchSummary:
    total_matching_rows: int
    returned_rows: int
    limit: int
    offset: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchExecutionMetadata:
    canonical_query: Mapping[str, Any]
    canonical_payload_hash: str
    executed_at_utc: str
    git_revision: str | None
    git_dirty: bool | None
    schema_revision: str | None
    source_releases: tuple[Mapping[str, Any], ...]
    normalization_profile: str | None
    duration_ms: int
    database_row_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchResult:
    metadata: ResearchExecutionMetadata
    summary: ResearchSummary
    matches: tuple[ResearchMatch, ...]

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "canonical_query": self.metadata.canonical_query,
            "source_releases": list(self.metadata.source_releases),
            "normalization_profile": self.metadata.normalization_profile,
            "summary": self.summary.to_dict(),
            "matches": [match.to_dict() for match in self.matches],
        }

    def reproducibility_hash(self) -> str:
        return canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict() | {"reproducibility_hash": self.reproducibility_hash()},
            "summary": self.summary.to_dict(),
            "matches": [match.to_dict() for match in self.matches],
        }


@dataclass(frozen=True)
class CompiledResearchQuery:
    query: ResearchQuery
    where_sql: str
    parameters: Mapping[str, Any]


class ResearchEngine:
    """Composable SELECT-only boundary. It returns immutable values, never ORM rows."""

    def __init__(self, session: Any, registry: Any | None = None):
        self.session, self.registry = session, registry

    def _compile_expression(self, expression: ResearchExpression, params: dict[str, Any], index: list[int]) -> str:
        if isinstance(expression, ResearchBoolean):
            parts = [self._compile_expression(item, params, index) for item in expression.children]
            if expression.operator == "not":
                return f"not ({parts[0]})"
            return "(" + f" {expression.operator} ".join(parts) + ")"
        columns = {
            "canonical_text": "tu.text_raw",
            "token": "ot.surface_raw",
            "segment": "ms.segment_index",
            "root": "coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT')",
            "lemma": "coalesce(ma.source_lemma, ma.source_features_json -> 'native' ->> 'LEM')",
            "pos": "ms.source_pos",
            "surah": "tu.surah_number",
            "ayah": "tu.ayah_number",
            "source_release": "qma.annotation_source_release_id",
            "alignment_method": "qma.method",
            "parser_status": "rec.parse_status",
        }
        index[0] += 1
        name = f"p{index[0]}"
        value = expression.value
        if expression.dimension == "feature":
            if expression.operator == "eq":
                params[name] = value
                return f"exists (select 1 from jsonb_array_elements_text(ma.source_features_json -> 'fragments') f(fragment) where f.fragment = :{name})"
            params[name] = list(value)  # type: ignore[arg-type]
            return f"exists (select 1 from jsonb_array_elements_text(ma.source_features_json -> 'fragments') f(fragment) where f.fragment = any(:{name}))"
        if expression.dimension == "normalization_profile":
            params[name] = value if expression.operator == "eq" else list(value)  # type: ignore[arg-type]
            comparison = f"np.name = :{name}" if expression.operator == "eq" else f"np.name = any(:{name})"
            return (
                "exists (select 1 from normalized_token nt join normalization_profile np on np.id=nt.normalization_profile_id where nt.orthographic_token_id=ot.id and "
                + comparison
                + ")"
            )
        column = columns[expression.dimension]
        if expression.operator == "eq":
            params[name] = value
            return f"{column} = :{name}"
        if expression.operator == "in":
            params[name] = list(value)
            return f"{column} = any(:{name})"  # type: ignore[arg-type]
        params[name] = f"{value}%" if expression.operator == "prefix" else str(value)
        return f"{column} like :{name}" if expression.operator == "prefix" else f"{column} like '%' || :{name} || '%'"

    def compile(self, query: ResearchQuery) -> CompiledResearchQuery:
        query = query.canonical()
        params: dict[str, Any] = {}
        where = self._compile_expression(query.where, params, [0])
        return CompiledResearchQuery(query, where, params)

    def optimize(self, compiled: CompiledResearchQuery) -> CompiledResearchQuery:
        """Canonical AST flattening/deduplication is the sole semantics-preserving optimization."""
        return self.compile(compiled.query.canonical())

    def serialize(self, query: ResearchQuery, format: str = "json") -> str:
        return query.dumps(format)

    def execute(self, query: ResearchQuery) -> ResearchResult:
        started = time.perf_counter()
        compiled = self.optimize(self.compile(query))
        capabilities = {
            "root": AnnotationCapability.ROOT,
            "lemma": AnnotationCapability.LEMMA,
            "pos": AnnotationCapability.POS,
            "feature": AnnotationCapability.FEATURE_FRAGMENTS,
            "segment": AnnotationCapability.TOKEN_SEGMENTATION,
            "alignment_method": AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,
            "parser_status": AnnotationCapability.PARSER_STATUS,
        }
        requested = tuple(
            sorted(
                {
                    capabilities[predicate.dimension]
                    for predicate in _walk(compiled.query.where)
                    if predicate.dimension in capabilities
                },
                key=lambda item: item.value,
            )
        )
        descriptors = resolve_query_scope(
            self.session, SimpleNamespace(source_release_id=None), self.registry, requested
        )
        base_clauses, base_params = morphology_filter_predicates(SimpleNamespace())
        params = dict(base_params) | dict(compiled.parameters)
        params.update({"limit": compiled.query.limit, "offset": compiled.query.offset})
        source_ids = [descriptor.source_release_id for descriptor in descriptors]
        base_clauses.append("qma.annotation_source_release_id = any(:source_ids)")
        params["source_ids"] = source_ids
        where = " and ".join(base_clauses + [compiled.where_sql])
        joins = """
            from qac_morphology_alignment qma join qac_alignment_run ar on ar.id=qma.alignment_run_id
            join morphological_segment ms on ms.id=qma.morphological_segment_id
            join morphological_analysis ma on ma.id=ms.morphological_analysis_id
            join annotation_source_record rec on rec.id=ma.annotation_source_record_id
            join annotation_source_release rel on rel.id=qma.annotation_source_release_id
            left join orthographic_token ot on ot.id=qma.orthographic_token_id left join text_unit tu on tu.id=ot.text_unit_id
        """
        count = int(
            self.session.execute(
                text("select count(distinct qma.id) " + joins + " where " + where), params
            ).scalar_one()
        )
        rows = (
            self.session.execute(
                text(
                    """
            select qma.id alignment_id, qma.alignment_run_id, qma.method, qma.confidence, qma.is_ambiguous,
                   ma.id analysis_id, rec.id record_id, rec.parse_status, rec.raw_record_content, rec.source_line_number,
                   ms.external_locator, ms.segment_index, ms.source_surface, ms.source_pos,
                   coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT') root,
                   coalesce(ma.source_lemma, ma.source_features_json -> 'native' ->> 'LEM') lemma,
                   ma.source_features_json -> 'fragments' features, ma.source_native_payload_json source_native,
                   tu.surah_number, tu.ayah_number, ot.token_in_unit, ot.token_in_full_source_stream, ot.surface_raw, tu.text_raw,
                   rel.id release_id, rel.name release_name, rel.version release_version, rel.raw_sha256 release_sha256, rel.format release_format, rel.parser_name adapter
        """
                    + joins
                    + " where "
                    + where
                    + " order by tu.surah_number nulls last, tu.ayah_number nulls last, ot.token_in_unit nulls last, ms.segment_index, rec.source_line_number, qma.id limit :limit offset :offset"
                ),
                params,
            )
            .mappings()
            .all()
        )
        matches = tuple(
            ResearchMatch(
                {
                    "surah": row["surah_number"],
                    "ayah": row["ayah_number"],
                    "token": row["token_in_unit"],
                    "global_token": row["token_in_full_source_stream"],
                },
                row["text_raw"],
                row["surface_raw"],
                row["segment_index"],
                row["root"],
                row["lemma"],
                row["source_pos"],
                tuple(row["features"] or ()),
                ResearchEvidence(
                    row["analysis_id"],
                    row["record_id"],
                    row["alignment_run_id"],
                    row["method"],
                    float(row["confidence"]),
                    row["parse_status"],
                    {
                        "locator": row["external_locator"],
                        "surface": row["source_surface"],
                        "pos": row["source_pos"],
                        "features": row["source_native"],
                        "raw_record": row["raw_record_content"],
                        "source_line": row["source_line_number"],
                        "alignment_id": row["alignment_id"],
                        "ambiguous": row["is_ambiguous"],
                    },
                    {
                        "id": row["release_id"],
                        "name": row["release_name"],
                        "version": row["release_version"],
                        "sha256": row["release_sha256"],
                        "format": row["release_format"],
                        "adapter": row["adapter"],
                    },
                ),
            )
            for row in rows
        )
        release_rows = (
            self.session.execute(
                text(
                    "select id, name, version, raw_sha256, format, parser_name from annotation_source_release where id = any(:source_ids) order by id"
                ),
                {"source_ids": source_ids},
            )
            .mappings()
            .all()
        )
        releases = tuple(
            {
                "id": row["id"],
                "name": row["name"],
                "version": row["version"],
                "sha256": row["raw_sha256"],
                "format": row["format"],
                "adapter": row["parser_name"],
            }
            for row in release_rows
        )
        profile = next(
            (
                predicate.value
                for predicate in _walk(compiled.query.where)
                if predicate.dimension == "normalization_profile" and predicate.operator == "eq"
            ),
            None,
        )
        env = environment(self.session)
        payload = {
            "query": compiled.query.to_dict(),
            "source_releases": list(releases),
            "normalization_profile": profile,
        }
        metadata = ResearchExecutionMetadata(
            compiled.query.to_dict(),
            canonical_hash(payload),
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            env["git_commit_hash"],
            env["git_dirty"],
            alembic_revision(self.session),
            releases,
            str(profile) if profile else None,
            round((time.perf_counter() - started) * 1000),
            count,
        )
        return ResearchResult(
            metadata,
            ResearchSummary(
                count,
                len(matches),
                compiled.query.limit,
                compiled.query.offset,
                compiled.query.offset + len(matches) < count,
            ),
            matches,
        )


def _walk(expression: ResearchExpression) -> tuple[ResearchPredicate, ...]:
    if isinstance(expression, ResearchPredicate):
        return (expression,)
    return tuple(predicate for child in expression.children for predicate in _walk(child))


def load_query(value: str | Path, format: str | None = None) -> ResearchQuery:
    path = Path(value)
    if path.exists():
        format = format or ("yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json")
        return ResearchQuery.loads(path.read_text(encoding="utf-8"), format)
    return ResearchQuery.loads(str(value), format or "json")


__all__ = [
    "CompiledResearchQuery",
    "ResearchBoolean",
    "ResearchEngine",
    "ResearchEvidence",
    "ResearchExecutionMetadata",
    "ResearchMatch",
    "ResearchPredicate",
    "ResearchQuery",
    "ResearchQueryError",
    "ResearchResult",
    "ResearchSummary",
    "load_query",
    "CountUnit",
    "Metric",
    "AggregateQuery",
    "SetQuery",
    "CooccurrenceQuery",
    "AggregationError",
]


# Phase 5B aggregation values share the immutable Phase 5A AST/compiler.
class CountUnit(str, Enum):
    MATCH_ROW = "MATCH_ROW"
    CANONICAL_TOKEN = "CANONICAL_TOKEN"
    CANONICAL_AYAH = "CANONICAL_AYAH"
    CANONICAL_SURAH = "CANONICAL_SURAH"
    ANNOTATION_RECORD = "ANNOTATION_RECORD"
    MORPHOLOGICAL_ANALYSIS = "MORPHOLOGICAL_ANALYSIS"
    MORPHOLOGICAL_SEGMENT = "MORPHOLOGICAL_SEGMENT"
    SOURCE_NATIVE_RECORD = "SOURCE_NATIVE_RECORD"


class Metric(str, Enum):
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    FREQUENCY = "FREQUENCY"
    MIN = "MIN"
    MAX = "MAX"


class AggregationError(ResearchQueryError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.details}


_AGGREGATABLE_DIMENSIONS = {
    "surah",
    "ayah",
    "root",
    "lemma",
    "pos",
    "feature",
    "source_release",
    "alignment_method",
    "parser_status",
    "canonical_token_text",
    "segment_text",
}
_UNIT_IDENTITIES = {
    CountUnit.MATCH_ROW: "qma.id",
    CountUnit.CANONICAL_TOKEN: "qma.orthographic_token_id",
    CountUnit.CANONICAL_AYAH: "tu.id",
    CountUnit.CANONICAL_SURAH: "tu.surah_id",
    CountUnit.ANNOTATION_RECORD: "rec.id",
    CountUnit.MORPHOLOGICAL_ANALYSIS: "ma.id",
    CountUnit.MORPHOLOGICAL_SEGMENT: "ms.id",
    CountUnit.SOURCE_NATIVE_RECORD: "rec.id",
}
_UNIT_NONNULL = {unit: f"{identity} is not null" for unit, identity in _UNIT_IDENTITIES.items()}
_UNIT_CAPABILITIES = {
    CountUnit.MATCH_ROW: (AnnotationCapability.MORPHOLOGY, AnnotationCapability.TANZIL_TOKEN_ALIGNMENT),
    CountUnit.CANONICAL_TOKEN: (
        AnnotationCapability.MORPHOLOGY,
        AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,
        AnnotationCapability.SOURCE_LOCATOR,
    ),
    CountUnit.CANONICAL_AYAH: (
        AnnotationCapability.MORPHOLOGY,
        AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,
        AnnotationCapability.SOURCE_LOCATOR,
    ),
    CountUnit.CANONICAL_SURAH: (
        AnnotationCapability.MORPHOLOGY,
        AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,
        AnnotationCapability.SOURCE_LOCATOR,
    ),
    CountUnit.ANNOTATION_RECORD: (AnnotationCapability.MORPHOLOGY,),
    CountUnit.MORPHOLOGICAL_ANALYSIS: (AnnotationCapability.MORPHOLOGY,),
    CountUnit.MORPHOLOGICAL_SEGMENT: (AnnotationCapability.MORPHOLOGY, AnnotationCapability.TOKEN_SEGMENTATION),
    CountUnit.SOURCE_NATIVE_RECORD: (AnnotationCapability.MORPHOLOGY, AnnotationCapability.SOURCE_LOCATOR),
}
_DIMENSION_SQL = {
    "surah": "tu.surah_number",
    "ayah": "tu.ayah_number",
    "root": "coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT')",
    "lemma": "coalesce(ma.source_lemma, ma.source_features_json -> 'native' ->> 'LEM')",
    "pos": "ms.source_pos",
    "source_release": "qma.annotation_source_release_id",
    "alignment_method": "qma.method",
    "parser_status": "rec.parse_status",
    "canonical_token_text": "ot.surface_raw",
    "segment_text": "ms.source_surface",
}


def _bounded_page(limit: int, offset: int, *, evidence: int = 0) -> None:
    if not 1 <= limit <= 1000 or offset < 0 or not 0 <= evidence <= 20:
        raise AggregationError("unbounded_aggregation", "rows must be 1..1000, offset nonnegative, evidence 0..20")


@dataclass(frozen=True)
class AggregateQuery:
    query: ResearchQuery
    unit: CountUnit
    metric: Metric = Metric.COUNT
    group_by: tuple[str, ...] = ()
    order: str = "desc"
    limit: int = 50
    offset: int = 0
    evidence_samples: int = 0

    def __post_init__(self) -> None:
        _bounded_page(self.limit, self.offset, evidence=self.evidence_samples)
        if len(self.group_by) > 3:
            raise AggregationError("excessive_group_dimensions", "at most three group dimensions are supported")
        if len(set(self.group_by)) != len(self.group_by) or any(
            k not in _AGGREGATABLE_DIMENSIONS for k in self.group_by
        ):
            raise AggregationError("unsupported_group_dimension", "unsupported or duplicate group dimension")
        if self.order not in {"asc", "desc"}:
            raise AggregationError("unsupported_metric", "order must be asc or desc")
        if self.metric in {Metric.MIN, Metric.MAX}:
            raise AggregationError("unsupported_metric", "MIN/MAX do not have stable count semantics")

    def canonical(self) -> "AggregateQuery":
        return AggregateQuery(
            self.query.canonical(),
            self.unit,
            self.metric,
            self.group_by,
            self.order,
            self.limit,
            self.offset,
            self.evidence_samples,
        )

    def to_dict(self) -> dict[str, Any]:
        q = self.canonical()
        return {
            "schema": "research-aggregation-v1",
            "query": q.query.to_dict(),
            "unit": q.unit.value,
            "metric": q.metric.value,
            "group_by": list(q.group_by),
            "order": q.order,
            "limit": q.limit,
            "offset": q.offset,
            "evidence_samples": q.evidence_samples,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "AggregateQuery":
        try:
            return cls(
                ResearchQuery.from_dict(v["query"]),
                CountUnit(v["unit"]),
                Metric(v.get("metric", "COUNT")),
                tuple(v.get("group_by", ())),
                str(v.get("order", "desc")),
                int(v.get("limit", 50)),
                int(v.get("offset", 0)),
                int(v.get("evidence_samples", 0)),
            ).canonical()
        except KeyError as e:
            raise AggregationError("ambiguous_count_semantics", "aggregate requires query and explicit unit") from e
        except ValueError as e:
            raise AggregationError("unsupported_count_unit", str(e)) from e


class SetOperation(str, Enum):
    INTERSECTION = "INTERSECTION"
    UNION = "UNION"
    DIFFERENCE = "DIFFERENCE"
    SYMMETRIC_DIFFERENCE = "SYMMETRIC_DIFFERENCE"


@dataclass(frozen=True)
class SetQuery:
    left: ResearchQuery
    right: ResearchQuery
    identity: CountUnit
    operation: SetOperation
    limit: int = 100
    evidence_samples: int = 0

    def __post_init__(self) -> None:
        _bounded_page(self.limit, 0, evidence=self.evidence_samples)
        if self.identity not in {CountUnit.CANONICAL_TOKEN, CountUnit.CANONICAL_AYAH, CountUnit.CANONICAL_SURAH}:
            raise AggregationError(
                "incompatible_identity_unit", "sets require canonical token, ayah, or surah identity"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "research-set-v1",
            "left": self.left.canonical().to_dict(),
            "right": self.right.canonical().to_dict(),
            "identity": self.identity.value,
            "operation": self.operation.value,
            "limit": self.limit,
            "evidence_samples": self.evidence_samples,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "SetQuery":
        try:
            return cls(
                ResearchQuery.from_dict(v["left"]),
                ResearchQuery.from_dict(v["right"]),
                CountUnit(v["identity"]),
                SetOperation(v["operation"]),
                int(v.get("limit", 100)),
                int(v.get("evidence_samples", 0)),
            )
        except (KeyError, ValueError) as e:
            raise AggregationError(
                "incompatible_identity", "set needs complete left/right queries, identity and operation"
            ) from e


class PairPolicy(str, Enum):
    UNIQUE_TOKEN_PAIRS = "UNIQUE_TOKEN_PAIRS"
    ALL_CROSS_PRODUCT_PAIRS = "ALL_CROSS_PRODUCT_PAIRS"


@dataclass(frozen=True)
class CooccurrenceQuery:
    left: ResearchQuery
    right: ResearchQuery
    identity: CountUnit
    scope: str = "SAME_AYAH"
    pair_policy: PairPolicy = PairPolicy.UNIQUE_TOKEN_PAIRS
    limit: int = 100
    evidence_samples: int = 0

    def __post_init__(self) -> None:
        _bounded_page(self.limit, 0, evidence=self.evidence_samples)
        if self.scope != "SAME_AYAH":
            raise AggregationError(
                "invalid_cooccurrence_scope", "only SAME_AYAH is justified by completed alignment semantics"
            )
        if self.identity != CountUnit.CANONICAL_TOKEN:
            raise AggregationError("incompatible_identity_unit", "cooccurrence requires CANONICAL_TOKEN identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "research-cooccurrence-v1",
            "left": self.left.canonical().to_dict(),
            "right": self.right.canonical().to_dict(),
            "identity": self.identity.value,
            "scope": self.scope,
            "pair_policy": self.pair_policy.value,
            "limit": self.limit,
            "evidence_samples": self.evidence_samples,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "CooccurrenceQuery":
        try:
            return cls(
                ResearchQuery.from_dict(v["left"]),
                ResearchQuery.from_dict(v["right"]),
                CountUnit(v["identity"]),
                str(v.get("scope", "SAME_AYAH")),
                PairPolicy(v.get("pair_policy", "UNIQUE_TOKEN_PAIRS")),
                int(v.get("limit", 100)),
                int(v.get("evidence_samples", 0)),
            )
        except (KeyError, ValueError) as e:
            raise AggregationError(
                "invalid_cooccurrence_scope", "cooccurrence needs left/right queries, identity and pair policy"
            ) from e


@dataclass(frozen=True)
class AggregateResult:
    metadata: Mapping[str, Any]
    total_groups: int
    returned_groups: int
    truncated: bool
    groups: tuple[Mapping[str, Any], ...]

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata,
            "total_groups": self.total_groups,
            "returned_groups": self.returned_groups,
            "truncated": self.truncated,
            "groups": list(self.groups),
        }

    def reproducibility_hash(self) -> str:
        return canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return self.canonical_payload() | {"reproducibility_hash": self.reproducibility_hash()}


def _required_capabilities(
    query: ResearchQuery, dimensions: tuple[str, ...] = (), unit: CountUnit | None = None
) -> tuple[AnnotationCapability, ...]:
    mapping = {
        "root": AnnotationCapability.ROOT,
        "lemma": AnnotationCapability.LEMMA,
        "pos": AnnotationCapability.POS,
        "feature": AnnotationCapability.FEATURE_FRAGMENTS,
        "segment": AnnotationCapability.TOKEN_SEGMENTATION,
        "alignment_method": AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,
        "parser_status": AnnotationCapability.PARSER_STATUS,
    }
    capabilities = {mapping[x] for x in [*(p.dimension for p in _walk(query.where)), *dimensions] if x in mapping}
    if unit is not None:
        capabilities.update(_UNIT_CAPABILITIES[unit])
    return tuple(sorted(capabilities, key=lambda x: x.value))


def _research_joins() -> str:
    return """ from qac_morphology_alignment qma join qac_alignment_run ar on ar.id=qma.alignment_run_id join morphological_segment ms on ms.id=qma.morphological_segment_id join morphological_analysis ma on ma.id=ms.morphological_analysis_id join annotation_source_record rec on rec.id=ma.annotation_source_record_id join annotation_source_release rel on rel.id=qma.annotation_source_release_id left join orthographic_token ot on ot.id=qma.orthographic_token_id left join text_unit tu on tu.id=ot.text_unit_id """


def _requested_source_ids(query: ResearchQuery) -> tuple[int, ...]:
    """Return explicit positive source-release selections or reject ambiguous boolean use."""

    def visit(expression: ResearchExpression, negated: bool = False) -> list[int]:
        if isinstance(expression, ResearchPredicate):
            if expression.dimension != "source_release":
                return []
            if negated or expression.operator not in {"eq", "in"}:
                raise AggregationError(
                    "ambiguous_source_selection", "source_release requires a positive eq/in selection"
                )
            return [
                int(value)
                for value in (expression.value if isinstance(expression.value, tuple) else (expression.value,))
            ]
        if expression.operator == "or" and any(
            predicate.dimension == "source_release" for predicate in _walk(expression)
        ):
            raise AggregationError("ambiguous_source_selection", "source_release cannot appear inside or")
        return [
            value for child in expression.children for value in visit(child, negated or expression.operator == "not")
        ]

    return tuple(sorted(set(visit(query.where))))


def _scope_metadata(
    engine: ResearchEngine,
    query: ResearchQuery,
    descriptors: tuple[Any, ...],
    required: tuple[AnnotationCapability, ...],
) -> dict[str, Any]:
    requested = _requested_source_ids(query)
    completed = (
        engine.session.execute(
            text(
                "select distinct qma.annotation_source_release_id from qac_morphology_alignment qma join qac_alignment_run ar on ar.id=qma.alignment_run_id where ar.status='completed' order by qma.annotation_source_release_id"
            )
        )
        .scalars()
        .all()
    )
    return {
        "requested_release_ids": list(requested),
        "effective_release_ids": [item.source_release_id for item in descriptors],
        "effective": [item.to_dict() for item in descriptors],
        "excluded_release_ids": [int(item) for item in completed if requested and int(item) not in requested],
        "rejected_release_ids": [],
        "adapters": [item.to_dict() for item in descriptors],
        "adapter_ids": sorted({item.adapter_id for item in descriptors}),
        "required_capabilities": [item.value for item in required],
    }


def _base_for(
    engine: ResearchEngine,
    query: ResearchQuery,
    prefix: str = "",
    required: tuple[AnnotationCapability, ...] | None = None,
) -> tuple[str, dict[str, Any], tuple[Any, ...]]:
    compiled = engine.optimize(engine.compile(query))
    requested = _requested_source_ids(compiled.query)
    required = required if required is not None else _required_capabilities(query)
    if len(requested) > 1:
        raise AggregationError(
            "incompatible_source_scope",
            "mixed explicit source releases are not comparable",
            requested_release_ids=list(requested),
            effective_release_ids=[],
            excluded_release_ids=[],
            rejected_release_ids=list(requested),
            adapters=[],
            required_capabilities=[item.value for item in required],
        )
    try:
        descriptors = (
            tuple(
                descriptor
                for source_id in requested
                for descriptor in resolve_query_scope(
                    engine.session, SimpleNamespace(source_release_id=source_id), engine.registry, required
                )
            )
            if requested
            else resolve_query_scope(engine.session, SimpleNamespace(source_release_id=None), engine.registry, required)
        )
    except Exception as exc:
        raise AggregationError(
            "incompatible_source_scope",
            "source scope does not satisfy required capabilities",
            requested_release_ids=list(requested),
            effective_release_ids=[],
            excluded_release_ids=[],
            rejected_release_ids=list(requested),
            adapters=[],
            required_capabilities=[item.value for item in required],
        ) from exc
    if len({descriptor.adapter_id for descriptor in descriptors}) > 1:
        raise AggregationError(
            "incompatible_source_scope",
            "mixed annotation adapters are not comparable",
            **_scope_metadata(engine, compiled.query, descriptors, required),
        )
    params = {f"{prefix}{key}": value for key, value in compiled.parameters.items()}
    where = compiled.where_sql
    for key in compiled.parameters:
        where = where.replace(f":{key}", f":{prefix}{key}")
    where = " and ".join(
        [
            "ar.status = 'completed'",
            "qma.status <> 'unmatched'",
            "qma.annotation_source_release_id = any(:%ssource_ids)" % prefix,
            where,
        ]
    )
    params[f"{prefix}source_ids"] = [d.source_release_id for d in descriptors]
    return where, params, descriptors


def _evidence_rows(
    engine: ResearchEngine,
    where: str,
    params: Mapping[str, Any],
    identity: str,
    count: int,
    group_by: tuple[str, ...] = (),
    values: tuple[Any, ...] = (),
    ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    if count == 0:
        return []
    bound = dict(params) | {"evidence_limit": count}
    clauses = [where, identity + " is not null"]
    if ids:
        bound["evidence_ids"] = ids
        clauses.append(identity + " = any(:evidence_ids)")
    for index, (dimension, value) in enumerate(zip(group_by, values)):
        key = f"evidence_group_{index}"
        bound[key] = value
        clauses.append(
            "exists (select 1 from jsonb_array_elements_text(coalesce(ma.source_features_json -> 'fragments','[]'::jsonb)) f where f.value = :"
            + key
            + ")"
            if dimension == "feature"
            else _DIMENSION_SQL[dimension] + " is not distinct from :" + key
        )
    sql = (
        "select "
        + identity
        + " stable_id,qma.id alignment_id,qma.alignment_run_id,qma.method,qma.confidence,qma.status alignment_status,qma.is_ambiguous,rec.id annotation_record_id,rec.raw_record_content,rec.source_line_number,rec.parse_status,ma.id analysis_id,ma.source_native_payload_json,ma.source_features_json,ms.id segment_id,ms.external_locator,ms.segment_index,ms.source_surface,ms.source_pos,qma.orthographic_token_id token_id,tu.id ayah_id,tu.surah_id surah_id,tu.surah_number,tu.ayah_number,ot.token_in_unit,ot.surface_raw,rel.id release_id,rel.name release_name,rel.version release_version,rel.raw_sha256 release_sha256,rel.format release_format,rel.parser_name adapter "
        + _research_joins()
        + " where "
        + " and ".join(clauses)
        + " order by stable_id,qma.id,rec.id,ma.id,ms.id limit :evidence_limit"
    )
    return [
        {
            "canonical_id": {"unit_identity": identity, "id": int(row["stable_id"])},
            "canonical": {
                "token_id": row["token_id"],
                "ayah_id": row["ayah_id"],
                "surah_id": row["surah_id"],
                "coordinate": {"surah": row["surah_number"], "ayah": row["ayah_number"], "token": row["token_in_unit"]},
                "raw_token": row["surface_raw"],
            },
            "annotation": {
                "record_id": row["annotation_record_id"],
                "analysis_id": row["analysis_id"],
                "segment_id": row["segment_id"],
                "parse_status": row["parse_status"],
                "raw_record": row["raw_record_content"],
                "source_line": row["source_line_number"],
            },
            "source_native": {
                "locator": row["external_locator"],
                "segment_index": row["segment_index"],
                "surface": row["source_surface"],
                "pos": row["source_pos"],
                "payload": row["source_native_payload_json"],
                "features": row["source_features_json"],
            },
            "alignment": {
                "id": row["alignment_id"],
                "run_id": row["alignment_run_id"],
                "method": row["method"],
                "confidence": float(row["confidence"]),
                "status": row["alignment_status"],
                "ambiguous": row["is_ambiguous"],
            },
            "source_release": {
                "id": row["release_id"],
                "name": row["release_name"],
                "version": row["release_version"],
                "sha256": row["release_sha256"],
                "format": row["release_format"],
                "adapter": row["adapter"],
            },
        }
        for row in engine.session.execute(text(sql), bound).mappings().all()
    ]


def _representatives(
    engine: ResearchEngine,
    where: str,
    params: Mapping[str, Any],
    identity: str,
    count: int,
    group_by: tuple[str, ...] = (),
    values: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    return _evidence_rows(engine, where, params, identity, count, group_by, values)


def _ids_evidence(engine: ResearchEngine, ids: list[int], unit: CountUnit, count: int) -> list[dict[str, Any]]:
    return _evidence_rows(
        engine, "ar.status='completed' and qma.status <> 'unmatched'", {}, _UNIT_IDENTITIES[unit], count, ids=ids
    )


def _aggregate(engine: ResearchEngine, request: AggregateQuery) -> AggregateResult:
    request = request.canonical()
    required = _required_capabilities(request.query, request.group_by, request.unit)
    where, params, descriptors = _base_for(engine, request.query, required=required)
    identity = _UNIT_IDENTITIES[request.unit]
    where = " and ".join([where, _UNIT_NONNULL.get(request.unit, "true")])
    dimensions = list(request.group_by)
    select_dimensions = []
    group_expr = []
    joins = ""
    for i, name in enumerate(dimensions):
        if name == "feature":
            joins += " cross join lateral jsonb_array_elements_text(coalesce(ma.source_features_json -> 'fragments', '[]'::jsonb)) feature_value"
            expr = "feature_value.value"
        else:
            expr = _DIMENSION_SQL[name]
        select_dimensions.append(f"{expr} g{i}")
        group_expr.append(expr)
    if any(name in {"root", "lemma", "pos"} for name in dimensions):
        where = " and ".join(
            [where, *(_DIMENSION_SQL[name] + " is not null" for name in dimensions if name in {"root", "lemma", "pos"})]
        )
    aggregate = (
        f"count(distinct {identity})"
        if request.metric in {Metric.COUNT, Metric.COUNT_DISTINCT, Metric.FREQUENCY}
        else f"{request.metric.value.lower()}({identity})"
    )
    select = ", ".join([*select_dimensions, f"{aggregate} metric"])
    grouped = f"select {select} {_research_joins()}{joins} where {where}" + (
        " group by " + ", ".join(group_expr) if group_expr else ""
    )
    total = int(engine.session.execute(text("select count(*) from (" + grouped + ") grouped"), params).scalar_one())
    order_key = "metric" if request.order == "desc" else "metric"
    key_order = ", ".join(f"g{i} asc nulls last" for i in range(len(dimensions))) or "1"
    params |= {"limit": request.limit, "offset": request.offset}
    rows = (
        engine.session.execute(
            text(grouped + f" order by {order_key} {request.order}, {key_order} limit :limit offset :offset"), params
        )
        .mappings()
        .all()
    )
    groups = []
    for row in rows:
        keys = {name: row[f"g{i}"] for i, name in enumerate(dimensions)}
        groups.append(
            {
                "key": keys,
                "metric": int(row["metric"]),
                "unit": request.unit.value,
                "representative_evidence": _representatives(
                    engine,
                    where,
                    params,
                    identity,
                    request.evidence_samples,
                    tuple(dimensions),
                    tuple(keys[name] for name in dimensions),
                ),
            }
        )
    metadata = {
        "canonical_request": request.to_dict(),
        "canonical_payload_hash": canonical_hash(request.to_dict()),
        "unit": request.unit.value,
        "metric": request.metric.value,
        "required_capabilities": [x.value for x in required],
        "source_scope": _scope_metadata(engine, request.query, descriptors, required),
        "dedup_identity": identity,
        "normalization": {
            "implicit": False,
            "profile_id": None,
            "profile_version": None,
            "raw_evidence_preserved": True,
        },
    }
    return AggregateResult(metadata, total, len(groups), request.offset + len(groups) < total, tuple(groups))


def _set_execute(engine: ResearchEngine, request: SetQuery) -> dict[str, Any]:
    required = tuple(
        sorted(
            set(
                _required_capabilities(request.left, unit=request.identity)
                + _required_capabilities(request.right, unit=request.identity)
            ),
            key=lambda item: item.value,
        )
    )
    lw, lp, ld = _base_for(engine, request.left, "l_", required)
    rw, rp, rd = _base_for(engine, request.right, "r_", required)
    if tuple(d.adapter_id for d in ld) != tuple(d.adapter_id for d in rd):
        raise AggregationError("incompatible_source_scope", "source adapters are not comparable")
    identity = _UNIT_IDENTITIES[request.identity]
    nonnull = _UNIT_NONNULL[request.identity]
    left = f"select distinct {identity} id {_research_joins()} where {lw} and {nonnull}"
    right = f"select distinct {identity} id {_research_joins()} where {rw} and {nonnull}"
    op = {
        SetOperation.INTERSECTION: "intersect",
        SetOperation.UNION: "union",
        SetOperation.DIFFERENCE: "except",
        SetOperation.SYMMETRIC_DIFFERENCE: "(select id from left_set except select id from right_set) union (select id from right_set except select id from left_set)",
    }[request.operation]
    result = (
        f"select id from left_set {op} select id from right_set"
        if request.operation != SetOperation.SYMMETRIC_DIFFERENCE
        else op
    )
    sql = f"with left_set as ({left}), right_set as ({right}), result_set as ({result}) select (select count(*) from left_set) left_cardinality,(select count(*) from right_set) right_cardinality,(select count(*) from left_set join right_set using(id)) overlap_cardinality,(select count(*) from result_set) result_cardinality,(select coalesce(jsonb_agg(id order by id), '[]'::jsonb) from (select id from result_set order by id limit :limit) x) ids"
    row = engine.session.execute(text(sql), lp | rp | {"limit": request.limit}).mappings().one()
    payload = {
        "canonical_request": request.to_dict(),
        "identity": request.identity.value,
        "operation": request.operation.value,
        "left_cardinality": int(row["left_cardinality"]),
        "right_cardinality": int(row["right_cardinality"]),
        "overlap_cardinality": int(row["overlap_cardinality"]),
        "result_cardinality": int(row["result_cardinality"]),
        "ids": list(row["ids"] or []),
        "representative_evidence": _ids_evidence(
            engine, list(row["ids"] or []), request.identity, request.evidence_samples
        ),
        "required_capabilities": [item.value for item in required],
        "source_scope": {
            "left": _scope_metadata(engine, request.left, ld, required),
            "right": _scope_metadata(engine, request.right, rd, required),
        },
    }
    return payload | {"reproducibility_hash": canonical_hash(payload)}


def _cooccurrence_execute(engine: ResearchEngine, request: CooccurrenceQuery) -> dict[str, Any]:
    required = tuple(
        sorted(
            set(
                _required_capabilities(request.left, unit=request.identity)
                + _required_capabilities(request.right, unit=request.identity)
            ),
            key=lambda item: item.value,
        )
    )
    lw, lp, ld = _base_for(engine, request.left, "l_", required)
    rw, rp, rd = _base_for(engine, request.right, "r_", required)
    if tuple(d.adapter_id for d in ld) != tuple(d.adapter_id for d in rd):
        raise AggregationError("incompatible_source_scope", "source adapters are not comparable")
    left = f"select distinct tu.id ayah_id, tu.surah_id surah_id, qma.orthographic_token_id token_id {_research_joins()} where {lw} and qma.orthographic_token_id is not null and tu.id is not null"
    right = f"select distinct tu.id ayah_id, tu.surah_id surah_id, qma.orthographic_token_id token_id {_research_joins()} where {rw} and qma.orthographic_token_id is not null and tu.id is not null"
    pairs = (
        "select distinct l.token_id left_token_id,r.token_id right_token_id,l.ayah_id,l.surah_id from left_set l join right_set r on r.ayah_id=l.ayah_id"
        if request.pair_policy == PairPolicy.UNIQUE_TOKEN_PAIRS
        else "select l.token_id left_token_id,r.token_id right_token_id,l.ayah_id,l.surah_id from left_set l join right_set r on r.ayah_id=l.ayah_id"
    )
    sql = f"with left_set as ({left}),right_set as ({right}),pairs as ({pairs}) select (select count(*) from left_set) left_token_count,(select count(*) from right_set) right_token_count,(select count(distinct ayah_id) from pairs) distinct_ayahs,(select count(distinct surah_id) from pairs) distinct_surahs,(select count(*) from pairs) pair_cardinality,(select coalesce(jsonb_agg(jsonb_build_object('left_token_id',left_token_id,'right_token_id',right_token_id,'ayah_id',ayah_id,'surah_id',surah_id) order by surah_id,ayah_id,left_token_id,right_token_id),'[]'::jsonb) from (select * from pairs order by surah_id,ayah_id,left_token_id,right_token_id limit :limit) page) pair_page"
    row = engine.session.execute(text(sql), lp | rp | {"limit": request.limit}).mappings().one()
    page = list(row["pair_page"] or [])
    evidence = (
        []
        if not request.evidence_samples
        else _ids_evidence(
            engine,
            sorted({int(pair["left_token_id"]) for pair in page} | {int(pair["right_token_id"]) for pair in page}),
            CountUnit.CANONICAL_TOKEN,
            request.evidence_samples,
        )
    )
    payload = {
        "canonical_request": request.to_dict(),
        "scope": "SAME_AYAH",
        "identity": request.identity.value,
        "pair_policy": request.pair_policy.value,
        "left_stable_token_count": int(row["left_token_count"]),
        "right_stable_token_count": int(row["right_token_count"]),
        "distinct_ayahs": int(row["distinct_ayahs"]),
        "distinct_surahs": int(row["distinct_surahs"]),
        "pair_cardinality": int(row["pair_cardinality"]),
        "truncated": int(row["pair_cardinality"]) > request.limit,
        "pairs": page,
        "representative_evidence": evidence,
        "required_capabilities": [item.value for item in required],
        "source_scope": {
            "left": _scope_metadata(engine, request.left, ld, required),
            "right": _scope_metadata(engine, request.right, rd, required),
        },
    }
    return payload | {"reproducibility_hash": canonical_hash(payload)}


def _aggregate_explain(engine: ResearchEngine, request: Any) -> dict[str, Any]:
    if isinstance(request, AggregateQuery):
        query = request.query
        unit = request.unit.value
        groups = list(request.group_by)
        canonical = request.to_dict()
    elif isinstance(request, SetQuery):
        query = request.left
        unit = request.identity.value
        groups = []
        canonical = request.to_dict()
    else:
        query = request.left
        unit = request.identity.value
        groups = ["SAME_AYAH"]
        canonical = request.to_dict()
    compiled = engine.optimize(engine.compile(query))
    return {
        "canonical_request": canonical,
        "canonical_query": query.to_dict(),
        "optimized_query": compiled.query.to_dict(),
        "unit": unit,
        "groups": groups,
        "required_capabilities": [x.value for x in _required_capabilities(query, tuple(groups))],
        "stages": [
            "completed_alignment",
            "parameterized_predicate",
            "stable_identity_dedup",
            "database_aggregate",
            "bounded_page",
        ],
        "dedup_identity": _UNIT_IDENTITIES.get(getattr(request, "unit", getattr(request, "identity", None))),
        "sql_exposed": False,
    }


ResearchEngine.aggregate = _aggregate  # type: ignore[attr-defined]
ResearchEngine.set = _set_execute  # type: ignore[attr-defined]
ResearchEngine.cooccurrence = _cooccurrence_execute  # type: ignore[attr-defined]
ResearchEngine.explain = _aggregate_explain  # type: ignore[attr-defined]
