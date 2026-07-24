"""Non-persistent annotation-source contracts and capability boundaries."""

from quran_analysis.annotation_sources.catalog import (
    CapabilityAssessment,
    CapabilityEvaluationStatus,
    CatalogSource,
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
    valid_lifecycle_transitions,
)
from quran_analysis.annotation_sources.capabilities import (
    AnnotationAdapterRegistry,
    AnnotationCapability,
    AnnotationFrameworkError,
    AnnotationSourceDescriptor,
    IncompatibleLocatorError,
    NoRegisteredAdapterError,
    QACMorphologyV04Adapter,
    SourceSelectionRequiredError,
    UnsupportedCapabilityError,
    UnsupportedDimensionError,
    UnknownAdapterError,
    production_annotation_adapter_registry,
)

__all__ = [
    "CapabilityAssessment", "CapabilityEvaluationStatus", "CatalogSource", "SourceCatalog", "SourceLifecycle",
    "SourceLifecycleError", "get_catalog_source", "guard_source_activation", "guard_source_ingestion",
    "is_valid_lifecycle_transition", "list_active_sources", "list_catalog_sources", "list_deferred_sources",
    "list_unavailable_sources", "production_source_catalog", "valid_lifecycle_transitions",
    "AnnotationAdapterRegistry", "AnnotationCapability", "AnnotationFrameworkError", "AnnotationSourceDescriptor",
    "IncompatibleLocatorError", "NoRegisteredAdapterError", "QACMorphologyV04Adapter",
    "SourceSelectionRequiredError", "UnsupportedCapabilityError", "UnsupportedDimensionError", "UnknownAdapterError",
    "production_annotation_adapter_registry",
]
