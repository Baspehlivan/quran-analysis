from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from quran_analysis.annotation_sources.capabilities import (
    AnnotationAdapterRegistry, AnnotationCapability, QACMorphologyV04Adapter,
    UnsupportedCapabilityError, UnknownAdapterError, production_annotation_adapter_registry,
)
from quran_analysis.annotation_sources.service import required_filter_capabilities, validate_descriptor
from quran_analysis.annotation_sources.testing import SyntheticPosAlignmentAdapter
from quran_analysis.morphology.analytics import MorphologyAnalyticsFilter
from quran_analysis.morphology.query import MorphologyQuery


def test_registry_is_isolated_deterministic_and_production_has_only_qac():
    registry = AnnotationAdapterRegistry((SyntheticPosAlignmentAdapter(), QACMorphologyV04Adapter()))
    assert [adapter.adapter_id for adapter in registry.list()] == ["qac-morphology-v0.4", "synthetic-pos-alignment-test-v1"]
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(QACMorphologyV04Adapter())
    with pytest.raises(UnknownAdapterError) as error:
        registry.get("missing")
    assert error.value.to_dict()["code"] == "unknown_adapter"
    assert [adapter.adapter_id for adapter in production_annotation_adapter_registry().list()] == ["qac-morphology-v0.4"]


def test_immutable_sorted_descriptors_and_synthetic_capability_rejection():
    descriptor = SyntheticPosAlignmentAdapter().descriptor(9)
    assert descriptor.to_dict()["capabilities"] == ["FREQUENCY_ANALYTICS", "MORPHOLOGY", "POS", "TANZIL_TOKEN_ALIGNMENT"]
    with pytest.raises(FrozenInstanceError):
        descriptor.adapter_id = "changed"  # type: ignore[misc]
    validate_descriptor(descriptor, (AnnotationCapability.POS, AnnotationCapability.TANZIL_TOKEN_ALIGNMENT))
    with pytest.raises(UnsupportedCapabilityError) as error:
        validate_descriptor(descriptor, (AnnotationCapability.ROOT,), dimension="root")
    assert error.value.to_dict()["capability"] == "ROOT"
    assert error.value.to_dict()["dimension"] == "root"


def test_shared_filter_capability_mapping_preserves_qac_filter_contract():
    query = MorphologyQuery(root="qwl", tag="V", feature="POS:V", segment=1)
    assert required_filter_capabilities(query) == (
        AnnotationCapability.FEATURE_FRAGMENTS, AnnotationCapability.POS, AnnotationCapability.ROOT,
        AnnotationCapability.SOURCE_LOCATOR, AnnotationCapability.TOKEN_SEGMENTATION,
    )
    assert required_filter_capabilities(MorphologyAnalyticsFilter(lemma="qwl")) == (AnnotationCapability.LEMMA,)
