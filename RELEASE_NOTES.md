# Quran Analysis 1.1.0 Release Notes

## Research kit

This release adds executable bounded research examples, recipes, Python API guidance, optional dependency-free notebooks, citation guidance, architecture diagrams, and deterministic CSV/JSONL/Markdown rendering for read-only research outputs. Existing text, JSON, YAML, analysis export behavior, certified provenance, schema, and verification contracts remain unchanged.

## Verification

Run `quran verify --format json` against an aligned local database. It checks the versioned eleven-case golden contract, deterministic replay, and the fixed eleven-table no-write invariant.

## License and external sources

Repository code and documentation are licensed under Apache-2.0; see [LICENSE](LICENSE). This does not relicense external Tanzil/QAC/corpus artifacts. Their own licenses, attribution requirements, and terms continue to apply.

## Limitations

QAC remains a locally supplied external annotation source. Results are source-native evidence, not semantic, theological, historical, or authorship claims.
