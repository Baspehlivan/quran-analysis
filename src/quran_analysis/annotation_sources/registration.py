"""Metadata-only registration for a locally acquired QAC morphology v0.4 file."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text

from quran_analysis.annotation_sources.contracts import (
    ParserConfiguration,
    ParserConfigurationHash,
    PhysicalEnding,
    QAC_MORPHOLOGY_V04_IDENTITY,
)
from quran_analysis.annotation_sources.qac_v04 import QACV04Parser

ADAPTER_ID = QAC_MORPHOLOGY_V04_IDENTITY.adapter_identifier
EXPECTED_CONFIGURATION = ParserConfiguration(ADAPTER_ID, "0.4")
EXPECTED_CONFIGURATION_HASH = ParserConfigurationHash.from_configuration(EXPECTED_CONFIGURATION)


class RegistrationRepository(Protocol):
    def find_by_sha256(self, sha256: str) -> Mapping[str, Any] | None: ...

    def create(self, values: Mapping[str, Any]) -> int: ...


class SqlRegistrationRepository:
    """Small persistence adapter; it inserts only an annotation source release."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def find_by_sha256(self, sha256: str) -> Mapping[str, Any] | None:
        row = self.session.execute(
            text("select id,name,version,format,raw_sha256,byte_size,parser_config_sha256,metadata_json from annotation_source_release where raw_sha256=:sha256"),
            {"sha256": sha256},
        ).mappings().first()
        return dict(row) if row else None

    def create(self, values: Mapping[str, Any]) -> int:
        return int(self.session.execute(text("""
            insert into annotation_source_release(
                name, version, format, publisher, official_url, license, license_url,
                citation, original_filename, stored_raw_path, raw_sha256, byte_size,
                line_count, parser_name, parser_version, parser_config_json,
                parser_config_sha256, metadata_json
            ) values (
                :name, :version, :format, :publisher, :official_url, :license, :license_url,
                :citation, :original_filename, :stored_raw_path, :raw_sha256, :byte_size,
                :line_count, :parser_name, :parser_version, cast(:parser_config_json as jsonb),
                :parser_config_sha256, cast(:metadata_json as jsonb)
            ) returning id
        """), dict(values)).scalar_one())


def _newline_style(endings: set[PhysicalEnding]) -> str:
    labels = {ending.name for ending in endings}
    if not labels:
        return "NONE"
    return labels.pop() if len(labels) == 1 else "MIXED"


