# validation

Phase 1 neutral, auditable implementation notes. Raw source bytes are immutable. Derived processes must preserve provenance and avoid claims or hard-coded analytical counts.

## Phase 2B validation

Run: `docker compose ps`, `alembic current`, `alembic upgrade head`, `quran validate 1`, `quran environment show`, `pytest -q`, `ruff check .`, `mypy src`, representative repeated analyses, export/verify in CSV/JSON/JSONL, tamper-failure check, `quran analysis verify RUN_ID`, EXPLAIN audits, and prohibited-content grep.
