# Phase 5 research engine

`quran research query` is a **read-only** query boundary over canonical Tanzil tokens and completed Phase 3B morphology alignment evidence. Phase 5B preserves that boundary for aggregates: a segment is source-native morphology, a record is source input, a token is a canonical Tanzil token, and an ayah is the canonical text unit; counts must name exactly one of these identities. It creates no run, evidence, source, annotation, alignment, or research-result rows. The public result consists only of immutable value models; SQLAlchemy objects do not cross the boundary.

## Query grammar

A query is JSON or YAML with `schema: research-query-v1`, one `where` expression, and optional bounded `limit` (1–500) and non-negative `offset`.

```yaml
schema: research-query-v1
limit: 20
where:
  and:
    - dimension: root
      operator: eq
      value: كتب
    - or:
        - dimension: pos
          operator: eq
          value: V
        - dimension: feature
          operator: eq
          value: IMPF
```

Predicates are explicit objects with exactly `dimension`, `operator`, and `value`. Boolean objects have exactly one key: `and`, `or`, or `not`; their value is a list (`not` has exactly one child). There is no implicit precedence: nesting is the complete logical meaning.

Supported dimensions are `canonical_text`, `token`, `segment`, `root`, `lemma`, `pos`, `feature`, `surah`, `ayah`, `source_release`, `alignment_method`, `parser_status`, and `normalization_profile`. `eq` and `in` are exact operators; text/token additionally allow `contains` and `prefix`. `feature` is an exact source-native fragment. Numeric coordinates and source releases are positive integers. `normalization_profile` selects an existing persisted normalization profile associated with the token. `juz`, `hizb`, and `page` deliberately raise structured `unsupported_dimension` errors: no verified data in this repository supports them.

Inline input defaults to JSON:

```sh
quran research query --query '{"where":{"and":[{"dimension":"surah","operator":"eq","value":1},{"dimension":"pos","operator":"eq","value":"N"}]}}' --format json
```

Invalid syntax, capabilities, and unavailable dimensions exit nonzero with a structured JSON error on stderr.

## Compilation, optimization, and evidence

`ResearchEngine.compile()` turns the typed AST into parameterized SQL predicates. It reuses the Phase 3B completed-alignment predicates and Phase 4 adapter capability resolution; it never interpolates user values. `optimize()` canonicalizes only safe commutative `and`/`or` operations: nested same-kind operations are flattened, duplicate children removed, and children ordered by canonical serialization. It does not reorder `not` or change nesting.

Execution uses deterministic canonical coordinate ordering, a count plus bounded page, and completed alignment evidence only. Every match carries its coordinate/token, segment/root/lemma/POS/features, annotation and record IDs, source-native locator/raw record/features, parser status, alignment run/method/confidence, and source-release hash/name/version/adapter. Results therefore need no later evidence reconstruction.

## Phase 5B aggregation

See [research-aggregation.md](research-aggregation.md) for the read-only aggregation, identity-set, SAME_AYAH cooccurrence, deterministic evidence, capability and canonical-hash boundary. It reuses this document's immutable AST/compiler and completed-alignment semantics.

## Reproducibility

The report includes canonical query, source releases, normalization profile, schema revision, git revision/dirty status, returned/total counts, UTC execution time, and duration. Timestamp and duration necessarily vary. `ResearchResult.canonical_payload()` excludes volatile execution metadata and `reproducibility_hash()` hashes that stable payload. Matches and source releases are stably ordered, so equivalent commutative queries serialize identically and produce identical canonical reports against identical evidence.

## Phase 5C verification

The verification boundary is described in [verification.md](verification.md). It uses versioned
golden **input specifications** and explicitly gated generated snapshots; normal research query
execution remains read-only and does not write verification artifacts.
