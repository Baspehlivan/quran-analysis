"""TEST-ONLY synthetic adapter; it is deliberately absent from production registry."""
from __future__ import annotations

from dataclasses import dataclass

from quran_analysis.annotation_sources.capabilities import AnnotationCapability, AnnotationSourceDescriptor


@dataclass(frozen=True)
class SyntheticPosAlignmentAdapter:
    adapter_id: str = "synthetic-pos-alignment-test-v1"
    version: str = "1"
    capabilities: tuple[AnnotationCapability, ...] = tuple(sorted((
        AnnotationCapability.MORPHOLOGY, AnnotationCapability.POS,
        AnnotationCapability.TANZIL_TOKEN_ALIGNMENT, AnnotationCapability.FREQUENCY_ANALYTICS,
    ), key=lambda value: value.value))
    queryable_dimensions: tuple[str, ...] = ("alignment_method", "tag")
    aggregatable_dimensions: tuple[str, ...] = ("alignment_method", "tag")
    locator_type: str | None = None

    def supports(self, capability: AnnotationCapability) -> bool:
        return capability in self.capabilities

    def descriptor(self, source_release_id: int, source_identifier: str | None = None) -> AnnotationSourceDescriptor:
        return AnnotationSourceDescriptor(source_release_id, source_identifier or self.adapter_id, self.adapter_id,
            self.version, "synthetic-test-only", self.capabilities, True, self.queryable_dimensions,
            self.aggregatable_dimensions, self.locator_type)
