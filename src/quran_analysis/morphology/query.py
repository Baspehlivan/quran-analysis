"""Read-only, source-native QAC morphology query API."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sqlalchemy import text

from quran_analysis.annotation_sources.alignment import METHODS
from quran_analysis.annotation_sources.capabilities import AnnotationAdapterRegistry, AnnotationCapability
from quran_analysis.annotation_sources.service import resolve_query_scope

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass(frozen=True)
class MorphologyOccurrence:
    surah: int
    ayah: int
    token_position: int
    token_id: int | None
    token_text: str | None
    verse: str | None
    locator: str
    segment: int
    form: str
    tag: str
    raw_features: str
    feature_fragments: tuple[str, ...]
    parser_status: str
    raw_source_line: str
    source_line: int
    source_release_id: int
    source_identifier: str
    adapter: str
    version: str
    alignment_method: str
    confidence: float
    ambiguity: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MorphologyQueryResult:
    occurrences: tuple[MorphologyOccurrence, ...]
    limit: int
    offset: int
    effective_source_release_ids: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "offset": self.offset, "effective_source_release_ids": list(self.effective_source_release_ids), "results": [item.to_dict() for item in self.occurrences]}


@dataclass(frozen=True)
class MorphologyQuery:
    source_release_id: int | None = None
    root: str | None = None
    lemma: str | None = None
    tag: str | None = None
    feature: str | None = None
    surah: int | None = None
    ayah: int | None = None
    token: int | None = None
    segment: int | None = None
    alignment_method: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if self.offset < 0:
            raise ValueError("offset must be nonnegative")
        if self.alignment_method is not None and self.alignment_method not in METHODS:
            raise ValueError("invalid alignment method")
        if not any((self.source_release_id, self.root, self.lemma, self.tag, self.feature, self.surah, self.ayah, self.token, self.segment, self.alignment_method)):
            raise ValueError("at least one morphology filter is required")
        for name in ("source_release_id", "surah", "ayah", "token", "segment"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive")


def morphology_filter_predicates(filters: Any) -> tuple[list[str], dict[str, Any]]:
    """Build the one canonical Phase 3B predicate set for query and analytics reads."""
    clauses = ["ar.status = 'completed'", "qma.status <> 'unmatched'"]
    params: dict[str, Any] = {}
    for field, column in (("source_release_id", "qma.annotation_source_release_id"), ("root", "coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT')"), ("lemma", "coalesce(ma.source_lemma, ma.source_features_json -> 'native' ->> 'LEM')"), ("tag", "ms.source_pos"), ("alignment_method", "qma.method"), ("surah", "tu.surah_number"), ("ayah", "tu.ayah_number"), ("token", "ot.token_in_unit"), ("segment", "ms.segment_index")):
        value = getattr(filters, field, None)
        if value is not None:
            clauses.append(f"{column} = :{field}")
            params[field] = value
    if getattr(filters, "feature", None) is not None:
        clauses.append("exists (select 1 from jsonb_array_elements_text(ma.source_features_json -> 'fragments') f(fragment) where f.fragment = :feature)")
        params["feature"] = filters.feature
    return clauses, params


class MorphologyRepository(Protocol):
    def find(self, query: MorphologyQuery) -> MorphologyQueryResult: ...


class SqlMorphologyRepository:
    """Single query boundary; callers never need morphology table joins."""

    def __init__(self, session: Any, registry: AnnotationAdapterRegistry | None = None):
        self.session = session
        self.registry = registry

    def find(self, query: MorphologyQuery) -> MorphologyQueryResult:
        descriptors = resolve_query_scope(self.session, query, self.registry, (AnnotationCapability.MORPHOLOGY,))
        clauses, params = morphology_filter_predicates(query)
        if query.source_release_id is None:
            clauses.append("qma.annotation_source_release_id = any(:effective_source_release_ids)")
            params["effective_source_release_ids"] = [item.source_release_id for item in descriptors]
        params |= {"limit": query.limit, "offset": query.offset}
        rows = self.session.execute(text(f"""
            select tu.surah_number, tu.ayah_number, ot.token_in_unit, ot.id token_id,
                   ot.surface_raw token_text, tu.text_raw verse, ms.external_locator locator,
                   ms.segment_index, ms.source_surface form, ms.source_pos tag,
                   ma.source_features_json ->> 'raw_text' raw_features,
                   ma.source_features_json -> 'fragments' feature_fragments,
                   rec.parse_status parser_status, rec.raw_record_content raw_source_line,
                   rec.source_line_number source_line, rel.id source_release_id,
                   rel.format source_identifier, rel.parser_name adapter, rel.version,
                   qma.method alignment_method, qma.confidence, qma.is_ambiguous ambiguity
              from qac_morphology_alignment qma
              join qac_alignment_run ar on ar.id = qma.alignment_run_id
              join morphological_segment ms on ms.id = qma.morphological_segment_id
              join morphological_analysis ma on ma.id = ms.morphological_analysis_id
              join annotation_source_record rec on rec.id = ma.annotation_source_record_id
              join annotation_source_release rel on rel.id = qma.annotation_source_release_id
              left join orthographic_token ot on ot.id = qma.orthographic_token_id
              left join text_unit tu on tu.id = ot.text_unit_id
             where {' and '.join(clauses)}
             order by tu.surah_number, tu.ayah_number, ot.token_in_unit, ms.segment_index, rec.source_line_number
             limit :limit offset :offset
        """), params).mappings()
        items = tuple(MorphologyOccurrence(
            surah=row["surah_number"], ayah=row["ayah_number"], token_position=row["token_in_unit"], token_id=row["token_id"], token_text=row["token_text"], verse=row["verse"], locator=row["locator"], segment=row["segment_index"], form=row["form"], tag=row["tag"], raw_features=row["raw_features"], feature_fragments=tuple(row["feature_fragments"] or ()), parser_status=row["parser_status"], raw_source_line=row["raw_source_line"], source_line=row["source_line"], source_release_id=row["source_release_id"], source_identifier=row["source_identifier"], adapter=row["adapter"], version=row["version"], alignment_method=row["alignment_method"], confidence=row["confidence"], ambiguity=row["ambiguity"],
        ) for row in rows)
        return MorphologyQueryResult(items, query.limit, query.offset, tuple(item.source_release_id for item in descriptors))


class MorphologyQueryService:
    def __init__(self, repository: MorphologyRepository):
        self.repository = repository

    def find(self, query: MorphologyQuery) -> MorphologyQueryResult:
        return self.repository.find(query)

    def show_ayah(self, surah: int, ayah: int, **filters: Any) -> MorphologyQueryResult:
        return self.find(MorphologyQuery(surah=surah, ayah=ayah, **filters))

    def show_token(self, surah: int, ayah: int, token: int, **filters: Any) -> MorphologyQueryResult:
        return self.find(MorphologyQuery(surah=surah, ayah=ayah, token=token, **filters))

    def show_locator(self, surah: int, ayah: int, token: int, segment: int, **filters: Any) -> MorphologyQueryResult:
        return self.find(MorphologyQuery(surah=surah, ayah=ayah, token=token, segment=segment, **filters))


__all__ = ["MorphologyOccurrence", "MorphologyQuery", "MorphologyQueryResult", "MorphologyRepository", "MorphologyQueryService", "SqlMorphologyRepository"]
