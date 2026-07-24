"""Read-only resolution of persisted source releases to explicit adapter contracts."""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import text

from quran_analysis.annotation_sources.capabilities import (
    AnnotationAdapterRegistry, AnnotationCapability, AnnotationSourceDescriptor,
    NoRegisteredAdapterError, SourceSelectionRequiredError, UnsupportedCapabilityError,
    production_annotation_adapter_registry,
)


def source_descriptor(session: Any, source_release_id: int, registry: AnnotationAdapterRegistry | None = None) -> AnnotationSourceDescriptor:
    row = session.execute(text("select id,format,name,version,metadata_json from annotation_source_release where id=:id"), {"id": source_release_id}).mappings().first()
    if row is None:
        raise NoRegisteredAdapterError(f"no registered annotation source release: {source_release_id}", source_release_id=source_release_id)
    metadata = row["metadata_json"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    identity = (metadata or {}).get("source_identity", {})
    adapter_id = identity.get("adapter_identifier", row["format"])
    adapter = (registry or production_annotation_adapter_registry()).get(adapter_id)
    return adapter.descriptor(int(row["id"]), identity.get("source_identifier") or str(row["name"]))


def required_filter_capabilities(filters: Any) -> tuple[AnnotationCapability, ...]:
    mapping = (("root", AnnotationCapability.ROOT), ("lemma", AnnotationCapability.LEMMA),
               ("tag", AnnotationCapability.POS), ("feature", AnnotationCapability.FEATURE_FRAGMENTS),
               ("segment", AnnotationCapability.TOKEN_SEGMENTATION),
               ("alignment_method", AnnotationCapability.TANZIL_TOKEN_ALIGNMENT))
    needed = [capability for field, capability in mapping if getattr(filters, field, None) is not None]
    if any(getattr(filters, field, None) is not None for field in ("surah", "ayah", "token", "segment")):
        needed.append(AnnotationCapability.SOURCE_LOCATOR)
    return tuple(sorted(set(needed), key=lambda value: value.value))


def validate_descriptor(descriptor: AnnotationSourceDescriptor, capabilities: Iterable[AnnotationCapability], *, dimension: str | None = None) -> None:
    for capability in capabilities:
        if capability not in descriptor.capabilities:
            raise UnsupportedCapabilityError(
                f"source release {descriptor.source_release_id} does not support {capability.value}",
                source_release_id=descriptor.source_release_id, adapter_id=descriptor.adapter_id,
                capability=capability, dimension=dimension,
            )


def resolve_query_scope(session: Any, filters: Any, registry: AnnotationAdapterRegistry | None = None,
                        required: Iterable[AnnotationCapability] = ()) -> tuple[AnnotationSourceDescriptor, ...]:
    """Resolve only completed QAC alignment evidence; never silently include other data."""
    registry = registry or production_annotation_adapter_registry()
    selected = getattr(filters, "source_release_id", None)
    if selected is not None:
        descriptors = (source_descriptor(session, selected, registry),)
    else:
        rows = session.execute(text("""
            select distinct qma.annotation_source_release_id
            from qac_morphology_alignment qma
            join qac_alignment_run ar on ar.id=qma.alignment_run_id
            where ar.status='completed'
            order by qma.annotation_source_release_id
        """)).scalars().all()
        descriptors = tuple(source_descriptor(session, int(row), registry) for row in rows)
        if not descriptors:
            raise NoRegisteredAdapterError("no registered adapter has completed queryable alignment evidence")
        if len({descriptor.adapter_id for descriptor in descriptors}) > 1:
            raise SourceSelectionRequiredError("mixed annotation adapters require explicit source_release_id")
    needed = tuple(required) + required_filter_capabilities(filters)
    for descriptor in descriptors:
        validate_descriptor(descriptor, needed)
    return descriptors
