from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from quran_analysis import __version__
from quran_analysis.normalization.profiles import profile_hashes
from quran_analysis.tokenization.core import TOKENIZER_CONFIGURATION, TOKENIZER_CONFIGURATION_SHA256, TOKENIZER_VERSION

QUERY_HASH_ALGORITHM_VERSION = "query-hash-v1"
EVIDENCE_HASH_ALGORITHM_VERSION = "evidence-hash-v1"
NGRAM_SEQUENCE_HASH_ALGORITHM_VERSION = "ngram-sequence-v1"
EXPORT_SCHEMA_VERSION = "analysis-export-v1"


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_hash(value: Any) -> str:
    return canonical_hash(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def package_version(name: str, module: Any | None = None) -> str | None:
    value = getattr(module, "__version__", None) if module is not None else None
    if value:
        return str(value)
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def git_commit_hash(cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd or Path.cwd(), check=True, capture_output=True, text=True, timeout=2)
    except Exception:
        return None
    return result.stdout.strip() or None


def git_dirty(cwd: Path | None = None) -> bool | None:
    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=cwd or Path.cwd(), check=True, capture_output=True, text=True, timeout=2)
    except Exception:
        return None
    return bool(result.stdout.strip())


def postgresql_version(session: Any | None = None) -> str | None:
    if session is None:
        return None
    try:
        return str(session.execute(text("select version()")).scalar_one())
    except Exception:
        return None


def alembic_revision(session: Any | None = None) -> str | None:
    if session is not None:
        try:
            return str(session.execute(text("select version_num from alembic_version")).scalar_one())
        except Exception:
            pass
    try:
        return ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    except Exception:
        return None


def environment(session: Any | None = None) -> dict[str, Any]:
    import regex
    import sqlalchemy
    cwd = Path.cwd()
    return {
        "application_version": __version__,
        "git_commit_hash": git_commit_hash(cwd),
        "git_dirty": git_dirty(cwd),
        "python_implementation": platform.python_implementation(),
        "python_version": sys.version,
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "postgresql_version": postgresql_version(session),
        "sqlalchemy_version": sqlalchemy.__version__,
        "alembic_revision": alembic_revision(session),
        "regex_package_version": package_version("regex", regex),
        "unicodedata_unidata_version": unicodedata.unidata_version,
        "tokenizer": {"name": "orthographic_whitespace_tokenizer", "version": TOKENIZER_VERSION, "configuration": TOKENIZER_CONFIGURATION, "configuration_sha256": TOKENIZER_CONFIGURATION_SHA256},
        "normalization_profile_hashes": profile_hashes(),
    }


def environment_snapshot_payload(session: Any, *, source: Any, scope: dict[str, Any], profile: Any | None, command_name: str, query_params: dict[str, Any]) -> dict[str, Any]:
    return environment(session) | {
        "source_release_id": source.id,
        "source_release_sha256": source.sha256,
        "source_name": source.source_name,
        "source_version": source.source_version,
        "scope_name": scope.get("name"),
        "scope_version": scope.get("version"),
        "scope_configuration_sha256": canonical_hash(scope),
        "normalization_profile_name": profile.name if profile else None,
        "normalization_profile_version": profile.version if profile else None,
        "normalization_profile_sha256": profile.configuration_sha256 if profile else None,
        "command_name": command_name,
        "canonical_query_parameters": query_params,
        "captured_at_utc": utc_now_iso(),
        "database_schema_revision": alembic_revision(session),
    }


def query_hash_payload(*, analysis_type: str, source: Any, scope: dict[str, Any], profile: Any | None, params: dict[str, Any], representation: str | None = None, cross_unit: bool | None = None, n: int | None = None, session: Any | None = None) -> dict[str, Any]:
    env = environment(session)
    return {
        "algorithm_version": QUERY_HASH_ALGORITHM_VERSION,
        "analysis_type": analysis_type,
        "source_release_sha256": source.sha256,
        "source_name": source.source_name,
        "source_version": source.source_version,
        "scope_configuration": scope,
        "scope_configuration_sha256": canonical_hash(scope),
        "tokenizer_name": "orthographic_whitespace_tokenizer",
        "tokenizer_version": TOKENIZER_VERSION,
        "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256,
        "normalization_profile_name": profile.name if profile else None,
        "normalization_profile_version": profile.version if profile else None,
        "normalization_profile_sha256": profile.configuration_sha256 if profile else None,
        "query_parameters": params,
        "representation": representation,
        "cross_unit": cross_unit,
        "ngram_n": n,
        "app_git_commit_hash": env.get("git_commit_hash"),
        "app_git_dirty_policy": "allow-dirty-recorded",
        "schema_revision": env.get("alembic_revision"),
    }


def ngram_sequence_hash(tokens: list[str], *, representation: str, normalization_profile_sha256: str | None, n: int) -> str:
    return canonical_hash({"algorithm_version": NGRAM_SEQUENCE_HASH_ALGORITHM_VERSION, "representation": representation, "normalization_profile_sha256": normalization_profile_sha256, "n": n, "tokens": tokens})


def evidence_hash(results: list[dict[str, Any]]) -> str:
    rows = [{k: v for k, v in r.items() if k not in {"id", "analysis_run_id", "query_hash"}} for r in results]
    rows.sort(key=lambda r: canonical_json({"source_order": r.get("global_token_position") or r.get("first_global_token_position") or 0, "surah": r.get("surah") or 0, "ayah": r.get("ayah") or 0, "token": r.get("token_position_in_ayah") or 0, "start": r.get("codepoint_start") or 0, "end": r.get("codepoint_end") or 0, "value": r.get("raw_surface") or r.get("sequence") or r.get("value") or "", "row": r}))
    return canonical_hash({"algorithm_version": EVIDENCE_HASH_ALGORITHM_VERSION, "evidence": rows})


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
