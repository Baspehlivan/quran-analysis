# Source policy

The adapter `tanzil-text-with-ayah-numbers-v1` accepts `surah|ayah|text` ayah records, blank lines, confirmed Tanzil footer/copyright/license/source-attribution lines, and comments. Unknown non-ayah lines are errors. Footer, license, comments, and blanks are persisted as `source_line` records but are not ingested as Quran `text_unit` rows.

## Phase 2B repository policy

The Tanzil footer/license text is present in the registered source file. For reproducibility, the byte-identical raw registered source and its manifest are kept in this repository; generated analysis export payloads under `data/analysis_runs/` are ignored.
