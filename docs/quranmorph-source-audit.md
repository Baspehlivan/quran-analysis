# Phase 4C — QuranMorph Source Acquisition Audit and Adapter Specification

## 1. Decision and non-negotiable boundary

**Safety decision: NOT READY.** This is a provenance-first, read-only acquisition audit. QuranMorph was not registered; no database row, migration, source/morphology/alignment evidence, production registry entry, or Tanzil/QAC content was changed. No unofficial mirror, fork, repackage, paper-derived data, or inferred format was downloaded or used.

The official path exposed a manual Google Form rather than a direct corpus artifact. Per the acquisition boundary, acquisition stopped there. Consequently there is no official artifact to inspect, hash, parse, compare, or adapt. This report never turns web-page or paper claims into artifact facts.

## 2. Official discovery evidence

- **Official landing page:** `https://sina.birzeit.edu/quran/`
- **Official resource catalogue:** `https://sina.birzeit.edu/resources/`
- **Advertised name:** landing page: “Quran Corpus”; paper linked by the landing page: “The Quran Corpus: Lemmatization and POS Tagging”; arXiv calls the corpus “QuranMorph”. The relationship is not resolved from an artifact.
- **Advertised publisher:** SinaLab, Birzeit University.
- **Advertised date/version:** landing-page citation says *Technical Report, Birzeit University, 2025*. No corpus release/version or filename is advertised on the landing page.
- **Advertised description:** morphology tagging; every word linked to a Qabas lemma and assigned a POS tag.
- **Website catalogue license label:** the “Classical Arabic” listing displays `CC-BY-4.0` next to “Quran Morphology”. This is web-page metadata only, not an artifact-contained corpus-data license or terms file.
- **Citation as displayed:** Diyam Akra, Tymaa Hammouda, Mustafa Jarrar, *The Quran Corpus: Lemmatization and POS Tagging*, Technical Report, Birzeit University, 2025.
- **Access time:** `2026-07-23T21:30:46Z` UTC.

The official landing page’s only active “Download The Quran Corpus” mechanism links to:

`https://docs.google.com/forms/d/e/1FAIpQLSfBEVT0BWhWhMPtAqGonBjc2uvgcMhSxzRJd44FhUDgb-rOsQ/viewform?usp=header`

No direct artifact URL, filename, release archive, checksum, API, or documented automated corpus delivery protocol was published in the inspected official page source.

## 3. Required manual acquisition action

A human must open the official Google Form above, complete and submit its requested access procedure, and obtain the corpus **directly from SinaLab/Birzeit**. Preserve the received filename and bytes unchanged, including any archive. Do not substitute any third-party copy or reconstruct a dataset from the paper/site.

Only after that action may the untouched received artifact be placed under `data/incoming/quranmorph/<original-filename>`. The existing `.gitignore` ignores `data/incoming/`, so this location is intentionally local-only. At that point record SHA-256, byte size, archive/member hashes, and all supplied notices before any parsing.

## 4. License and citation disposition

The website’s `CC-BY-4.0` label is evidence of an advertised catalogue label, not sufficient evidence of explicit artifact-level corpus-data terms. The audit did not inspect a corpus `LICENSE`, `README`, notice, delivery e-mail terms, download click-through terms, or archive metadata because none was acquired.

Therefore the following remain distinct and unresolved:

| Subject | Status |
|---|---|
| Website catalogue metadata | Advertises `CC-BY-4.0` |
| Corpus-data license/terms | **UNRESOLVED**; artifact/delivery terms not inspected |
| Software/toolkit license | Out of scope; not evidence for corpus data |
| Paper copyright/license | Out of scope; not evidence for corpus data |
| Citation | Advertised landing-page citation recorded above |

Conflicting, absent, non-explicit, or delivery-restricted corpus-data terms are a blocking condition. The current evidence is insufficient, so the corpus is **not eligible for registration or persistence**.

## 5. Artifact chain of custody and integrity

No QuranMorph artifact was downloaded. Accordingly all artifact-specific facts are unavailable rather than zero:

| Evidence | Status |
|---|---|
| Original filename | UNRESOLVED |
| Byte size | UNRESOLVED |
| SHA-256 | UNRESOLVED |
| Container/archive type and compression | UNRESOLVED |
| Archive member names, sizes, SHA-256 | UNRESOLVED |
| Artifact license/README/notices | UNRESOLVED |
| Encoding/BOM/physical line endings | UNRESOLVED |

