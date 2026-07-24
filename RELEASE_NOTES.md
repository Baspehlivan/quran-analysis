# Quran Analysis 1.0.0 Release Notes

## Architecture

The system keeps registered source bytes immutable and stores derived text, morphology, alignment, and analysis evidence separately. Tanzil is the canonical Quran text source. Annotation streams remain source-native; QAC values are not transformed into a universal morphology ontology. CLI commands compose application services, while research, verification, manifest, and certificate boundaries are read-only.

## Capabilities

Version 1.0.0 supports canonical Tanzil source registration, ingestion, reconstruction validation, normalization, search, counts, n-grams, exports, and provenance checks. It supports a local-only QAC v0.4 adapter with explicit provenance, source-native parsing, validation, and bounded Tanzil alignment. Completed alignment evidence is available to morphology queries/statistics and read-only research query, aggregate, set, cooccurrence, and explain operations.

The source lifecycle catalog exposes Tanzil, QAC, and QuranMorph states. QAC acquisition is local-only; the project does not download it. QuranMorph remains unavailable and has no implemented artifact adapter.

## Verification and certification

`quran verify` validates a versioned eleven-workload golden contract, compatibility locks, deterministic replays, and an ordered eleven-table before/after count invariant. `quran release-manifest` renders a canonical secret-free state manifest. `quran research-certificate` renders a canonical certificate whose payload includes the verification summary. None of these commands persists a result.

## Setup

Install Python dependencies, start the supplied PostgreSQL 16 Compose service, and run Alembic migrations:

```sh
python3 -m pip install -e .
cp .env.example .env
docker compose up -d postgres
alembic upgrade head
```

The effective sample database URL uses host port `55432`. The tracked Tanzil source and manifest are sufficient for a fresh canonical-text setup; QAC must be supplied locally with artifact-level provenance and license/terms recorded before registration. The complete workflow is in [README.md](README.md).

## Known limitations

- QuranMorph cannot be registered or queried because no official artifact and artifact-level terms were available for inspection.
- QAC is a locally supplied external annotation source; the repository neither downloads nor redistributes it.
- Research requires completed, supported annotation alignment evidence and returns structured errors for unavailable capabilities or dimensions.
- The tool intentionally does not make theological, numerological, historical, or authorship claims.
