# Source lifecycle catalog

## Boundary

The source lifecycle catalog is a read-only, in-memory catalog of source identities. It is independent of `annotation_source_release` and `source_release` database rows: a catalog entry does not assert that any release is registered, and a registered release does not by itself alter catalog state. Constructing, listing, serializing, filtering, or guarding the catalog never downloads, registers, parses, ingests, aligns, or writes data.

Entries are frozen values and serialization is deterministic by source identifier. `SourceCatalog` instances are isolated so tests and callers can supply their own entries without modifying a process-wide catalog.

## States and transitions

Lifecycle values are `DISCOVERED`, `UNDER_REVIEW`, `AVAILABLE`, `REGISTERED`, `INGESTED`, `ACTIVE`, `DEFERRED`, `UNAVAILABLE`, `UNSUPPORTED`, and `RETIRED`.

The normal evidence path is:

`DISCOVERED -> UNDER_REVIEW -> AVAILABLE -> REGISTERED -> INGESTED -> ACTIVE`.

At discovery/review/availability/registration/ingestion stages an entry may instead become `DEFERRED`, `UNAVAILABLE`, `UNSUPPORTED`, or `RETIRED`. `ACTIVE` may become one of those non-active states. `DEFERRED`, `UNAVAILABLE`, and `UNSUPPORTED` may return only to `UNDER_REVIEW` when new evidence exists, or become `RETIRED`; `RETIRED` has no outgoing transition. `CatalogSource.transitioned()` validates this table and returns a new frozen entry rather than changing an existing one.

`DEFERRED` means work is deliberately postponed; `UNAVAILABLE` means the official artifact cannot currently be obtained or inspected; `UNSUPPORTED` means inspected evidence rules out supported integration; and `RETIRED` ends catalog consideration. None of these states silently becomes a registration or an ingestion result.

## Discovery, provenance, audit, registration, and ingestion

Discovery records only established identity and official access information. Under review, provenance and artifact-level license/terms are audited before availability is asserted. `REGISTERED` and `INGESTED` are lifecycle concepts, not actions performed by this catalog; actual releases and ingestion evidence remain in their existing database-backed workflows. `ACTIVE` identifies a production catalog source, not a particular database release.

Capability assessments use separate statuses: `SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`, and `NOT_EVALUATED`. They are not lifecycle states. In particular, a source whose official artifact is unavailable has `UNKNOWN` capability assessments: publication or web-page advertising is not artifact proof.

## Current production catalog

- `tanzil-text-with-ayah-numbers-v1` is `ACTIVE` and remains the project’s authoritative Quran text source.
- `qac-morphology-v0.4` is `ACTIVE` as an external, source-native annotation source. Its catalog record is not a license assertion for any local release.
- `quranmorph` is `UNAVAILABLE`. Per `docs/quranmorph-source-audit.md`, its known institution is SinaLab, Birzeit University; official access is a manual institutional approval mechanism; no official artifact was available. It has no registration, parser, ingestion, alignment, release row, or production adapter, and Phase 4C is NOT READY.

## Guards and CLI

`guard_source_activation` and `guard_source_ingestion` are reusable read-only boundaries for future commands. They reject an unavailable source with serializable `source_lifecycle_blocked` data including source identifier, lifecycle, operation, and the official-artifact-unavailable reason. They do not activate or ingest anything.

`quran annotation-source catalog --format text|json` lists catalog entries. `quran annotation-source show SOURCE --format text|json` shows one catalog entry; lifecycle is presented prominently in text output. `quran annotation-source lifecycle-guard SOURCE --operation activation|ingestion` exposes only the read-only guard and exits nonzero with its structured error when blocked. The existing `capabilities` command remains release/adapter-derived and is intentionally distinct from catalog capability assessments.