No artifact bytes were altered, extracted, normalized, decoded into a replacement file, or persisted.

## 6. Real-format audit disposition

A real-format audit requires the official bytes. None was available, so the following are **UNRESOLVED**, not inferred from the publication or web page: delimiter, quoting, header, physical and parsed row counts, blank/comment/malformed/duplicate rows, field order, native values/nulls, field semantics/types/cardinalities, row identity, text versus annotation payload, locator unit, splits/merges, surah/ayah/token/segment/global/Qabas IDs, endpoint/range/gap/duplicate/sort checks, raw lemma/ID alternatives, script, POS inventory, POS delimiter, and tag definitions.

The advertised “77,429 tokens” and “40 tags” from the linked paper are publication claims and deliberately are **not recorded as artifact audit counts or adapter guarantees**.

## 7. Coordinate and surface comparison disposition

No source rows or source surfaces exist locally, so no comparison with canonical Tanzil or QAC can be honestly computed. The following reports are **UNRESOLVED**: source/canonical count overlap; missing/extra/duplicate coordinates; 1:1, 1:N, N:1, splits, merges and ordering divergence; raw surface mismatch samples/categories; `RAW_EXACT`; `REMOVE_COMBINING_MARKS`; and existing semantically appropriate profile comparisons.

Coordinates must remain independent from source surface text. On future acquisition, mismatches must retain both raw source and Tanzil strings; normalization never overwrites either source-native value.

## 8. Parser and CLI decision

No QuranMorph parser, auditor, fixture, test, or CLI was implemented. Implementing one now would infer a format from the paper/site, which is prohibited. In particular, `audit-quranmorph` and `compare-quranmorph PATH --source-release-id 1` were not exposed because no stable, artifact-proven format, row identity, or locator contract exists.

After official artifact inspection establishes a stable format, a DB-free prototype may expose only immutable raw/parsed/issue/report models. It must retain raw physical line/member row, original field order and native values, physical ending, issue list, and hashes; classify `PARSED`, `BLANK`, `COMMENT`, `MALFORMED`, and `UNSUPPORTED_STRUCTURE`; emit deterministic text/JSON; and return nonzero for malformed input or corpus-data license blockers. It must not register, write a database, align, or add a production adapter.

## 9. Artifact-based Phase 4B capability matrix

This is deliberately artifact-based. Because no artifact was inspected, each capability is **UNRESOLVED**, even where the website advertises a related concept.

| Phase 4B capability | Classification | Reason |
|---|---|---|
| MORPHOLOGY | UNRESOLVED | No real rows/fields inspected |
| ROOT | UNRESOLVED | No artifact field inspected |
| LEMMA | UNRESOLVED | Website claim is not artifact verification |
| POS | UNRESOLVED | Website claim is not artifact verification |
| FEATURE_FRAGMENTS | UNRESOLVED | No native feature encoding inspected |
| TOKEN_SEGMENTATION | UNRESOLVED | No token/segment unit inspected |
| SOURCE_LOCATOR | UNRESOLVED | No locator fields or uniqueness inspected |
| TANZIL_TOKEN_ALIGNMENT | UNRESOLVED | No coordinate/surface comparison possible |
| PARSER_STATUS | UNRESOLVED | No stable format to classify |
| FREQUENCY_ANALYTICS | UNRESOLVED | Depends on verified parse/identity/dimensions |

No unsupported conclusion is made before a real artifact establishes that a capability is absent.

## 10. Proposed future adapter specification (not implemented or registered)

If the received official artifact identifies a distinct 2025 release, the proposed adapter ID is **`quranmorph-birzeit-2025`**; the actual official artifact version must replace `2025` if it publishes one. This is a proposal only, not a production registry entry.

| Contract area | Proposed rule pending artifact proof |
|---|---|
| Identity/type | Official publisher identity, official release/version, and `user-local-dataset`; never derive identity from a mirror |
| Locator and row identity | Exact native locator fields and raw row/member position; require verified uniqueness and preserve explicit duplicates |
| Native accessors | Return only original field names, field order, raw strings/null spellings, raw lemma/Qabas IDs/POS; no QAC conversion or universal ontology |
| Query/aggregate | Declare only evidence-backed native dimensions; reject unsupported dimensions with structured errors |
| Serialization | Immutable, deterministic JSON with source release identity, artifact/member hashes, raw locator/value payload, parser issues and order |
| Errors | Missing artifact/terms, malformed rows, unsupported structures, duplicate/ambiguous locators, and unknown dimensions are explicit errors; no fallback or coercion |

