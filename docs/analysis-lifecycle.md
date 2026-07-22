# analysis-lifecycle

Phase 2B defines neutral reproducibility contracts only. Canonical JSON is UTF-8, sorted keys, compact separators, and UTC timestamps formatted as RFC3339  strings. Semantic hashes exclude output paths, terminal formatting, pagination limit/offset, timestamps, generated filenames, and unstable database row IDs.

- Query hash algorithm:  includes analysis type, source release identity/SHA, scope configuration/hash, tokenizer identity/hash, normalization profile identity/hash when used, ordered query parameters, representation, cross-unit flag, n-gram n, git commit/dirty policy, schema revision, and algorithm version.
- Evidence hash algorithm:  hashes the complete logical evidence set in canonical source/token/span/value order, independent of CSV/JSON/JSONL, output filename, pagination, and evidence row IDs.
- N-gram sequence hash:  hashes structured JSON containing representation, normalization profile SHA, n, and token array; it never joins token text with separators.
- Exports use stable UTF-8 CSV/JSON/JSONL schemas and a  sidecar with run id, query/evidence hashes, source SHA, environment snapshot hash, row counts, format/schema version, file SHA, timestamp, commit, and dirty status.
- Completed analysis provenance and frozen profile/scope/environment rows are immutable at DB trigger level.
