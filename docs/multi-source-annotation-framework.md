# Phase 4B — Multi-Source Annotation Framework

## Boundary and registry

Phase 4B introduces an in-memory, deterministic `AnnotationAdapterRegistry`. It has `register`, `get`, and sorted `list` operations, rejects duplicate and unknown adapter IDs, and is deliberately easy to construct per test. The production registry contains only `qac-morphology-v0.4`; importing the registry does not register, parse, ingest, download, or align data.

Capabilities are immutable `AnnotationCapability` values: `MORPHOLOGY`, `ROOT`, `LEMMA`, `POS`, `FEATURE_FRAGMENTS`, `TOKEN_SEGMENTATION`, `SOURCE_LOCATOR`, `TANZIL_TOKEN_ALIGNMENT`, `PARSER_STATUS`, and `FREQUENCY_ANALYTICS`. The immutable source descriptor is adapter-derived at read time. It includes release ID, source and adapter identity/version/type, sorted capabilities, alignment availability, dimensions, and locator type. Therefore no migration or capability-state table is needed.

`quran annotation-source capabilities SOURCE_RELEASE_ID --format text|json` is read-only and reports that descriptor. Unknown sources/adapters, unsupported capabilities/dimensions, absent adapters, mixed unselected scopes, and incompatible locators use serializable structured framework errors. CLI framework errors are JSON on stderr and exit nonzero.

## QAC source-native contract

The QAC adapter owns only the QAC boundary: native `ROOT`, `LEM`, `TAG`, ordered literal `FEATURES` fragments, parenthesized four-part locator, segment semantics, parser status, direct Tanzil evidence, and its declared query/aggregate dimensions. These remain source-native values; the generic layer does not reinterpret them.

Parsing remains in `qac_v04.py`, metadata registration in `registration.py`, persistence in `ingestion.py`, and alignment evidence in `alignment.py`. The adapter boundary does not import or invoke those operations. Existing QAC tables remain because they are immutable provenance/payload/alignment evidence, while a capability descriptor is static derived behavior—not data to persist. No QAC table was renamed, migrated, duplicated, or cosmetically replaced.

## Query and analytics capability resolution

The shared Phase 3B predicate set is retained. Capability validation maps root to `ROOT`, lemma to `LEMMA`, tag to `POS`, feature to `FEATURE_FRAGMENTS`, locator coordinates to `SOURCE_LOCATOR`, segment to `TOKEN_SEGMENTATION`, and alignment method to `TANZIL_TOKEN_ALIGNMENT`. Phase 4A root/lemma/tag/feature frequencies and segment/alignment analytics similarly require their declared capabilities. A no-source request resolves only completed, registered, capable QAC evidence and publishes its effective source-release IDs in occurrence JSON. Multiple adapter kinds require explicit selection rather than implicit mixed aggregation.

## Future adapters and synthetic policy

A future adapter must implement the small identity/capability/source-native descriptor protocol, declare only capabilities it can prove, preserve its own native payload and locator semantics, and add query/analytics adapters without coupling parsing, registration, ingestion, or alignment. It must not add generic persistence merely to advertise static capabilities.

`annotation_sources.testing.SyntheticPosAlignmentAdapter` is TEST-ONLY and never registered in production. It intentionally exposes only POS, Tanzil alignment, morphology, and frequency analytics, proving capability rejection for root, lemma, features, source locator, and segmentation. It is not a real corpus and does not persist or download any dataset.
