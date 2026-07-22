# Addressing

Address spaces are source-release scoped.

- `global_numbered_ayah_position`: deterministic ordered position of ayah records ingested from the registered source release.
- Token positions (`token_in_unit`, `token_in_surah`, `token_in_numbered_stream`) depend on `tokenizer_version` and are not universal across tokenizers or source streams.
- Raw codepoint positions (`codepoint_in_text_unit`, `codepoint_in_numbered_stream`, `source_release_codepoint_v1`) are stable for the exact registered source release bytes and ayah text extraction.
- `source_line.source_line_number` plus `byte_start`/`byte_end` address every original source line, including blank, comment, footer, license, and source metadata records. Ordered `source_line` rows reconstruct the complete source file with original line endings.
