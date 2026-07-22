# Source policy

The adapter `tanzil-text-with-ayah-numbers-v1` accepts `surah|ayah|text` ayah records, blank lines, confirmed Tanzil footer/copyright/license/source-attribution lines, and comments. Unknown non-ayah lines are errors. Footer, license, comments, and blanks are persisted as `source_line` records but are not ingested as Quran `text_unit` rows.
