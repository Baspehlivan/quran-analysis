# Phase 3A morphology layer

This document covers the generic, provenance-preserving morphology annotation layer. Annotation sources are never authoritative Quran text; the registered Tanzil source remains the only authoritative Quran text and Phase 1 byte-identical reconstruction must be preserved.

Phase 3A stores source-native annotation records exactly, parses derived payloads separately, aligns to Tanzil tokens with explicit evidence, and preserves uncertainty, ambiguity, partial matches, unaligned rows, malformed rows, unknown rows, and conflicts. It does not implement morphology frequencies, root/lemma counts, semantic search, embeddings, abjad, theological/numerological claims, expected frequencies, verse-specific logic, or Phase 3B search/counting.

Synthetic fixture format `synthetic-qac-tsv-v1` is QAC-concept-inspired for tests only and is not an official QAC importer. External annotation sources are annotation only. Real QAC v0.4 is not downloaded, committed, or ingested because official downloadable QAC/GPLv3 text conflicts with FAQ language about non-commercial / purely research use; license and redistribution must be clarified first.

Source-native fields and derived fields are distinct. Parser, transliteration, feature mapping, alignment configurations are frozen and content-hashed. Hash algorithms are `morphology-record-hash-v1`, `morphology-analysis-hash-v1`, `morphology-segment-hash-v1`, `morphology-alignment-hash-v1`, and `morphology-ingestion-hash-v1`, over canonical JSON excluding DB row ids, output paths, timestamps, and terminal formatting.

Alignment stages: locator parse; exact surface match to authoritative raw token; optional named neutral normalization profiles (`identity_v1`, `remove_combining_marks_v1`); segment-aware offsets; bounded candidate search only in the addressed ayah; unresolved classification. Ambiguous matches are never resolved by choosing the first candidate. Basmala and locator handling are explicit through stored external locator and parsed locator fields.

Exports write JSON/JSONL/CSV with manifests and verification by SHA-256. Validation checks stored raw copy byte identity, reconstruction from preserved records, ingestion integrity counts, and tamper detection. Conflict records remain preserved rather than repaired or merged.
