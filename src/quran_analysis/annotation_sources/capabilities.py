"""Explicit, non-persistent annotation adapter capability contracts.

Adapters describe source-native semantics.  Registration, parsing, ingestion and
alignment remain separate modules and are never triggered by importing this one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Protocol


class AnnotationCapability(str, Enum):
    MORPHOLOGY = "MORPHOLOGY"
    ROOT = "ROOT"
    LEMMA = "LEMMA"
    POS = "POS"
    FEATURE_FRAGMENTS = "FEATURE_FRAGMENTS"
    TOKEN_SEGMENTATION = "TOKEN_SEGMENTATION"
    SOURCE_LOCATOR = "SOURCE_LOCATOR"
    TANZIL_TOKEN_ALIGNMENT = "TANZIL_TOKEN_ALIGNMENT"
    PARSER_STATUS = "PARSER_STATUS"
    FREQUENCY_ANALYTICS = "FREQUENCY_ANALYTICS"


class AnnotationFrameworkError(ValueError):
    code = "annotation_framework_error"

    def __init__(self, message: str, *, source_release_id: int | None = None, adapter_id: str | None = None,
                 capability: AnnotationCapability | None = None, dimension: str | None = None) -> None:
        super().__init__(message)
        self.source_release_id = source_release_id
        self.adapter_id = adapter_id
        self.capability = capability
        self.dimension = dimension

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "source_release_id": self.source_release_id,
                "adapter_id": self.adapter_id, "capability": self.capability.value if self.capability else None,
                "dimension": self.dimension}


class UnknownAdapterError(AnnotationFrameworkError):
    code = "unknown_adapter"


class UnsupportedCapabilityError(AnnotationFrameworkError):
    code = "unsupported_capability"


class UnsupportedDimensionError(AnnotationFrameworkError):
    code = "unsupported_dimension"


class NoRegisteredAdapterError(AnnotationFrameworkError):
    code = "no_registered_adapter"


class SourceSelectionRequiredError(AnnotationFrameworkError):
    code = "source_selection_required"


class IncompatibleLocatorError(AnnotationFrameworkError):
    code = "incompatible_locator"


@dataclass(frozen=True)
class AnnotationSourceDescriptor:
    source_release_id: int
    source_identifier: str
    adapter_id: str
    adapter_version: str
    source_type: str
    capabilities: tuple[AnnotationCapability, ...]
    alignment_available: bool
    queryable_dimensions: tuple[str, ...]
    aggregatable_dimensions: tuple[str, ...]
    locator_type: str | None

    def __post_init__(self) -> None:
        if self.source_release_id < 1:
            raise ValueError("source_release_id must be positive")
        if not all((self.source_identifier, self.adapter_id, self.adapter_version, self.source_type)):
            raise ValueError("descriptor identity fields must be non-empty")
        if self.capabilities != tuple(sorted(set(self.capabilities), key=lambda value: value.value)):
            raise ValueError("capabilities must be unique and sorted by stable capability value")
        if self.queryable_dimensions != tuple(sorted(set(self.queryable_dimensions))):
            raise ValueError("queryable_dimensions must be unique and sorted")
        if self.aggregatable_dimensions != tuple(sorted(set(self.aggregatable_dimensions))):
            raise ValueError("aggregatable_dimensions must be unique and sorted")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = [capability.value for capability in self.capabilities]
        return value


class AnnotationAdapter(Protocol):
    """Small public boundary for identity, source-native access and capabilities."""

    adapter_id: str
    version: str
    capabilities: tuple[AnnotationCapability, ...]
    queryable_dimensions: tuple[str, ...]
    aggregatable_dimensions: tuple[str, ...]
    locator_type: str | None

    def descriptor(self, source_release_id: int, source_identifier: str | None = None) -> AnnotationSourceDescriptor: ...

    def supports(self, capability: AnnotationCapability) -> bool: ...


@dataclass(frozen=True)
class QACMorphologyV04Adapter:
    """QAC's native ROOT/LEM, TAG and ordered FEATURES-fragment contract."""

    adapter_id: str = "qac-morphology-v0.4"
    version: str = "0.4"
    capabilities: tuple[AnnotationCapability, ...] = tuple(sorted((
        AnnotationCapability.MORPHOLOGY, AnnotationCapability.ROOT, AnnotationCapability.LEMMA,
        AnnotationCapability.POS, AnnotationCapability.FEATURE_FRAGMENTS,
        AnnotationCapability.TOKEN_SEGMENTATION, AnnotationCapability.SOURCE_LOCATOR,
        AnnotationCapability.TANZIL_TOKEN_ALIGNMENT, AnnotationCapability.PARSER_STATUS,
        AnnotationCapability.FREQUENCY_ANALYTICS,
    ), key=lambda value: value.value))
    queryable_dimensions: tuple[str, ...] = ("alignment_method", "ayah", "feature", "lemma", "root", "segment", "surah", "tag", "token")
    aggregatable_dimensions: tuple[str, ...] = ("alignment_method", "ayah", "feature", "lemma", "parser_status", "root", "segment", "source_release", "surah", "tag")
    locator_type: str | None = "qac-parenthesized-surah-ayah-token-segment-v0.4"

    def supports(self, capability: AnnotationCapability) -> bool:
        return capability in self.capabilities

    def descriptor(self, source_release_id: int, source_identifier: str | None = None) -> AnnotationSourceDescriptor:
        return AnnotationSourceDescriptor(source_release_id, source_identifier or self.adapter_id, self.adapter_id,
            self.version, "user-local-dataset", self.capabilities, True, self.queryable_dimensions,
            self.aggregatable_dimensions, self.locator_type)


class AnnotationAdapterRegistry:
    """Deterministic registry; instances are isolated to make tests independent."""

    def __init__(self, adapters: tuple[AnnotationAdapter, ...] = ()) -> None:
        self._adapters: dict[str, AnnotationAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: AnnotationAdapter) -> None:
        if adapter.adapter_id in self._adapters:
            raise ValueError(f"duplicate annotation adapter: {adapter.adapter_id}")
        self._adapters[adapter.adapter_id] = adapter

    def get(self, adapter_id: str) -> AnnotationAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise UnknownAdapterError(f"unknown annotation adapter: {adapter_id}", adapter_id=adapter_id) from exc

    def list(self) -> tuple[AnnotationAdapter, ...]:
        return tuple(self._adapters[key] for key in sorted(self._adapters))


_PRODUCTION_REGISTRY = AnnotationAdapterRegistry((QACMorphologyV04Adapter(),))


def production_annotation_adapter_registry() -> AnnotationAdapterRegistry:
    """Return the intentionally small production registry (QAC only in Phase 4B)."""
    return _PRODUCTION_REGISTRY
