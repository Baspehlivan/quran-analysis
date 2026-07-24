# architecture

Phase 1 neutral, auditable implementation notes. Raw source bytes are immutable. Derived processes must preserve provenance and avoid claims or hard-coded analytical counts.

The read-only source lifecycle catalog is intentionally independent of database release records; see [source-lifecycle.md](source-lifecycle.md). Catalog discovery or lifecycle state never implies registration, ingestion, or activation of an artifact.

Phase 5B aggregation is an outer read-only adapter over the Phase 5A predicate AST and the Phase 4B capability resolver. Source dependencies point inward: CLI and SQL composition invoke immutable public value models; no ORM model escapes. Aggregate/set/cooccurrence results are not schema objects and are never persisted. A morphological **segment** is one source-native subdivision; an annotation **record** can contain analyses and segments; a canonical **token** is Tanzil orthography; an **ayah** owns canonical tokens. These are deliberately different count units, not aliases. See [research-aggregation.md](research-aggregation.md).

Phase 5C adds a final read-only verification adapter. Golden specifications and generated snapshot
comparison live outside the database. Manifest and certificate payloads are canonical immutable
values printed by the CLI; they are not new persistence models. The verification adapter observes
an ordered eleven-table count vector before and after its work to enforce its no-write
boundary: `source_release`, `text_unit`, `orthographic_token`,
`annotation_source_release`, `annotation_source_record`, `morphological_analysis`,
`morphological_segment`, `qac_alignment_run`, `qac_morphology_alignment`,
`analysis_run`, and `analysis_evidence`.
