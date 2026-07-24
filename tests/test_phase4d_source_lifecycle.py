from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from typer.testing import CliRunner

from quran_analysis.annotation_sources.catalog import (
    SourceCatalog,
    SourceLifecycle,
    SourceLifecycleError,
    get_catalog_source,
    guard_source_activation,
    guard_source_ingestion,
    is_valid_lifecycle_transition,
    list_active_sources,
    list_catalog_sources,
    list_deferred_sources,
    list_unavailable_sources,
    production_source_catalog,
)
from quran_analysis.cli import app


def test_lifecycle_transitions_are_explicit_and_entries_are_immutable():
    entry = get_catalog_source("quranmorph")
    assert is_valid_lifecycle_transition(SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNDER_REVIEW)
    assert not is_valid_lifecycle_transition(SourceLifecycle.UNAVAILABLE, SourceLifecycle.ACTIVE)
    reviewed = entry.transitioned(SourceLifecycle.UNDER_REVIEW)
    assert entry.lifecycle is SourceLifecycle.UNAVAILABLE
    assert reviewed.lifecycle is SourceLifecycle.UNDER_REVIEW
    with pytest.raises(ValueError, match="invalid source lifecycle transition"):
        entry.transitioned(SourceLifecycle.ACTIVE)
    with pytest.raises(FrozenInstanceError):
        entry.lifecycle = SourceLifecycle.ACTIVE  # type: ignore[misc]


def test_catalog_is_serializable_deterministic_and_isolated():
    first = list_catalog_sources()
    second = list_catalog_sources()
    assert [item.source_identifier for item in first] == sorted(item.source_identifier for item in first)
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert get_catalog_source("quranmorph").to_dict()["lifecycle"] == "UNAVAILABLE"
    quranmorph = get_catalog_source("quranmorph")
    assert {item["status"] for item in quranmorph.to_dict()["capability_assessments"]} == {"UNKNOWN"}
    isolated = SourceCatalog((replace(quranmorph, lifecycle=SourceLifecycle.DEFERRED),))
    assert [item.source_identifier for item in list_deferred_sources(isolated)] == ["quranmorph"]
    assert list_unavailable_sources(isolated) == ()
    assert [item.source_identifier for item in list_unavailable_sources()] == ["quranmorph"]
    assert [item.source_identifier for item in list_active_sources()] == ["qac-morphology-v0.4", "tanzil-text-with-ayah-numbers-v1"]
    assert production_source_catalog() is not production_source_catalog()


def test_unavailable_guards_are_structured_and_write_free():
    source = get_catalog_source("quranmorph")
    for guard, operation in ((guard_source_activation, "activation"), (guard_source_ingestion, "ingestion")):
        with pytest.raises(SourceLifecycleError) as error:
            guard(source)
        assert error.value.to_dict() == {
            "code": "source_lifecycle_blocked",
            "message": f"{operation} is not permitted for source quranmorph in lifecycle UNAVAILABLE; official artifact unavailable",
            "source_identifier": "quranmorph",
            "lifecycle": "UNAVAILABLE",
            "operation": operation,
        }


def test_catalog_cli_text_json_and_nonzero_structured_guard_error():
    runner = CliRunner()
    text = runner.invoke(app, ["annotation-source", "catalog", "--format", "text"])
    assert text.exit_code == 0
    assert "LIFECYCLE=UNAVAILABLE" in text.output
    payload = runner.invoke(app, ["annotation-source", "show", "quranmorph", "--format", "json"])
    assert payload.exit_code == 0
    assert '"source_identifier": "quranmorph"' in payload.output
    assert '"lifecycle": "UNAVAILABLE"' in payload.output
    blocked = runner.invoke(app, ["annotation-source", "lifecycle-guard", "quranmorph", "--operation", "ingestion"])
    assert blocked.exit_code == 2
    assert '"code": "source_lifecycle_blocked"' in blocked.output
    assert 'official artifact unavailable' in blocked.output
