"""Read-only aggregate analytics over Phase 3B morphology alignment evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text

from quran_analysis.annotation_sources.alignment import METHODS
from quran_analysis.annotation_sources.capabilities import AnnotationAdapterRegistry, AnnotationCapability
from quran_analysis.annotation_sources.service import resolve_query_scope
from quran_analysis.morphology.query import morphology_filter_predicates

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass(frozen=True)
class MorphologyAnalyticsFilter:
    """The Phase 3B filter vocabulary for aggregate reads; all fields are exact."""

    source_release_id: int | None = None
    surah: int | None = None
    ayah: int | None = None
    root: str | None = None
    lemma: str | None = None
    tag: str | None = None
    feature: str | None = None
    alignment_method: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_release_id", "surah", "ayah"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive")
        if self.alignment_method is not None and self.alignment_method not in METHODS:
            raise ValueError("invalid alignment method")


@dataclass(frozen=True)
class FrequencyRow:
    value: str | int
    segment_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrequencyResult:
    dimension: str
    results: tuple[FrequencyRow, ...]
    limit: int
    offset: int

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "limit": self.limit, "offset": self.offset, "results": [row.to_dict() for row in self.results]}


@dataclass(frozen=True)
class SurahStatistic:
    surah: int
    segment_count: int
    tanzil_token_count: int
    ayah_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AyahStatistic:
    surah: int
    ayah: int
    segment_count: int
    tanzil_token_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SegmentDistributionRow:
    segments_per_tanzil_token: int
    tanzil_token_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StatisticsResult:
    dimension: str
    results: tuple[SurahStatistic | AyahStatistic | SegmentDistributionRow, ...]
    limit: int
    offset: int

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "limit": self.limit, "offset": self.offset, "results": [row.to_dict() for row in self.results]}


@dataclass(frozen=True)
class MorphologySummary:
    """Counts use explicit units: no segment count is labelled as a word count."""

    aligned_segment_count: int
    tanzil_token_count: int
    ayah_count: int
    source_record_count: int
    alignment_record_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MorphologyAnalyticsService:
    """Public, ORM-free analytics API backed only by bounded SELECT statements."""

    def __init__(self, session: Any, registry: AnnotationAdapterRegistry | None = None):
        self.session = session
        self.registry = registry

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if limit < 1 or limit > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if offset < 0:
            raise ValueError("offset must be nonnegative")

    def _base(self, filters: MorphologyAnalyticsFilter, required: tuple[AnnotationCapability, ...] = ()) -> tuple[str, dict[str, Any]]:
        descriptors = resolve_query_scope(self.session, filters, self.registry, (AnnotationCapability.MORPHOLOGY, AnnotationCapability.FREQUENCY_ANALYTICS, *required))
        clauses, params = morphology_filter_predicates(filters)
        if filters.source_release_id is None:
            clauses.append("qma.annotation_source_release_id = any(:effective_source_release_ids)")
            params["effective_source_release_ids"] = [item.source_release_id for item in descriptors]
        return """
            from qac_morphology_alignment qma
            join qac_alignment_run ar on ar.id = qma.alignment_run_id
            join morphological_segment ms on ms.id = qma.morphological_segment_id
            join morphological_analysis ma on ma.id = ms.morphological_analysis_id
            join annotation_source_record rec on rec.id = ma.annotation_source_record_id
            join annotation_source_release rel on rel.id = qma.annotation_source_release_id
            left join orthographic_token ot on ot.id = qma.orthographic_token_id
            left join text_unit tu on tu.id = ot.text_unit_id
            where """ + " and ".join(clauses), params

    def summary(self, filters: MorphologyAnalyticsFilter | None = None) -> MorphologySummary:
        base, params = self._base(filters or MorphologyAnalyticsFilter())
        row = self.session.execute(text("""
            select count(distinct qma.morphological_segment_id) aligned_segment_count,
                   count(distinct qma.orthographic_token_id) filter (where qma.orthographic_token_id is not null) tanzil_token_count,
                   count(distinct (tu.surah_number, tu.ayah_number)) filter (where tu.id is not null) ayah_count,
                   count(distinct rec.id) source_record_count,
                   count(*) alignment_record_count
        """ + base), params).mappings().one()
        return MorphologySummary(**{key: int(value) for key, value in row.items()})

    def _frequency(self, dimension: str, expression: str, filters: MorphologyAnalyticsFilter | None, limit: int, offset: int, exclude_null: bool = False, required: tuple[AnnotationCapability, ...] = ()) -> FrequencyResult:
        self._page(limit, offset)
        base, params = self._base(filters or MorphologyAnalyticsFilter(), required)
        params |= {"limit": limit, "offset": offset}
        rows = self.session.execute(text(f"""
            select {expression} value, count(distinct qma.morphological_segment_id) segment_count
            {base}{f' and {expression} is not null' if exclude_null else ''}
            group by {expression}
            order by segment_count desc, value asc nulls last
            limit :limit offset :offset
        """), params).mappings().all()
        return FrequencyResult(dimension, tuple(FrequencyRow(row["value"], int(row["segment_count"])) for row in rows), limit, offset)

    def root_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("root", "coalesce(ma.source_root, ma.source_features_json -> 'native' ->> 'ROOT')", filters, limit, offset, True, (AnnotationCapability.ROOT,))

    def lemma_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("lemma", "coalesce(ma.source_lemma, ma.source_features_json -> 'native' ->> 'LEM')", filters, limit, offset, True, (AnnotationCapability.LEMMA,))

    def tag_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("tag", "ms.source_pos", filters, limit, offset, required=(AnnotationCapability.POS,))

    def feature_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        self._page(limit, offset)
        base, params = self._base(filters or MorphologyAnalyticsFilter(), (AnnotationCapability.FEATURE_FRAGMENTS,))
        params |= {"limit": limit, "offset": offset}
        rows = self.session.execute(text("""
            select fragment value, count(distinct morphological_segment_id) segment_count
            from (
                select qma.morphological_segment_id, ma.source_features_json
                """ + base + """
            ) filtered
            cross join lateral jsonb_array_elements_text(filtered.source_features_json -> 'fragments') fragment
            group by fragment
            order by segment_count desc, value asc
            limit :limit offset :offset
        """), params).mappings().all()
        return FrequencyResult("feature", tuple(FrequencyRow(row["value"], int(row["segment_count"])) for row in rows), limit, offset)

    def source_release_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("source_release", "rel.id", filters, limit, offset)

    def parser_status_frequency(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("parser_status", "rec.parse_status", filters, limit, offset)

    def alignment_statistics(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self._frequency("alignment_method", "qma.method", filters, limit, offset, required=(AnnotationCapability.TANZIL_TOKEN_ALIGNMENT,))

    def surah_statistics(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> StatisticsResult:
        self._page(limit, offset)
        base, params = self._base(filters or MorphologyAnalyticsFilter())
        params |= {"limit": limit, "offset": offset}
        rows = self.session.execute(text("""
            select tu.surah_number surah, count(distinct qma.morphological_segment_id) segment_count,
                   count(distinct qma.orthographic_token_id) tanzil_token_count,
                   count(distinct tu.ayah_number) ayah_count
            """ + base + """
            group by tu.surah_number
            order by segment_count desc, surah asc nulls last
            limit :limit offset :offset
        """), params).mappings().all()
        return StatisticsResult("surah", tuple(SurahStatistic(**{key: int(value) for key, value in row.items()}) for row in rows), limit, offset)

    def ayah_statistics(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> StatisticsResult:
        self._page(limit, offset)
        base, params = self._base(filters or MorphologyAnalyticsFilter())
        params |= {"limit": limit, "offset": offset}
        rows = self.session.execute(text("""
            select tu.surah_number surah, tu.ayah_number ayah,
                   count(distinct qma.morphological_segment_id) segment_count,
                   count(distinct qma.orthographic_token_id) tanzil_token_count
            """ + base + """
            group by tu.surah_number, tu.ayah_number
            order by segment_count desc, surah asc nulls last, ayah asc nulls last
            limit :limit offset :offset
        """), params).mappings().all()
        return StatisticsResult("ayah", tuple(AyahStatistic(**{key: int(value) for key, value in row.items()}) for row in rows), limit, offset)

    def segment_distribution(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> StatisticsResult:
        self._page(limit, offset)
        base, params = self._base(filters or MorphologyAnalyticsFilter(), (AnnotationCapability.TOKEN_SEGMENTATION, AnnotationCapability.TANZIL_TOKEN_ALIGNMENT))
        params |= {"limit": limit, "offset": offset}
        rows = self.session.execute(text("""
            select segments_per_tanzil_token, count(*) tanzil_token_count
            from (
                select qma.orthographic_token_id, count(distinct qma.morphological_segment_id) segments_per_tanzil_token
                """ + base + """ and qma.orthographic_token_id is not null
                group by qma.orthographic_token_id
            ) per_token
            group by segments_per_tanzil_token
            order by segments_per_tanzil_token asc
            limit :limit offset :offset
        """), params).mappings().all()
        return StatisticsResult("segments_per_tanzil_token", tuple(SegmentDistributionRow(**{key: int(value) for key, value in row.items()}) for row in rows), limit, offset)

    def parser_status_distribution(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self.parser_status_frequency(filters, limit, offset)

    def source_release_distribution(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self.source_release_frequency(filters, limit, offset)

    def alignment_method_distribution(self, filters: MorphologyAnalyticsFilter | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> FrequencyResult:
        return self.alignment_statistics(filters, limit, offset)


__all__ = [
    "AyahStatistic", "DEFAULT_LIMIT", "FrequencyResult", "FrequencyRow", "MAX_LIMIT", "MorphologyAnalyticsFilter",
    "MorphologyAnalyticsService", "MorphologySummary", "SegmentDistributionRow", "StatisticsResult", "SurahStatistic",
]
