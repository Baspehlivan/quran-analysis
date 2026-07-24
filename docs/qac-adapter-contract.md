# QAC adapter contract

`qac-morphology-v0.4` is the implemented local QAC v0.4 adapter. It parses a user-provided local artifact, records immutable source-native payload and provenance, and supports explicit ingestion and Tanzil alignment. It never downloads an artifact; see [qac-local-acquisition.md](qac-local-acquisition.md) for the local-only acquisition boundary.

The canonical source representation is an ordered sequence of `RawRecord` values. Each record holds one-based physical line number, lossless line bytes excluding its ending, the exact physical ending (`LF`, `CRLF`, `CR`, or none), and a parser status. Concatenating `raw_line_bytes + physical_ending` reconstructs the original bytes exactly. Raw records must be consecutive and begin at line one.

`ParsedRecord` is a derived interpretation and is valid only for a raw record with `parsed` status. Unknown and malformed records retain their raw representation and carry their own strict status wrappers. `SegmentLocator` uses positive one-based coordinates; `FeatureBundle` preserves string-native feature pairs. Parser configuration is canonically serialized and SHA-256 hashed using `sha256-canonical-json-v1`.
