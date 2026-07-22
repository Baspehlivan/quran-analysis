from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import text

from quran_analysis import __version__
from quran_analysis.normalization.profiles import profile_hashes
from quran_analysis.tokenization.core import TOKENIZER_CONFIGURATION, TOKENIZER_CONFIGURATION_SHA256, TOKENIZER_VERSION


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
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def postgresql_version(session: Any | None = None) -> str | None:
    if session is None:
        return None
    try:
        return str(session.execute(text("select version()")).scalar_one())
    except Exception:
        return None


def environment(session: Any | None = None) -> dict[str, Any]:
    import regex
    import sqlalchemy

    return {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "postgresql_version": postgresql_version(session),
        "sqlalchemy_version": sqlalchemy.__version__,
        "regex_package_version": package_version("regex", regex),
        "unicodedata_unidata_version": unicodedata.unidata_version,
        "application_version": __version__,
        "git_commit_hash": git_commit_hash(Path.cwd()),
        "tokenizer": {
            "name": "orthographic_whitespace_tokenizer",
            "version": TOKENIZER_VERSION,
            "configuration": TOKENIZER_CONFIGURATION,
            "configuration_sha256": TOKENIZER_CONFIGURATION_SHA256,
        },
        "normalization_profile_hashes": profile_hashes(),
    }


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
