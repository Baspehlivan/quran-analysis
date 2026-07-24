"""Transactional, source-only persistence for metadata-registered QAC v0.4 files."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from quran_analysis.annotation_sources.contracts import MalformedRecord, ParsedRecord
from quran_analysis.annotation_sources.qac_v04 import QACV04Parser
from quran_analysis.provenance import alembic_revision, canonical_hash, environment

INGESTION_KIND = "qac-source-parse-v1"


def _source_path(source: Any) -> Path:
    metadata = source.metadata_json if isinstance(source.metadata_json, dict) else json.loads(source.metadata_json)
    filename = metadata.get("file", {}).get("filename")
    if not filename:
        raise ValueError("metadata-only source has no local filename")
    path = Path("data/incoming") / filename
    if not path.is_file():
        raise FileNotFoundError(f"local QAC file is unavailable: {path}")
    return path


def _raw_values(record: Any, number: int, parsed: Any) -> dict[str, Any]:
    raw = record.raw_record
    payload: dict[str, Any] | None = None
    error: str | None = None
    if isinstance(parsed, ParsedRecord):
        payload = {
            **parsed.payload,
            "locator_components": {"surah": parsed.locator.surah, "ayah": parsed.locator.ayah, "token": parsed.locator.token, "segment": parsed.locator.segment},
            "feature_bundle": {"raw_text": parsed.features.raw_text, "fragments": list(parsed.features.fragments), "separator": parsed.features.separator, "native": parsed.features.native},
        }
    elif isinstance(parsed, MalformedRecord):
        error = parsed.error.message
        payload = {"raw": raw.decoded_text}
    else:
        payload = {"raw": raw.decoded_text, "record_kind": raw.record_kind.value}
    return {
        "source_record_number": number, "source_line_number": raw.line_number,
        "record_type": raw.record_kind.value, "raw_record_content": raw.decoded_text,
        "exact_line_ending": bytes(raw.physical_ending).decode("ascii"), "raw_record_sha256": hashlib.sha256(raw.physical_bytes()).hexdigest(),
        "parsed_payload_json": json.dumps(payload, ensure_ascii=False), "parse_status": raw.parser_status.value,
        "parse_error": error, "metadata_json": json.dumps({"parser": "qac-morphology-v0.4"}),
    }


def ingest_qac_source(session: Any, source_id: int) -> dict[str, Any]:
    source = session.execute(text("select * from annotation_source_release where id=:id"), {"id": source_id}).mappings().first()
    if not source:
        raise ValueError(f"annotation source {source_id} not found")
    if source.format != "qac-morphology-v0.4":
        raise ValueError("annotation-source ingest supports only qac-morphology-v0.4")
    existing = session.execute(text("select id,status from morphology_ingestion_run where annotation_source_release_id=:id and ingestion_kind=:kind order by (status='completed') desc, id desc"), {"id": source_id, "kind": INGESTION_KIND}).mappings().first()
    if existing and existing.status == "completed":
        return source_ingestion_stats(session, int(existing.id)) | {"idempotent": True}
    if existing and existing.status == "running":
        raise ValueError(f"source {source_id} already has running source ingestion run {existing.id}")

    path = _source_path(source)
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != source.raw_sha256:
        raise ValueError("local QAC SHA-256 differs from registered source")
    env = environment(session)
    run_values = {"sid": source_id, "kind": INGESTION_KIND, "env": json.dumps(env, default=str), "git": env.get("git_commit_hash"), "dirty": env.get("git_dirty"), "rev": alembic_revision(session), "hashes": json.dumps({"annotation_raw_sha256": actual_hash}), "configs": json.dumps({"parser": source.parser_config_sha256})}
    try:
        run_id = session.execute(text("""insert into morphology_ingestion_run(annotation_source_release_id,ingestion_kind,status,environment_snapshot_json,git_commit_hash,git_dirty,schema_revision,source_hashes_json,configuration_hashes_json) values (:sid,:kind,'running',cast(:env as jsonb),:git,:dirty,:rev,cast(:hashes as jsonb),cast(:configs as jsonb)) returning id"""), run_values).scalar_one()
        parser = QACV04Parser()
        records = list(parser.iter_records(path))
        counts: Counter[str] = Counter()
        for number, parsed in enumerate(records, start=1):
            values = _raw_values(parsed, number, parsed)
            counts[values["parse_status"]] += 1
            session.execute(text("""insert into annotation_source_record(annotation_source_release_id,source_record_number,source_line_number,record_type,raw_record_content,exact_line_ending,raw_record_sha256,parsed_payload_json,parse_status,parse_error,metadata_json) values (:sid,:source_record_number,:source_line_number,:record_type,:raw_record_content,:exact_line_ending,:raw_record_sha256,cast(:parsed_payload_json as jsonb),:parse_status,:parse_error,cast(:metadata_json as jsonb))"""), values | {"sid": source_id})
            if not isinstance(parsed, ParsedRecord):
                continue
            payload = json.loads(values["parsed_payload_json"])
            locator = payload["locator_components"]
            analysis_hash = canonical_hash({"source_record": number, "payload": payload})
            analysis_id = session.execute(text("""insert into morphological_analysis(ingestion_run_id,annotation_source_record_id,variant_index,external_locator,parsed_locator_json,source_surface,source_transliteration,source_pos,source_lemma,source_root,source_features_json,standardized_features_json,transliteration_json,source_native_payload_json,analysis_hash) values (:run,:record,1,:locator,cast(:parsed_locator as jsonb),:form,null,:tag,null,null,cast(:features as jsonb),'{}'::jsonb,'{}'::jsonb,cast(:payload as jsonb),:hash) returning id"""), {"run": run_id, "record": session.execute(text("select id from annotation_source_record where annotation_source_release_id=:sid and source_record_number=:number"), {"sid": source_id, "number": number}).scalar_one(), "locator": payload["LOCATION"], "parsed_locator": json.dumps(locator), "form": payload["FORM"], "tag": payload["TAG"], "features": json.dumps(payload["feature_bundle"], ensure_ascii=False), "payload": json.dumps(payload, ensure_ascii=False), "hash": analysis_hash}).scalar_one()
            session.execute(text("""insert into morphological_segment(morphological_analysis_id,segment_index,external_locator,source_surface,source_transliteration,source_pos,source_features_json,codepoint_start_in_source_token,codepoint_end_in_source_token,segment_hash) values (:analysis,:segment,:locator,:form,null,:tag,cast(:features as jsonb),null,null,:hash)"""), {"analysis": analysis_id, "segment": locator["segment"], "locator": payload["LOCATION"], "form": payload["FORM"], "tag": payload["TAG"], "features": json.dumps(payload["feature_bundle"], ensure_ascii=False), "hash": canonical_hash({"analysis": analysis_hash, "segment": locator["segment"]})})
        parsed_count = counts["parsed"]
        session.execute(text("""update morphology_ingestion_run set status='completed',completed_at=:now,source_record_count=:records,parsed_analysis_count=:parsed,segment_count=:segments,alignment_count=0,malformed_count=:malformed,unknown_count=:unknown,ambiguous_count=0,unaligned_count=0,ingestion_hash=:hash where id=:id"""), {"now": datetime.utcnow(), "records": len(records), "parsed": parsed_count, "segments": parsed_count, "malformed": counts["malformed"], "unknown": counts["unknown"], "hash": canonical_hash({"source": actual_hash, "records": len(records), "parsed": parsed_count}), "id": run_id})
        session.commit()
        return source_ingestion_stats(session, int(run_id)) | {"idempotent": False}
    except Exception as exc:
        session.rollback()
        # Failed state is deliberately a separate transaction: payload writes rolled back.
        failed = session.execute(text("""insert into morphology_ingestion_run(annotation_source_release_id,ingestion_kind,status,environment_snapshot_json,git_commit_hash,git_dirty,schema_revision,source_hashes_json,configuration_hashes_json,error_message) values (:sid,:kind,'failed',cast(:env as jsonb),:git,:dirty,:rev,cast(:hashes as jsonb),cast(:configs as jsonb),:error) returning id"""), run_values | {"error": str(exc)}).scalar_one()
        session.commit()
        raise RuntimeError(f"QAC source ingestion failed (run {failed}); all payload rows rolled back: {exc}") from exc


def source_ingestion_stats(session: Any, run_id: int) -> dict[str, Any]:
    run = session.execute(text("select * from morphology_ingestion_run where id=:id"), {"id": run_id}).mappings().first()
    if not run:
        raise ValueError(f"morphology ingestion run {run_id} not found")
    actual = session.execute(text("""select (select count(*) from annotation_source_record where annotation_source_release_id=:source), (select count(*) from morphological_analysis where ingestion_run_id=:run), (select count(*) from morphological_segment s join morphological_analysis a on a.id=s.morphological_analysis_id where a.ingestion_run_id=:run), (select count(*) from annotation_alignment where ingestion_run_id=:run)"""), {"source": run.annotation_source_release_id, "run": run_id}).one()
    return {"ingestion_run_id": run_id, "status": run.status, "ingestion_kind": run.ingestion_kind, "source_records": run.source_record_count, "parsed_analyses": run.parsed_analysis_count, "segments": run.segment_count, "alignments": run.alignment_count, "malformed": run.malformed_count, "unknown": run.unknown_count, "actual": {"source_records": actual[0], "analyses": actual[1], "segments": actual[2], "alignments": actual[3]}, "ok": run.status == "completed" and run.parsed_analysis_count == actual[1] and run.segment_count == actual[2] and actual[3] == 0}
