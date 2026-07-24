# Phase 4A Evidence Report — Morphology Analytics & Corpus Statistics

## 1. Scope and boundary

Phase 4A adds read-only aggregate queries over completed `qac_morphology_alignment` evidence. It does not create denormalized tables, materialized views, migrations, or write paths. The public service returns frozen dataclass result models rather than SQLAlchemy objects.

## 2. Shared predicate semantics

`morphology_filter_predicates` is the single Phase 3B/4A predicate builder. It supplies the same completed-alignment, non-unmatched, source-release, surah, ayah, root, lemma, tag, feature, and alignment-method semantics to occurrence and aggregate queries. Feature matching remains an exact JSON-array fragment comparison. Root and lemma resolve source-native `ROOT`/`LEM` fragments when the legacy dedicated columns are null.

## 3. Public API

`MorphologyAnalyticsService` exposes `summary`, `root_frequency`, `lemma_frequency`, `tag_frequency`, `feature_frequency`, `surah_statistics`, `ayah_statistics`, `segment_distribution`, and `alignment_statistics`; source-release and parser-status distributions are also available. Results expose explicit `aligned_segment_count`, `tanzil_token_count`, `ayah_count`, `source_record_count`, and `alignment_record_count` units. No segment count is labelled as words.

## 4. CLI

`quran morphology stats` provides `summary`, `roots`, `lemmas`, `tags`, `features`, `surahs`, `ayahs`, and `segments`. Each accepts the specified common filters, bounded `--limit`/`--offset`, and `--format text|json`. Aggregate ordering is deterministic: count descending with stable ascending dimension tie-breakers; segment buckets are ascending.

## 5. Controlled and DB-backed tests

`tests/test_phase4a_analytics.py` covers frozen/validated filters, serialization, every aggregate family, deterministic repeat calls, DB-side pagination, filtering, and read-only row-count invariance. Its DB-backed check uses the completed local QAC alignment when available and otherwise skips without changing data.

## 6. Real QAC bounded results

Completed source release 3 produced: summary `128219` aligned segments, `77429` Tanzil tokens, `6236` ayahs, and `128219` source records. Top roots: `Alh` 2851, `qwl` 1722, `kwn` 1390. Top lemmas: `min` 3226, `{ll~ah` 2699, `maA` 2565. Top tags: `N` 25136, `PRON` 24685, `V` 19356. Top features: `STEM` 77915, `PREFIX` 28670, `POS:N` 25136. The largest surah result is 2: 10243 segments, 6116 Tanzil tokens, 286 ayahs. The leading segment/token buckets are 1 segment: 35336 tokens and 2 segments: 34180 tokens.

## 7. SQL plan inspection

A representative bounded top-root `EXPLAIN (costs false)` used a parallel sequential scan of `qac_morphology_alignment`, hash join to the completed alignment run, primary-key index scans for segment and analysis rows, and an index-only source-record lookup. This is appropriate for the whole-corpus aggregate scan; existing lookup indexes remain sufficient. No new index was added because the plan supplied no measured need for one.

## 8. Determinism and read-only evidence

Immediately before and after running all aggregate methods twice, row counts were identical: `annotation_source_record=128292`, `morphological_analysis=128318`, `morphological_segment=128318`, `qac_morphology_alignment=128219`. Both result sequences were byte-for-byte equivalent at the public dictionary level. `quran validate 1` also confirmed byte-identical source reconstruction.

## 9. Validation gates

`docker compose ps` reported PostgreSQL healthy; `alembic current` reported `202607240004 (head)`; `ruff check .` and `mypy src` passed. `pytest -q` passed: 58 tests. `quran validate 1` passed. Phase 3B occurrence smoke (`quran morphology find --source-release-id 3 --limit 1 --format json`) passed. Phase 4A text and JSON CLI smokes passed.

## 10. Change hygiene

No commit was created. Existing dirty/untracked Phase 3 changes were preserved. The Phase 4A implementation is limited to the analytics API, shared predicate extraction, CLI statistics commands, their test, and this evidence record.
