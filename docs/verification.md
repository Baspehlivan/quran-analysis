# Phase 5C verification and release certification

Phase 5C is a read-only certification boundary. Normal runtime never creates migrations,
sources, annotations, alignments, analysis runs, benchmarks, snapshots, manifests, or
certificates. Commands render observations to stdout only.

## Golden contract and update gate

`tests/golden/specs.json` is the versioned contract. It contains exactly eleven cases:
canonical token, root, lemma, POS, feature, grouped frequency, distinct count, set
intersection, SAME_AYAH cooccurrence, normalization profile, and aggregate report.
Each checked-in snapshot is canonical JSON and excludes volatile metadata
(`executed_at_utc`, `duration_ms`, `git_revision`, and `git_dirty`). It therefore locks
canonical request/payload/hash, ordering, aggregate/group output, and bounded evidence
rather than a machine observation.

Snapshots are generated only through the guarded verification tooling:

```sh
QURAN_ANALYSIS_GOLDEN_UPDATE=I_UNDERSTAND_GOLDEN_CONTRACT_CHANGE \
  quran verify --update-goldens --format json
```

Without that exact acknowledgement, `--update-goldens` exits with a structured error.
Normal verification only compares; it cannot silently bless changed output.

## Certification gates

`quran verify --format text|json|yaml` performs and reports each gate separately:

1. exact eleven-category, canonical, nonvolatile golden-contract check;
2. independent compatibility locks for Phase 3B morphology public API, Phase 4A
   analytics, Phase 4B capability descriptors, and Phase 4D lifecycle errors;
3. Phase 5A/5B canonical request serialization, payload/hash metamorphism, structured
   errors, ordering, aggregate, set, cooccurrence, and evidence-policy locks;
4. golden comparison and two deterministic executions of every golden workload; and
5. exact before/after counts for this fixed, ordered eleven-table invariant vector:
   `source_release`, `text_unit`, `orthographic_token`,
   `annotation_source_release`, `annotation_source_record`,
   `morphological_analysis`, `morphological_segment`, `qac_alignment_run`,
   `qac_morphology_alignment`, `analysis_run`, and `analysis_evidence`.

The `counts_before` and `counts_after` maps in `quran verify` are keyed by exactly
that ordered vector; `COUNTS_INVARIANT=true` requires the two maps to be equal.
`quran research-certificate` records the same count maps in its verification summary.

`verify` returns nonzero when any lock, golden, replay, or invariance check fails. Its
structured error exit is `2`; a completed certification with a failed gate exits `1`.

`quran benchmark`, `quran release-manifest`, and `quran research-certificate` accept the
same text/JSON/YAML formats and are read-only. Benchmark timings are volatile, have no
threshold, and are never certification inputs; all four workload classes (query,
aggregate, set, cooccurrence) are represented.

The release manifest is canonical and secret-free: repository revision/dirty state,
Alembic revision, source releases and hashes, adapters/capabilities, normalization
profiles, golden version, and engine version. A certificate hashes exactly its canonical
payload. `verified_at_utc` is the sole volatile certificate field, so certificates from
the same state have equal canonical payload and certificate hash.
