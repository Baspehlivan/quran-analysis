# Research recipes

These recipes are read-only and require a completed supported QAC alignment. Input files are in [`examples/research`](../examples/research); [`index.yaml`](../examples/research-index.yaml) is a machine-readable bounded runner index. Run each command from the repository root. Results go to stdout; add `--output results.csv` to write a UTF-8 file.

## Count a source-native value

```sh
quran research aggregate --query-file examples/research/lemma-frequency.yaml --format json
```

The request explicitly counts `MORPHOLOGICAL_SEGMENT` identities, grouped by the source-native `lemma`; it is not a count of words, meanings, or orthographic tokens. Change the `unit` only when the requested identity is explicit. `COUNT`, `COUNT_DISTINCT`, and `FREQUENCY` retain the unit in their payload.

## Compare lemma labels

```sh
quran research aggregate --query-file examples/research/lemma-frequency.yaml --format csv
quran research aggregate --query-file examples/research/root-frequency.yaml --format markdown
```

Compare labels as QAC source-native annotations. Equal, related, or different lemma labels do **not** establish semantic equivalence. Inspect returned evidence, source release, parser status, and alignment fields before interpretation.

## Exact token and POS exploration

```sh
quran research query --file examples/research/exact-token.json --format json
quran research aggregate --query-file examples/research/pos-exploration.yaml --format yaml
```

`token` matches canonical aligned token text exactly; `pos` matches QAC's native part-of-speech tag. Both are bounded by their query `limit`.

## Imperfect verbs and feature search

```sh
quran research query --file examples/research/imperfect-verbs.json --format jsonl
```

For the supported QAC v0.4 adapter, verb records use the native `V` POS tag and the QAC feature fragment `IMPF` for imperfect aspect. The recipe deliberately asks for both exact values rather than translating them into an inferred linguistic category. QAC values, fragments, and provenance remain source-native; see [the QAC adapter contract](qac-adapter-contract.md).

## Group, set, and same-ayah operations

```sh
quran research aggregate --query-file examples/research/aggregate-surah.yaml --format csv
quran research cooccurrence --query-file examples/research/same-ayah-cooccurrence.yaml --format json
quran research set --query-file examples/research/set-intersection.yaml --format json
quran research set --query-file examples/research/set-union.yaml --format json
quran research set --query-file examples/research/set-difference.yaml --format json
quran research set --query-file examples/research/set-symmetric-difference.yaml --format json
```

Cooccurrence is only `SAME_AYAH`; it does not imply a syntactic or semantic relation. Set examples declare canonical-ayah identity and cover intersection, union, left difference, and symmetric difference.

## Reproduce and export

```sh
quran research query --file examples/research/exact-token.json --format csv --output exact-token.csv
quran research aggregate --query-file examples/research/root-frequency.yaml --format jsonl --output roots.jsonl
quran verify --format json
```

All research operations support `text`, `json`, `yaml`, `csv`, `jsonl`, and `markdown`. CSV, JSONL, and Markdown encode nested evidence/provenance as canonical JSON cells; rows and columns are deterministic UTF-8 with LF newlines. `quran verify` checks the certified v1.0 golden contract and eleven-table no-write invariant. It does not certify an interpretation or an unregistered annotation artifact.
