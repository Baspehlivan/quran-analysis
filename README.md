# Quran Analysis

`quran-analysis` 1.1.0 is neutral, auditable tooling for ingesting canonical Quran text and querying source-native morphology evidence. Raw registered bytes are immutable; derived data, alignment evidence, and research results preserve provenance.

It makes no theological, numerological, historical, or authorship claims. Tanzil is the authoritative Quran text source in this repository. QAC and any future morphology source are external annotations and do not replace it.

## Requirements

- Python 3.12 or later
- Docker and Docker Compose
- PostgreSQL 16 (the supplied Compose service exposes it on host port `55432`)

## Install and start PostgreSQL

```sh
python3 -m pip install -e .
cp .env.example .env
docker compose up -d postgres
docker compose ps
alembic upgrade head
alembic current
```

The supplied `.env.example` uses `postgresql+psycopg://quran:quran@localhost:55432/quran_analysis`, matching `docker-compose.yml`. `quran environment show` reports the effective runtime environment without revealing a connection string.

## Canonical Tanzil text

The byte-identical registered Tanzil input is tracked at:

```text
data/raw/tanzil-uthmani_1.1_tanzil-text-with-ayah-numbers-v1_bf4f57b968d03f4131c070b1e285da9be0e0a108a21c910e872801ca273312c8.txt
```

Its manifest is tracked under `data/manifests/`; its source footer contains the preserved attribution/license text. Inspect it without writing:

```sh
quran source inspect data/raw/tanzil-uthmani_1.1_tanzil-text-with-ayah-numbers-v1_bf4f57b968d03f4131c070b1e285da9be0e0a108a21c910e872801ca273312c8.txt --format tanzil-text-with-ayah-numbers-v1
```

On a fresh database, register and ingest that exact tracked file once:

```sh
quran source register data/raw/tanzil-uthmani_1.1_tanzil-text-with-ayah-numbers-v1_bf4f57b968d03f4131c070b1e285da9be0e0a108a21c910e872801ca273312c8.txt --name tanzil-uthmani --version 1.1 --format tanzil-text-with-ayah-numbers-v1
quran source list
quran ingest 1
quran validate 1
```

`source register` is content-addressed and reports an already registered source when the bytes are already present. Do not substitute a differently formatted or modified text file.

## Local QAC morphology artifact

QAC v0.4 is supported only as a user-provided local annotation artifact. It is not downloaded by this project and must not be committed. Put an official, legally usable copy at:

```text
data/incoming/quranic-corpus-morphology-0.4.txt
```

`data/incoming/`, raw annotation copies, manifests, and exports are Git-ignored. Before registration, retain the original filename, acquisition date, publisher, citation, applicable artifact-level license/terms, encoding, line ending convention, byte count, and checksum. See [docs/qac-local-acquisition.md](docs/qac-local-acquisition.md) and [docs/qac-adapter-contract.md](docs/qac-adapter-contract.md).

After Tanzil is ingested and only after those provenance and licensing checks, the explicit write workflow is:

```sh
quran annotation-source register-local-qac data/incoming/quranic-corpus-morphology-0.4.txt
quran annotation-source ingest SOURCE_ID
quran annotation-source align SOURCE_ID
quran annotation-source validate SOURCE_ID
quran annotation-source capabilities SOURCE_ID --format json
```

Replace `SOURCE_ID` with the identifier returned by registration. These commands persist source-native records and alignment evidence; they are intentionally not run as part of read-only verification.

## Read-only research

All commands below require completed QAC alignment evidence. The query, aggregate, set, cooccurrence, explain, catalog, verification, manifest, and certificate commands are read-only.

```sh
quran research query --query '{"where":{"and":[{"dimension":"surah","operator":"eq","value":1},{"dimension":"pos","operator":"eq","value":"N"}]}}' --format json
quran research aggregate --query-file examples/research/root-frequency.yaml --format json
quran research set --query-file examples/research/set-intersection.yaml --format json
quran research cooccurrence --query-file examples/research/cooccurrence.yaml --format json
quran research explain --query-file examples/research/explain.yaml --format json
quran annotation-source catalog --format json
```

Research results use source-native morphology fields and explicitly name their count identities. See [docs/research-engine.md](docs/research-engine.md), [docs/research-aggregation.md](docs/research-aggregation.md), and [docs/source-lifecycle.md](docs/source-lifecycle.md).

QuranMorph is catalogued as unavailable: no official artifact has been acquired or inspected, and no parser, registration, ingestion, alignment, or production adapter exists. Its lifecycle guard intentionally exits `2` with a structured error:

```sh
quran annotation-source lifecycle-guard quranmorph --operation ingestion
```

See [docs/quranmorph-source-audit.md](docs/quranmorph-source-audit.md).

## Verify and certify

```sh
quran validate 1
quran verify --format json
quran release-manifest --format json
quran research-certificate --format json
```

`quran verify` checks the versioned eleven-case golden contract, compatibility locks, deterministic replay, and equality of the fixed eleven-table before/after count vector. `release-manifest` and `research-certificate` render canonical, secret-free observations to standard output. Golden snapshots are updated only by the deliberately guarded command documented in [docs/verification.md](docs/verification.md); normal verification never updates them.

## License and external sources

The repository's code and documentation are licensed under the [Apache License 2.0](LICENSE) (`Apache-2.0`). This license applies only to this repository's original code and documentation. It does **not** relicense Tanzil, QAC, QuranMorph, or any other external corpus or annotation artifact: their respective licenses, attribution requirements, and terms remain controlling. Obtain and use external artifacts only under their own applicable terms.

## Documentation

- [Research recipes](docs/research-recipes.md)
- [Python API](docs/python-api.md)
- [Research export formats](docs/export-format.md)
- [Architecture diagrams](docs/architecture/index.md)
- [Optional notebooks](docs/notebooks.md)
- [Citation](docs/citation.md)
- [Architecture](docs/architecture.md)
- [Source policy](docs/source-policy.md)
- [QAC local acquisition](docs/qac-local-acquisition.md)
- [Verification and certification](docs/verification.md)
- [Release notes](RELEASE_NOTES.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [License](LICENSE)
