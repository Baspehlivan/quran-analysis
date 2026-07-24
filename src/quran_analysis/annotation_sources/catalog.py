"""Read-only, deterministic source lifecycle catalog.

Catalog entries describe known source identities, not database releases.  Constructing or
querying a catalog never registers, downloads, parses, ingests, aligns, or writes data.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from quran_analysis.annotation_sources.capabilities import AnnotationCapability


class SourceLifecycle(str, Enum):
    DISCOVERED = "DISCOVERED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AVAILABLE = "AVAILABLE"
    REGISTERED = "REGISTERED"
    INGESTED = "INGESTED"
    ACTIVE = "ACTIVE"
    DEFERRED = "DEFERRED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    RETIRED = "RETIRED"


class CapabilityEvaluationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    NOT_EVALUATED = "NOT_EVALUATED"


_VALID_TRANSITIONS: dict[SourceLifecycle, frozenset[SourceLifecycle]] = {
    SourceLifecycle.DISCOVERED: frozenset({SourceLifecycle.UNDER_REVIEW, SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.UNDER_REVIEW: frozenset({SourceLifecycle.AVAILABLE, SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.AVAILABLE: frozenset({SourceLifecycle.REGISTERED, SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.REGISTERED: frozenset({SourceLifecycle.INGESTED, SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.INGESTED: frozenset({SourceLifecycle.ACTIVE, SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.ACTIVE: frozenset({SourceLifecycle.DEFERRED, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.DEFERRED: frozenset({SourceLifecycle.UNDER_REVIEW, SourceLifecycle.UNAVAILABLE, SourceLifecycle.UNSUPPORTED, SourceLifecycle.RETIRED}),
    SourceLifecycle.UNAVAILABLE: frozenset({SourceLifecycle.UNDER_REVIEW, SourceLifecycle.RETIRED}),
    SourceLifecycle.UNSUPPORTED: frozenset({SourceLifecycle.UNDER_REVIEW, SourceLifecycle.RETIRED}),
    SourceLifecycle.RETIRED: frozenset(),
}


def valid_lifecycle_transitions(lifecycle: SourceLifecycle) -> frozenset[SourceLifecycle]:
    """Return the explicit immutable transition set for a lifecycle state."""
    return _VALID_TRANSITIONS[lifecycle]


def is_valid_lifecycle_transition(current: SourceLifecycle, target: SourceLifecycle) -> bool:
    return target in valid_lifecycle_transitions(current)


@dataclass(frozen=True)
class CapabilityAssessment:
    capability: AnnotationCapability
    status: CapabilityEvaluationStatus
    note: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"capability": self.capability.value, "status": self.status.value, "note": self.note}


@dataclass(frozen=True)
class CatalogSource:
    source_identifier: str
    official_name: str
    institution: str | None
    website: str | None
    publication: str | None
    official_acquisition: str | None
    license_summary: str | None
    lifecycle: SourceLifecycle
    acquisition_requirements: tuple[str, ...]
    capability_assessments: tuple[CapabilityAssessment, ...]
    notes: tuple[str, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_identifier or not self.official_name:
            raise ValueError("catalog source identity fields must be non-empty")
        capabilities = tuple(item.capability.value for item in self.capability_assessments)
        if capabilities != tuple(sorted(set(capabilities))):
            raise ValueError("capability assessments must be unique and sorted by capability")
        for field_name in ("acquisition_requirements", "notes", "provenance"):
            value = getattr(self, field_name)
            if any(not item for item in value):
                raise ValueError(f"{field_name} cannot contain empty values")

    def transitioned(self, lifecycle: SourceLifecycle) -> "CatalogSource":
        """Return a new entry after a valid lifecycle change; never mutate this entry."""
        if not is_valid_lifecycle_transition(self.lifecycle, lifecycle):
            raise ValueError(f"invalid source lifecycle transition: {self.lifecycle.value} -> {lifecycle.value}")
        return replace(self, lifecycle=lifecycle)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identifier": self.source_identifier,
            "official_name": self.official_name,
            "institution": self.institution,
            "website": self.website,
            "publication": self.publication,
            "official_acquisition": self.official_acquisition,
            "license_summary": self.license_summary,
            "lifecycle": self.lifecycle.value,
            "acquisition_requirements": list(self.acquisition_requirements),
            "capability_assessments": [item.to_dict() for item in self.capability_assessments],
            "notes": list(self.notes),
            "provenance": list(self.provenance),
        }


class SourceLifecycleError(ValueError):
    code = "source_lifecycle_blocked"

    def __init__(self, source: CatalogSource, operation: str) -> None:
        message = f"{operation} is not permitted for source {source.source_identifier} in lifecycle {source.lifecycle.value}"
        if source.lifecycle is SourceLifecycle.UNAVAILABLE:
            message += "; official artifact unavailable"
        super().__init__(message)
        self.source_identifier = source.source_identifier
        self.lifecycle = source.lifecycle
        self.operation = operation

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": str(self),
            "source_identifier": self.source_identifier,
            "lifecycle": self.lifecycle.value,
            "operation": self.operation,
        }


def guard_source_activation(source: CatalogSource) -> None:
    """Future activation boundary; this guard performs no activation or write."""
    if source.lifecycle is not SourceLifecycle.INGESTED:
        raise SourceLifecycleError(source, "activation")


def guard_source_ingestion(source: CatalogSource) -> None:
    """Future ingestion boundary; this guard performs no ingestion or write."""
    if source.lifecycle is not SourceLifecycle.REGISTERED:
        raise SourceLifecycleError(source, "ingestion")


class SourceCatalog:
    """Isolated immutable catalog collection with deterministic identifier ordering."""

    def __init__(self, entries: Iterable[CatalogSource] = ()) -> None:
        values = tuple(sorted(entries, key=lambda entry: entry.source_identifier))
        if len({entry.source_identifier for entry in values}) != len(values):
            raise ValueError("duplicate catalog source identifier")
        self._entries = values

    def list(self) -> tuple[CatalogSource, ...]:
        return self._entries

    def get(self, source_identifier: str) -> CatalogSource:
        for entry in self._entries:
            if entry.source_identifier == source_identifier:
                return entry
        raise KeyError(source_identifier)

    def filter(self, lifecycle: SourceLifecycle) -> tuple[CatalogSource, ...]:
        return tuple(entry for entry in self._entries if entry.lifecycle is lifecycle)


def _assessments(status: CapabilityEvaluationStatus, note: str | None = None) -> tuple[CapabilityAssessment, ...]:
    return tuple(CapabilityAssessment(capability, status, note) for capability in sorted(AnnotationCapability, key=lambda value: value.value))


def production_source_catalog() -> SourceCatalog:
    """Build the static production catalog without consulting database release rows."""
    return SourceCatalog((
        CatalogSource(
            "qac-morphology-v0.4", "Quranic Arabic Corpus Morphology", None, None, None,
            "Local, user-provided QAC v0.4 artifact.",
            "Not catalogued; acquisition terms must be captured before registration.",
            SourceLifecycle.ACTIVE,
            ("Capture source metadata and integrity fingerprints before registration.",),
            _assessments(CapabilityEvaluationStatus.SUPPORTED, "Declared by the existing QAC v0.4 adapter contract."),
            ("External annotation data; Tanzil remains the authoritative Quran text source.",),
            ("docs/qac-local-acquisition.md", "docs/multi-source-annotation-framework.md"),
        ),
        CatalogSource(
            "quranmorph", "Quran Corpus (QuranMorph)", "SinaLab, Birzeit University",
            "https://sina.birzeit.edu/quran/",
            "Diyam Akra, Tymaa Hammouda, Mustafa Jarrar, The Quran Corpus: Lemmatization and POS Tagging, Technical Report, Birzeit University, 2025.",
            "Institutional manual approval through the official Google Form; no direct artifact URL was published.",
            "Website catalogue label advertises CC-BY-4.0; corpus-data license/terms are unresolved without the official artifact or delivery terms.",
            SourceLifecycle.UNAVAILABLE,
            ("Obtain the artifact directly from SinaLab/Birzeit through its official access process.", "Preserve received bytes and inspect artifact-level terms before any registration."),
            _assessments(CapabilityEvaluationStatus.UNKNOWN, "No official artifact was available for inspection; advertised claims are not capability proof."),
            ("No registration, parser, ingestion, alignment, or production adapter exists.", "Phase 4C readiness is NOT READY."),
            ("docs/quranmorph-source-audit.md",),
        ),
        CatalogSource(
            "tanzil-text-with-ayah-numbers-v1", "Tanzil Quran Text", "Tanzil Project", "https://tanzil.net/", None,
            "Registered project source; see its preserved source footer and manifest.",
            "See the preserved registered Tanzil source footer/license text.",
            SourceLifecycle.ACTIVE,
            (), (),
            ("Authoritative Quran text source in this project; annotation sources do not replace it.",),
            ("docs/source-policy.md",),
        ),
    ))


def _catalog_or_default(catalog: SourceCatalog | None) -> SourceCatalog:
    return catalog if catalog is not None else production_source_catalog()


def list_catalog_sources(catalog: SourceCatalog | None = None) -> tuple[CatalogSource, ...]:
    return _catalog_or_default(catalog).list()


def get_catalog_source(source_identifier: str, catalog: SourceCatalog | None = None) -> CatalogSource:
    return _catalog_or_default(catalog).get(source_identifier)


def list_active_sources(catalog: SourceCatalog | None = None) -> tuple[CatalogSource, ...]:
    return _catalog_or_default(catalog).filter(SourceLifecycle.ACTIVE)


def list_deferred_sources(catalog: SourceCatalog | None = None) -> tuple[CatalogSource, ...]:
    return _catalog_or_default(catalog).filter(SourceLifecycle.DEFERRED)


def list_unavailable_sources(catalog: SourceCatalog | None = None) -> tuple[CatalogSource, ...]:
    return _catalog_or_default(catalog).filter(SourceLifecycle.UNAVAILABLE)
