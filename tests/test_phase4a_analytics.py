from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from quran_analysis.db.session import get_session_local
from quran_analysis.morphology.analytics import MorphologyAnalyticsFilter, MorphologyAnalyticsService


def test_filters_and_public_results_are_immutable_and_serializable():
    filters = MorphologyAnalyticsFilter(surah=1, feature="POS:N")
    with pytest.raises(FrozenInstanceError):
        filters.surah = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="positive"):
        MorphologyAnalyticsFilter(ayah=0)
    with pytest.raises(ValueError, match="alignment method"):
        MorphologyAnalyticsFilter(alignment_method="invalid")


def test_qac_analytics_aggregates_are_read_only_deterministic_and_paginated():
    """Exercise every aggregate against the optional real QAC alignment fixture."""
    try:
        with get_session_local()() as session:
            if not session.execute(text("select 1 from qac_alignment_run where status='completed' limit 1")).scalar():
                pytest.skip("completed QAC alignment unavailable")
            tables = ("annotation_source_record", "morphological_analysis", "morphological_segment", "qac_morphology_alignment")
            before = {table: session.execute(text(f"select count(*) from {table}")).scalar_one() for table in tables}
            service = MorphologyAnalyticsService(session)
            summary = service.summary()
            assert summary.aligned_segment_count > 0
            assert summary.to_dict()["tanzil_token_count"] > 0
            methods = (
                service.root_frequency, service.lemma_frequency, service.tag_frequency, service.feature_frequency,
                service.source_release_frequency, service.parser_status_frequency, service.alignment_statistics,
            )
            for method in methods:
                first = method(limit=2)
                assert first == method(limit=2)
                assert method(limit=1, offset=1).results == first.results[1:2]
                assert first.to_dict()["limit"] == 2
            assert service.surah_statistics(limit=2) == service.surah_statistics(limit=2)
            assert service.ayah_statistics(limit=2) == service.ayah_statistics(limit=2)
            assert service.segment_distribution(limit=2) == service.segment_distribution(limit=2)
            source_id = service.source_release_frequency(limit=1).results[0].value
            surah = service.surah_statistics(limit=1).results[0].surah
            ayah = service.ayah_statistics(limit=1).results[0]
            filters = (
                {"source_release_id": source_id}, {"surah": surah}, {"surah": ayah.surah, "ayah": ayah.ayah},
                {"root": service.root_frequency(limit=1).results[0].value}, {"lemma": service.lemma_frequency(limit=1).results[0].value},
                {"tag": service.tag_frequency(limit=1).results[0].value}, {"feature": service.feature_frequency(limit=1).results[0].value},
                {"alignment_method": service.alignment_statistics(limit=1).results[0].value},
            )
            assert all(service.summary(MorphologyAnalyticsFilter(**values)).aligned_segment_count > 0 for values in filters)
            assert session.execute(text("select count(*) from qac_morphology_alignment")).scalar_one() == before["qac_morphology_alignment"]
            after = {table: session.execute(text(f"select count(*) from {table}")).scalar_one() for table in tables}
    except OperationalError:
        pytest.skip("PostgreSQL unavailable")
    assert after == before