## 11. Future alignment protocol

Tanzil remains canonical. A future bounded coordinate lookup returns all candidate mappings and never chooses a first candidate or overrides conflict evidence. It must explicitly represent one-to-one and many mappings using only:

- `DIRECT_COORDINATE` — source-native coordinate independently matches a canonical Tanzil token boundary.
- `independently validated GLOBAL ID` — an artifact global identifier is independently verified against Tanzil; it is not trusted merely by name.
- `NORMALIZED_SURFACE_WITHIN_AYAH` — a documented existing profile matches within the same ayah after raw comparison failed.
- `AMBIGUOUS` — multiple candidates, split/merge, duplicate coordinate, or insufficient disambiguation.
- `UNMATCHED` — no bounded candidate.

No partition estimate is possible without the artifact. Future estimates must distinguish source rows, source tokens, source segments, and canonical Tanzil tokens; none may be relabelled as another unit.

## 12. Cross-source coexistence policy

QuranMorph and QAC must coexist as independent source-native annotation streams. Native lemma spellings/IDs, POS tags, delimiter conventions, source locators, segmentation and missing-value semantics are not rewritten into each other and no universal POS/root/lemma ontology is created. Cross-source comparison is an explicit, stored-in-future alignment/view concern only after source-specific evidence is valid; it never mutates either source payload.

## 13. Database integrity and migration decision

**Migration decision: no migration.** QuranMorph has no database registration or rows.

The initial count attempt used nonexistent table names and is not evidence. A corrected read-only capture immediately before the full test suite and another after it produced the following table counts:

| Table | Before full suite | After full suite |
|---|---:|---:|
| `annotation_source_release` | 4 | 4 |
| `annotation_source_record` | 128292 | 128292 |
| `morphological_analysis` | 128351 | 128362 |
| `morphological_segment` | 128351 | 128362 |
| `qac_morphology_alignment` | 128219 | 128219 |
| `annotation_alignment` | 132 | 143 |
| `qac_alignment_run` | 1 | 1 |
| `morphology_ingestion_run` | 16 | 17 |
| `source_release` | 1 | 1 |
| `text_unit` | 6236 | 6236 |
| `orthographic_token` | 77881 | 77881 |
| QuranMorph-named `annotation_source_release` rows | 0 | 0 |

The Phase 4C audit itself issued no database write. The existing full suite's non-QuranMorph morphology tests changed pre-existing local QAC test evidence as shown; no QuranMorph row or evidence was created. This makes the requested global “no source/morphology/alignment persistence” validation unsuitable as a clean invariant in this existing test environment, but it confirms the required QuranMorph-specific zero-row condition.

Existing QAC file integrity was observed as unchanged at:

`a1d12923815341face765083805d2148ed2d9f5cc3f7d6665219d887675d8c46` for `data/annotation_incoming/quranic-corpus-morphology-0.4.txt`.

## 14. Validation and determinism disposition

Observed environment checks: `docker compose ps` reported PostgreSQL healthy; `alembic current` reported `202607240004 (head)`; `data/incoming/quranmorph/` is covered by the local-data ignore rule. `ruff check .` passed; `mypy src` passed; `pytest -q` passed (`61 passed`, with 20 pre-existing deprecation warnings); `quran validate 1` passed with byte-identical Tanzil reconstruction; `git diff --check` passed; the Phase 3B source-3 occurrence smoke passed; and the Phase 4B source-3 capabilities command returned the QAC descriptor.

The Phase 4A regression is covered by the passed suite. An audit-twice determinism test could not run because there is no official QuranMorph artifact and no parser/CLI. These checks do not establish QuranMorph readiness; they establish only that the existing project checks named above completed. The initial count command's unavailable `python` binary was corrected to `python3` for the final count captures.

## 15. Files changed

- `docs/quranmorph-source-audit.md` — this acquisition audit and future-only adapter/alignment specification.

No production source code, tests, migrations, manifests, incoming artifact, Tanzil file, QAC file, or registry was changed by Phase 4C.

## 16. Readiness criteria

Before Phase 4D, all of the following must be established from the received official artifact: official artifact provenance and untouched hash; explicit corpus-data license/terms; full real format audit; stable token/row identity and locator validation; deterministic DB-free parser/auditor with fixture tests; coordinate/surface comparison evidence; and completed integrity/validation counts. None is satisfied by the current landing-page-only evidence.

NOT READY
