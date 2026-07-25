# Contributing

## Development setup

Use Python 3.12 or later. Create an environment, install the project, copy the local configuration, and start PostgreSQL 16:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
docker compose up -d postgres
docker compose ps
alembic upgrade head
```

The Compose database listens on `localhost:55432`. The tracked Tanzil raw file may be registered and ingested with the commands in the README. QAC is a locally acquired external artifact: do not commit it or any derived local artifact.

## Standards and checks

Keep changes focused, deterministic, and compatible with the documented public contracts. Run the relevant checks before opening a pull request:

```sh
ruff check .
mypy src
pytest -q
quran validate 1
quran verify
```

`quran verify` is read-only and checks deterministic replay plus the eleven-table invariant. Do not weaken verification, mutate registered raw bytes, edit provenance records, or change schema/migrations without a separately reviewed change.

Golden snapshots are compatibility fixtures. Update them only with explicit maintainer approval, using the guarded golden-update workflow documented in `docs/verification.md`; include the reason, review evidence, and resulting verification output in the pull request.

## Commits and pull requests

- Use a concise, imperative commit subject and keep unrelated changes separate.
- Add or update tests and documentation for changed behavior.
- State compatibility, provenance, schema, source, and reproducibility impact explicitly.
- Do not commit corpora acquired locally, exports, database dumps, credentials, private keys, caches, or notebook output.
- Complete the pull-request checklist and link the relevant issue where applicable.