def fingerprint_local_qac(path: str | Path) -> dict[str, Any]:
    """Read through the QAC adapter and derive fingerprints without persisting content."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"local QAC file not found: {source}")

    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    byte_count = 0
    line_count = 0
    endings: set[PhysicalEnding] = set()
    for record in QACV04Parser().iter_raw_records(source):
        physical = record.physical_bytes()
        sha256.update(physical)
        sha512.update(physical)
        byte_count += len(physical)
        line_count += 1
        endings.add(record.physical_ending)
    return {
        "sha256": sha256.hexdigest(),
        "sha512": sha512.hexdigest(),
        "byte_size": byte_count,
        "line_count": line_count,
        "encoding": "utf-8",
        "newline_style": _newline_style(endings),
    }


def register_local_qac(
    repository: RegistrationRepository,
    path: str | Path,
    *,
    adapter_id: str = ADAPTER_ID,
    source_name: str = "Quranic Arabic Corpus Morphology",
    source_version: str = "0.4",
    original_filename: str | None = None,
    acquisition_date: date | None = None,
    acquisition_metadata: Mapping[str, Any] | None = None,
    provenance_metadata: Mapping[str, Any] | None = None,
    expected_parser_configuration_hash: str | None = None,
    expected_sha256: str | None = None,
    expected_sha512: str | None = None,
) -> dict[str, Any]:
    """Register source-level QAC metadata only; never copy, parse into, or align data."""
    if adapter_id != ADAPTER_ID:
        raise ValueError(f"unsupported annotation adapter: {adapter_id}")
    expected_hash = EXPECTED_CONFIGURATION_HASH.digest
    if expected_parser_configuration_hash is not None and expected_parser_configuration_hash != expected_hash:
        raise ValueError("parser configuration hash does not match the QAC v0.4 adapter contract")

    fingerprint = fingerprint_local_qac(path)
    if expected_sha256 is not None and expected_sha256 != fingerprint["sha256"]:
        raise ValueError("local QAC SHA-256 does not match the expected integrity fingerprint")
    if expected_sha512 is not None and expected_sha512 != fingerprint["sha512"]:
        raise ValueError("local QAC SHA-512 does not match the expected integrity fingerprint")
    original_filename = original_filename or Path(path).name
    acquired = acquisition_date or date.today()
    metadata = {
        "registration_kind": "metadata-only-local-qac-v1",
        "source_identity": {
            "source_identifier": QAC_MORPHOLOGY_V04_IDENTITY.source_identifier,
            "source_class": QAC_MORPHOLOGY_V04_IDENTITY.source_class.value,
            "adapter_identifier": ADAPTER_ID,
            "adapter_version": QAC_MORPHOLOGY_V04_IDENTITY.adapter_version,
            "name": source_name,
            "version": source_version,
        },
        "file": {"filename": Path(path).name, "original_filename": original_filename, **fingerprint},
        "acquisition": {"date": acquired.isoformat(), "local_only": True, **dict(acquisition_metadata or {})},
        "provenance": dict(provenance_metadata or {}),
        "parser_configuration": {
            "identifier": EXPECTED_CONFIGURATION.parser_identifier,
            "version": EXPECTED_CONFIGURATION.parser_version,
            "options": dict(EXPECTED_CONFIGURATION.options),
            "canonical_hash_algorithm": EXPECTED_CONFIGURATION_HASH.algorithm,
            "canonical_hash": expected_hash,
        },
    }
    existing = repository.find_by_sha256(fingerprint["sha256"])
    if existing is not None:
        existing_metadata = existing.get("metadata_json") or {}
        if isinstance(existing_metadata, str):
            existing_metadata = json.loads(existing_metadata)
        same_registration = (
            existing["name"] == source_name
            and existing["version"] == source_version
            and existing["format"] == ADAPTER_ID
            and existing["byte_size"] == fingerprint["byte_size"]
            and existing["parser_config_sha256"] == expected_hash
            and existing_metadata.get("file", {}).get("sha512") == fingerprint["sha512"]
            and existing_metadata.get("source_identity", {}).get("adapter_identifier") == ADAPTER_ID
        )
        if not same_registration:
            raise ValueError("existing source fingerprint has incompatible source identity or integrity metadata")
        return {"annotation_source_release_id": existing["id"], "status": "already_registered", "metadata": metadata}

    values = {
        "name": source_name, "version": source_version, "format": ADAPTER_ID,
        "publisher": str((provenance_metadata or {}).get("publisher", "local acquisition")),
        "official_url": (provenance_metadata or {}).get("official_url"),
        "license": str((provenance_metadata or {}).get("license", "locally acquired; see provenance metadata")),
        "license_url": (provenance_metadata or {}).get("license_url"),
        "citation": (provenance_metadata or {}).get("citation"),
        "original_filename": original_filename,
        "stored_raw_path": f"metadata-only://{ADAPTER_ID}/{fingerprint['sha256']}",
        "raw_sha256": fingerprint["sha256"], "byte_size": fingerprint["byte_size"], "line_count": fingerprint["line_count"],
        "parser_name": EXPECTED_CONFIGURATION.parser_identifier, "parser_version": EXPECTED_CONFIGURATION.parser_version,
        "parser_config_json": EXPECTED_CONFIGURATION.canonical_json(), "parser_config_sha256": expected_hash,
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    }
    source_id = repository.create(values)
    return {"annotation_source_release_id": source_id, "status": "registered", "metadata": metadata}
