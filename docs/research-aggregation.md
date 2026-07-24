# Phase 5B research aggregation

Phase 5B adds a read-only aggregate boundary over the immutable Phase 5A `ResearchQuery` predicate AST. It never creates a migration, table, source, alignment, analysis run, evidence record, or persisted result.

## Units and metrics

Every aggregate has an explicit unit: `MATCH_ROW`, `CANONICAL_TOKEN`, `CANONICAL_AYAH`, `CANONICAL_SURAH`, `ANNOTATION_RECORD`, `MORPHOLOGICAL_ANALYSIS`, `MORPHOLOGICAL_SEGMENT`, or `SOURCE_NATIVE_RECORD`. Counts are `count(distinct stable_database_identifier)`; labels and concatenated coordinates are never used for distinctness. `COUNT`, `COUNT_DISTINCT`, and `FREQUENCY` are supported. `MIN` and `MAX` are rejected because they do not express a stable count semantic.

Groups are bounded to three native dimensions: surah, ayah, source-native root/lemma/POS/feature, release, alignment method, parser status, canonical raw token text, and raw segment text. Ordering is metric then canonical group key and all paging is database-side.

## Sets and cooccurrence

Set operands are complete research queries with an explicit canonical token, ayah, or surah identity. They report left/right/result/overlap cardinalities and stable IDs. Empty operands follow normal SQL set semantics. Set and cooccurrence pages include at most `evidence_samples` (0–20) representative raw evidence objects, ordered first by canonical stable ID and then source evidence IDs; each retains canonical coordinates/raw token, annotation record/raw line, source-native payload/locator, alignment, and source-release provenance.

Cooccurrence supports only `SAME_AYAH` and canonical-token identity. `UNIQUE_TOKEN_PAIRS` deduplicates stable token pairs; `ALL_CROSS_PRODUCT_PAIRS` retains the product of already-deduplicated left/right token occurrences. Results name the policy, pair cardinality, distinct ayahs and surahs; no distance/window assertion is made.

## Scope, provenance and explain

Completed alignment and Phase 4B adapter resolution are required. Unsupported units/dimensions/capabilities and non-comparable mixed scopes return structured errors, not zero values. Raw source-native root/lemma/POS and evidence are never normalized. Existing normalization profiles remain explicit Phase 5A predicates and metadata says that no implicit normalization occurred.

`quran research aggregate|set|cooccurrence|explain` accepts inline JSON or `--query-file` JSON/YAML and emits text, JSON, or YAML. Explain exposes canonical/optimized logical request, capabilities, stages and dedup identity, never connection strings or SQL by default. Canonical hashes exclude execution time and duration.

Phase 4A comparisons are meaningful only when source scope, completed-alignment predicate, unit, distinct identity, and group dimension are exactly the same; Phase 5B intentionally differs where those semantics differ.

## Phase 5C contract lock

Phase 5C verifies this documented contract rather than changing aggregation semantics: a mixed
explicit source scope is rejected, ordering is stable as documented above, and all benchmark,
golden, manifest and certificate operations are in-memory/read-only.
