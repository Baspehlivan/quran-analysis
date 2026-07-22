from __future__ import annotations

import csv
import hashlib
import json
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from quran_analysis.config import settings
from quran_analysis.provenance import alembic_revision, canonical_hash, environment, file_sha256, git_dirty

SYNTHETIC_FORMAT = "synthetic-qac-tsv-v1"
PARSER_VERSION = "synthetic-qac-parser-v1"
ALIGNMENT_ALGORITHM_VERSION = "qac-tanzil-alignment-v1"
TRANSLITERATION_PROFILE = {"name": "buckwalter-basic", "version": "v1", "reversible": False, "unmapped_policy": "preserve"}
FEATURE_RULES: dict[str, str] = {"POS": "pos", "PERS": "person", "GEN": "gender", "NUM": "number", "CASE": "case", "MOOD": "mood"}
FEATURE_PROFILE = {"name": "morphology-feature-map", "version": "v1", "rules": FEATURE_RULES}
ALIGNMENT_CONFIG = {"name": "qac-tanzil-alignment", "version": "v1", "normalization_profiles": ["identity_v1", "remove_combining_marks_v1"], "bounded_to_addressed_ayah": True, "never_choose_first_if_ambiguous": True}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_line(raw: bytes) -> tuple[str, str]:
    if raw.endswith(b"\r\n"):
        return raw[:-2].decode("utf-8"), "\r\n"
    if raw.endswith(b"\n"):
        return raw[:-1].decode("utf-8"), "\n"
    if raw.endswith(b"\r"):
        return raw[:-1].decode("utf-8"), "\r"
    return raw.decode("utf-8"), ""


def parse_features(value: str) -> dict[str, str]:
    if not value:
        return {}
    out: dict[str, str] = {}
    for part in value.split("|"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1); out[k] = v
        else:
            out[part] = "true"
    return out


def parse_locator(locator: str) -> dict[str, Any] | None:
    parts = locator.split(":")
    if len(parts) not in {3, 4}:
        return None
    try:
        s, a, t = [int(x) for x in parts[:3]]
        seg = int(parts[3]) if len(parts) == 4 else None
    except ValueError:
        return None
    if s < 1 or a < 1 or t < 1 or (seg is not None and seg < 1):
        return None
    return {"surah": s, "ayah": a, "token": t, "segment": seg}


def parse_synthetic(path: Path) -> list[dict[str, Any]]:
    rows = []
    record_no = 0
    for line_no, raw in enumerate(path.read_bytes().splitlines(keepends=True), 1):
        record_no += 1
        content, ending = split_line(raw)
        base = {"source_record_number": record_no, "source_line_number": line_no, "raw_record_content": content, "exact_line_ending": ending, "raw_record_sha256": sha_bytes(raw)}
        if content == "":
            rows.append(base | {"record_type": "blank", "parse_status": "unknown", "parse_error": None, "parsed_payload_json": None}); continue
        if content.startswith("#"):
            typ = "license" if "license" in content.lower() else "comment"
            rows.append(base | {"record_type": typ, "parse_status": "unknown", "parse_error": None, "parsed_payload_json": {"comment": content}}); continue
        if content.startswith("@"):
            rows.append(base | {"record_type": "unknown", "parse_status": "unknown", "parse_error": "unknown record prefix", "parsed_payload_json": {"raw": content}}); continue
        fields = content.split("\t")
        if len(fields) != 8:
            rows.append(base | {"record_type": "malformed", "parse_status": "malformed", "parse_error": f"expected 8 TSV fields, got {len(fields)}", "parsed_payload_json": {"fields": fields}}); continue
        locator, surface, translit, pos, lemma, root, features, variant = fields
        payload = {"locator": locator, "surface": surface, "transliteration": translit, "pos": pos or None, "lemma": lemma or None, "root": root or None, "features": parse_features(features), "variant": int(variant or "1"), "fields": fields}
        rows.append(base | {"record_type": "analysis", "parse_status": "parsed", "parse_error": None, "parsed_payload_json": payload})
    return rows


def inspect_annotation_source(path: Path, fmt: str) -> dict[str, Any]:
    if fmt != SYNTHETIC_FORMAT:
        raise ValueError(f"unsupported annotation format: {fmt}")
    rows = parse_synthetic(path)
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["parse_status"]] += 1; counts[r["record_type"]] += 1
    data = path.read_bytes()
    return {"format": fmt, "path": str(path), "byte_size": len(data), "sha256": sha_bytes(data), "line_count": len(rows), "counts": dict(counts), "byte_identical_reconstruction": b"".join((r["raw_record_content"] + r["exact_line_ending"]).encode("utf-8") for r in rows) == data, "parser": {"name": SYNTHETIC_FORMAT, "version": PARSER_VERSION, "config_sha256": canonical_hash({"format": fmt, "version": PARSER_VERSION})}}


def register_annotation_source(session: Any, path: Path, *, name: str, version: str, fmt: str, publisher: str, license: str, official_url: str | None = None, license_url: str | None = None, citation: str | None = None) -> dict[str, Any]:
    info = inspect_annotation_source(path, fmt)
    raw_dir = settings.data_dir / "annotation_raw"; raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = settings.data_dir / "annotation_manifests"; manifest_dir.mkdir(parents=True, exist_ok=True)
    stored = raw_dir / f"{name}-{version}-{info['sha256'][:12]}{path.suffix}"
    shutil.copyfile(path, stored)
    if file_sha256(stored) != info["sha256"]:
        raise ValueError("stored copy hash mismatch")
    parser_config = {"format": fmt, "version": PARSER_VERSION}
    existing = session.execute(text("select id,stored_raw_path from annotation_source_release where raw_sha256=:sha"), {"sha": info["sha256"]}).mappings().first()
    if existing:
        existing_path = Path(existing.stored_raw_path)
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        if not existing_path.exists():
            shutil.copyfile(path, existing_path)
        return info | {"annotation_source_release_id": existing.id, "stored_raw_path": existing.stored_raw_path, "status": "already_registered"}
    row = session.execute(text("""
        insert into annotation_source_release(name, version, format, publisher, official_url, license, license_url, citation, original_filename, stored_raw_path, raw_sha256, byte_size, line_count, parser_name, parser_version, parser_config_json, parser_config_sha256, metadata_json)
        values (:name,:version,:format,:publisher,:official_url,:license,:license_url,:citation,:original_filename,:stored_raw_path,:raw_sha256,:byte_size,:line_count,:parser_name,:parser_version,cast(:parser_config_json as jsonb),:parser_config_sha256,cast(:metadata_json as jsonb)) returning id
    """), {"name": name, "version": version, "format": fmt, "publisher": publisher, "official_url": official_url, "license": license, "license_url": license_url, "citation": citation, "original_filename": path.name, "stored_raw_path": str(stored), "raw_sha256": info["sha256"], "byte_size": info["byte_size"], "line_count": info["line_count"], "parser_name": fmt, "parser_version": PARSER_VERSION, "parser_config_json": json.dumps(parser_config), "parser_config_sha256": canonical_hash(parser_config), "metadata_json": json.dumps(info)}).scalar_one()
    for rec in parse_synthetic(path):
        session.execute(text("""insert into annotation_source_record(annotation_source_release_id, source_record_number, source_line_number, record_type, raw_record_content, exact_line_ending, raw_record_sha256, parsed_payload_json, parse_status, parse_error, metadata_json) values (:sid,:source_record_number,:source_line_number,:record_type,:raw_record_content,:exact_line_ending,:raw_record_sha256,cast(:parsed_payload_json as jsonb),:parse_status,:parse_error,cast(:metadata_json as jsonb))"""), rec | {"sid": row, "parsed_payload_json": json.dumps(rec["parsed_payload_json"], ensure_ascii=False) if rec["parsed_payload_json"] is not None else None, "metadata_json": json.dumps({})})
    manifest = info | {"annotation_source_release_id": row, "stored_raw_path": str(stored)}
    mpath = manifest_dir / f"annotation_source_{row}.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    session.commit()
    return manifest | {"manifest_path": str(mpath), "status": "registered"}


def list_annotation_sources(session: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in session.execute(text("select id,name,version,format,publisher,license,raw_sha256,stored_raw_path,line_count from annotation_source_release order by id"))]


def show_annotation_source(session: Any, source_id: int) -> dict[str, Any]:
    row = session.execute(text("select * from annotation_source_release where id=:id"), {"id": source_id}).mappings().first()
    if not row:
        raise ValueError(f"annotation source {source_id} not found")
    counts = dict(session.execute(text("select parse_status, count(*) from annotation_source_record where annotation_source_release_id=:id group by parse_status"), {"id": source_id}).all())
    return dict(row) | {"parse_counts": counts}


def validate_annotation_source(session: Any, source_id: int) -> dict[str, Any]:
    src = show_annotation_source(session, source_id)
    data = b"".join((r.raw_record_content + r.exact_line_ending).encode("utf-8") for r in session.execute(text("select raw_record_content, exact_line_ending from annotation_source_record where annotation_source_release_id=:id order by source_record_number"), {"id": source_id}))
    path = Path(src["stored_raw_path"])
    ok = path.exists() and path.read_bytes() == data and sha_bytes(data) == src["raw_sha256"]
    return {"annotation_source_release_id": source_id, "ok": ok, "byte_identical": ok, "stored_raw_path": str(path), "raw_sha256": sha_bytes(data), "expected_sha256": src["raw_sha256"], "counts": src["parse_counts"]}


def ensure_profile(session: Any, table: str, config: dict[str, Any], description: str) -> int:
    h = canonical_hash(config)
    row = session.execute(text(f"select id from {table} where configuration_sha256=:h"), {"h": h}).first()
    if row:
        return int(row.id)
    return int(session.execute(text(f"insert into {table}(name,version,description,configuration_json,configuration_sha256,is_frozen) values (:n,:v,:d,cast(:c as jsonb),:h,true) returning id"), {"n": config["name"], "v": config["version"], "d": description, "c": json.dumps(config, ensure_ascii=False), "h": h}).scalar_one())


def remove_marks(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def standard_features(features: dict[str, str]) -> dict[str, Any]:
    out = {}
    for k, v in features.items():
        std = FEATURE_RULES.get(k)
        if std:
            out[std] = {"source_native_value": v, "mapping_rule": k, "mapping_version": "morphology-feature-map-v1", "confidence": 1.0, "transformation_log": []}
    return out


def transliterate(value: str) -> dict[str, Any]:
    return {"source_transliteration": value, "profile": "buckwalter-basic-v1", "derived": value, "unmapped": [], "transformation_log": [], "reversible": False}


def token_row(session: Any, quran_source_id: int, loc: dict[str, Any]) -> Any | None:
    return session.execute(text("""select t.id token_id,u.id text_unit_id,u.surah_number,u.ayah_number,t.token_in_unit,t.surface_raw,t.start_codepoint_in_unit,t.end_codepoint_in_unit from orthographic_token t join text_unit u on u.id=t.text_unit_id where u.source_release_id=:sid and u.surah_number=:s and u.ayah_number=:a and t.token_in_unit=:t"""), {"sid": quran_source_id, "s": loc["surah"], "a": loc["ayah"], "t": loc["token"]}).mappings().first()


def ayah_candidates(session: Any, quran_source_id: int, loc: dict[str, Any], surface: str) -> list[dict[str, Any]]:
    rows = session.execute(text("""select t.id token_id,u.id text_unit_id,u.surah_number,u.ayah_number,t.token_in_unit,t.surface_raw,t.start_codepoint_in_unit,t.end_codepoint_in_unit from orthographic_token t join text_unit u on u.id=t.text_unit_id where u.source_release_id=:sid and u.surah_number=:s and u.ayah_number=:a"""), {"sid": quran_source_id, "s": loc["surah"], "a": loc["ayah"]}).mappings().all()
    target = remove_marks(surface)
    return [dict(r) for r in rows if remove_marks(r.surface_raw) == target]


def alignment_decision(session: Any, quran_source_id: int, loc: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    if loc is None:
        return {"status": "unaligned", "type": "invalid_locator", "token": None, "reason": "invalid locator", "confidence": 0.0, "candidates": [], "comparison": None, "profile": None, "transforms": []}
    tok = token_row(session, quran_source_id, loc)
    if not tok:
        return {"status": "unaligned", "type": "missing_locator", "token": None, "reason": "locator not found in authoritative Tanzil tokens", "confidence": 0.0, "candidates": [], "comparison": None, "profile": None, "transforms": []}
    if payload["surface"] == tok.surface_raw:
        typ = "segment_exact" if loc.get("segment") else "exact_token"
        return {"status": "aligned", "type": typ, "token": tok, "reason": "exact surface match at locator", "confidence": 1.0, "candidates": [dict(tok)], "comparison": payload["surface"], "profile": "identity_v1", "transforms": []}
    if remove_marks(payload["surface"]) == remove_marks(tok.surface_raw):
        return {"status": "partial" if loc.get("segment") else "aligned", "type": "normalized_token", "token": tok, "reason": "remove_combining_marks_v1 match at locator", "confidence": 0.9, "candidates": [dict(tok)], "comparison": remove_marks(payload["surface"]), "profile": "remove_combining_marks_v1", "transforms": ["removed Unicode combining marks"]}
    cands = ayah_candidates(session, quran_source_id, loc, payload["surface"])
    if len(cands) == 1:
        return {"status": "partial", "type": "bounded_candidate", "token": cands[0], "reason": "single normalized candidate in addressed ayah but locator token differed", "confidence": 0.6, "candidates": cands, "comparison": remove_marks(payload["surface"]), "profile": "remove_combining_marks_v1", "transforms": ["bounded ayah candidate search"]}
    if len(cands) > 1:
        return {"status": "ambiguous", "type": "bounded_candidate", "token": None, "reason": "multiple candidates in addressed ayah; no first-match selection", "confidence": 0.0, "candidates": cands, "comparison": remove_marks(payload["surface"]), "profile": "remove_combining_marks_v1", "transforms": ["bounded ayah candidate search"]}
    return {"status": "unaligned", "type": "surface_mismatch", "token": None, "reason": "surface mismatch and no bounded candidates", "confidence": 0.0, "candidates": [], "comparison": remove_marks(payload["surface"]), "profile": "remove_combining_marks_v1", "transforms": []}


def ingest_morphology(session: Any, source_id: int, quran_source_id: int, alignment_config: str, allow_dirty: bool = False) -> dict[str, Any]:
    if alignment_config != "qac-tanzil-alignment-v1":
        raise ValueError("only qac-tanzil-alignment-v1 is implemented")
    if git_dirty(Path.cwd()) and not allow_dirty:
        raise ValueError("refusing morphology ingestion from dirty git tree; pass --allow-dirty")
    src = show_annotation_source(session, source_id)
    tid = ensure_profile(session, "transliteration_profile", TRANSLITERATION_PROFILE, "Synthetic Buckwalter-style transliteration preservation profile")
    fid = ensure_profile(session, "morphology_feature_mapping_profile", FEATURE_PROFILE, "Synthetic QAC-style feature mapping profile")
    aid = ensure_profile(session, "alignment_configuration", ALIGNMENT_CONFIG, "Synthetic QAC locator to Tanzil token alignment")
    env = environment(session); configs = {"transliteration": canonical_hash(TRANSLITERATION_PROFILE), "feature_mapping": canonical_hash(FEATURE_PROFILE), "alignment": canonical_hash(ALIGNMENT_CONFIG), "parser": src["parser_config_sha256"]}
    run_id = session.execute(text("""insert into morphology_ingestion_run(annotation_source_release_id,quran_source_release_id,alignment_configuration_id,transliteration_profile_id,feature_mapping_profile_id,status,environment_snapshot_json,git_commit_hash,git_dirty,schema_revision,source_hashes_json,configuration_hashes_json) values (:sid,:qid,:aid,:tid,:fid,'running',cast(:env as jsonb),:git,:dirty,:rev,cast(:sources as jsonb),cast(:configs as jsonb)) returning id"""), {"sid": source_id, "qid": quran_source_id, "aid": aid, "tid": tid, "fid": fid, "env": json.dumps(env, default=str), "git": env.get("git_commit_hash"), "dirty": env.get("git_dirty"), "rev": alembic_revision(session), "sources": json.dumps({"annotation_raw_sha256": src["raw_sha256"]}), "configs": json.dumps(configs)}).scalar_one()
    counts = defaultdict(int)
    analyses_by_token: dict[int, list[dict[str, Any]]] = defaultdict(list)
    records = session.execute(text("select id,source_record_number,record_type,parse_status,parsed_payload_json from annotation_source_record where annotation_source_release_id=:sid order by source_record_number"), {"sid": source_id}).mappings().all()
    for rec in records:
        counts["source_record_count"] += 1
        if rec.parse_status == "malformed": counts["malformed_count"] += 1; continue
        if rec.parse_status == "unknown": counts["unknown_count"] += 1; continue
        payload = rec.parsed_payload_json
        loc = parse_locator(payload["locator"])
        std = standard_features(payload["features"]); tr = transliterate(payload["transliteration"])
        ah = canonical_hash({"algorithm_version": "morphology-analysis-hash-v1", "record_hash": rec.id, "payload": payload, "standardized_features": std, "transliteration": tr})
        analysis_id = session.execute(text("""insert into morphological_analysis(ingestion_run_id,annotation_source_record_id,variant_index,external_locator,parsed_locator_json,source_surface,source_transliteration,source_pos,source_lemma,source_root,source_features_json,standardized_features_json,transliteration_json,source_native_payload_json,analysis_hash) values (:run,:rec,:variant,:locator,cast(:ploc as jsonb),:surface,:trans,:pos,:lemma,:root,cast(:features as jsonb),cast(:std as jsonb),cast(:tr as jsonb),cast(:payload as jsonb),:hash) returning id"""), {"run": run_id, "rec": rec.id, "variant": payload["variant"], "locator": payload["locator"], "ploc": json.dumps(loc), "surface": payload["surface"], "trans": payload["transliteration"], "pos": payload["pos"], "lemma": payload["lemma"], "root": payload["root"], "features": json.dumps(payload["features"]), "std": json.dumps(std), "tr": json.dumps(tr), "payload": json.dumps(payload, ensure_ascii=False), "hash": ah}).scalar_one()
        counts["parsed_analysis_count"] += 1
        sh = canonical_hash({"algorithm_version": "morphology-segment-hash-v1", "analysis_hash": ah, "segment_index": (loc.get("segment") or 1) if loc else 1, "surface": payload["surface"]})
        seg_id = session.execute(text("""insert into morphological_segment(morphological_analysis_id,segment_index,external_locator,source_surface,source_transliteration,source_pos,source_features_json,codepoint_start_in_source_token,codepoint_end_in_source_token,segment_hash) values (:analysis,:idx,:locator,:surface,:trans,:pos,cast(:features as jsonb),:start,:end,:hash) returning id"""), {"analysis": analysis_id, "idx": (loc.get("segment") or 1) if loc else 1, "locator": payload["locator"], "surface": payload["surface"], "trans": payload["transliteration"], "pos": payload["pos"], "features": json.dumps(payload["features"]), "start": 0 if loc and loc.get("segment") else None, "end": len(payload["surface"]) if loc and loc.get("segment") else None, "hash": sh}).scalar_one()
        counts["segment_count"] += 1
        dec = alignment_decision(session, quran_source_id, loc, payload)
        tok = dec["token"]
        if dec["status"] in {"ambiguous", "partial"}: counts["ambiguous_count"] += int(dec["status"] == "ambiguous")
        if dec["status"] == "unaligned": counts["unaligned_count"] += 1
        align_payload = {"algorithm_version": "morphology-alignment-hash-v1", "analysis_hash": ah, "segment_hash": sh, "decision": {k: v for k, v in dec.items() if k != "token"}}
        alh = canonical_hash(align_payload)
        token_id = tok.get("token_id") if isinstance(tok, dict) else (tok.token_id if tok else None)
        if token_id:
            analyses_by_token[int(token_id)].append({"analysis_id": analysis_id, "lemma": payload["lemma"], "root": payload["root"], "pos": payload["pos"], "features": payload["features"]})
        session.execute(text("""insert into annotation_alignment(ingestion_run_id,morphological_analysis_id,morphological_segment_id,annotation_source_record_id,orthographic_token_id,text_unit_id,surah_number,ayah_number,token_position,external_locator,alignment_type,alignment_status,source_surface,authoritative_raw_token,codepoint_start,codepoint_end,comparison_representation,normalization_profile,normalization_transformations_json,candidates_json,decision_rule,confidence,reason,algorithm_version,conflict_dimensions_json,alignment_hash) values (:run,:analysis,:seg,:rec,:token_id,:unit_id,:surah,:ayah,:tokpos,:locator,:atype,:status,:surface,:raw,:start,:end,:comparison,:profile,cast(:transforms as jsonb),cast(:candidates as jsonb),:rule,:confidence,:reason,:algo,cast('[]' as jsonb),:hash)"""), {"run": run_id, "analysis": analysis_id, "seg": seg_id, "rec": rec.id, "token_id": token_id, "unit_id": (tok.get("text_unit_id") if isinstance(tok, dict) else (tok.text_unit_id if tok else None)), "surah": loc.get("surah") if loc else None, "ayah": loc.get("ayah") if loc else None, "tokpos": loc.get("token") if loc else None, "locator": payload["locator"], "atype": dec["type"], "status": dec["status"], "surface": payload["surface"], "raw": (tok.get("surface_raw") if isinstance(tok, dict) else (tok.surface_raw if tok else None)), "start": (tok.get("start_codepoint_in_unit") if isinstance(tok, dict) else None), "end": (tok.get("end_codepoint_in_unit") if isinstance(tok, dict) else None), "comparison": dec["comparison"], "profile": dec["profile"], "transforms": json.dumps(dec["transforms"]), "candidates": json.dumps(dec["candidates"], ensure_ascii=False, default=str), "rule": "strict staged synthetic alignment", "confidence": dec["confidence"], "reason": dec["reason"], "algo": ALIGNMENT_ALGORITHM_VERSION, "hash": alh})
        counts["alignment_count"] += 1
    # mark conflicts without changing completed rows yet
    for token_id, vals in analyses_by_token.items():
        dims = [d for d in ["lemma", "root", "pos"] if len({v[d] for v in vals if v[d]}) > 1]
        if dims:
            session.execute(text("update annotation_alignment set alignment_status='conflict', conflict_dimensions_json=cast(:dims as jsonb), reason=reason || '; conflict preserved' where ingestion_run_id=:run and orthographic_token_id=:tid"), {"dims": json.dumps(dims), "run": run_id, "tid": token_id})
    counts["alignment_count"] = session.execute(text("select count(*) from annotation_alignment where ingestion_run_id=:run"), {"run": run_id}).scalar_one()
    counts["ambiguous_count"] = session.execute(text("select count(*) from annotation_alignment where ingestion_run_id=:run and alignment_status='ambiguous'"), {"run": run_id}).scalar_one()
    counts["unaligned_count"] = session.execute(text("select count(*) from annotation_alignment where ingestion_run_id=:run and alignment_status='unaligned'"), {"run": run_id}).scalar_one()
    ingestion_hash = canonical_hash({"algorithm_version": "morphology-ingestion-hash-v1", "source_hashes": {"annotation_raw_sha256": src["raw_sha256"]}, "configuration_hashes": configs, "counts": dict(counts)})
    params = dict(counts) | {"hash": ingestion_hash, "run": run_id}
    session.execute(text("""update morphology_ingestion_run set status='completed', completed_at=:completed, source_record_count=:source_record_count, parsed_analysis_count=:parsed_analysis_count, segment_count=:segment_count, alignment_count=:alignment_count, malformed_count=:malformed_count, unknown_count=:unknown_count, ambiguous_count=:ambiguous_count, unaligned_count=:unaligned_count, ingestion_hash=:hash where id=:run"""), params | {"completed": datetime.utcnow()})
    session.commit()
    return stats(session, run_id)


def stats(session: Any, run_id: int) -> dict[str, Any]:
    row = session.execute(text("select * from morphology_ingestion_run where id=:id"), {"id": run_id}).mappings().first()
    if not row: raise ValueError(f"morphology ingestion run {run_id} not found")
    by_status = dict(session.execute(text("select alignment_status,count(*) from annotation_alignment where ingestion_run_id=:id group by alignment_status"), {"id": run_id}).all())
    return {"ingestion_run_id": run_id, "status": row.status, "source_records": row.source_record_count, "parsed_analyses": row.parsed_analysis_count, "segments": row.segment_count, "alignments": row.alignment_count, "malformed": row.malformed_count, "unknown": row.unknown_count, "ambiguous": row.ambiguous_count, "unaligned": row.unaligned_count, "alignments_by_status": by_status, "ingestion_hash": row.ingestion_hash}


def validate_ingestion(session: Any, run_id: int) -> dict[str, Any]:
    st = stats(session, run_id)
    actual = session.execute(text("select (select count(*) from morphological_analysis where ingestion_run_id=:id),(select count(*) from morphological_segment s join morphological_analysis a on a.id=s.morphological_analysis_id where a.ingestion_run_id=:id),(select count(*) from annotation_alignment where ingestion_run_id=:id)"), {"id": run_id}).first()
    ok = st["parsed_analyses"] == actual[0] and st["segments"] == actual[1] and st["alignments"] == actual[2]
    return st | {"ok": ok, "actual": {"analyses": actual[0], "segments": actual[1], "alignments": actual[2]}}


def get_table_row(session: Any, table: str, id: int) -> dict[str, Any]:
    row = session.execute(text(f"select * from {table} where id=:id"), {"id": id}).mappings().first()
    if not row: raise ValueError(f"{table} {id} not found")
    return dict(row)


def show_token(session: Any, locator: str, source_id: int) -> list[dict[str, Any]]:
    loc = parse_locator(locator)
    if not loc: raise ValueError("invalid locator")
    return [dict(r._mapping) for r in session.execute(text("""select al.id alignment_id,al.alignment_status,al.alignment_type,al.reason,ma.source_lemma,ma.source_root,ma.source_pos,al.authoritative_raw_token from annotation_alignment al join morphological_analysis ma on ma.id=al.morphological_analysis_id join morphology_ingestion_run r on r.id=al.ingestion_run_id where r.annotation_source_release_id=:sid and al.surah_number=:s and al.ayah_number=:a and al.token_position=:t order by al.id"""), {"sid": source_id, "s": loc["surah"], "a": loc["ayah"], "t": loc["token"]})]


def unresolved(session: Any, source_id: int, status: str) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in session.execute(text("""select al.id alignment_id,al.external_locator,al.alignment_status,al.alignment_type,al.reason,al.candidates_json from annotation_alignment al join morphology_ingestion_run r on r.id=al.ingestion_run_id where r.annotation_source_release_id=:sid and al.alignment_status=:status order by al.id"""), {"sid": source_id, "status": status})]


def conflicts(session: Any, source_id: int, dimension: str) -> list[dict[str, Any]]:
    if dimension not in {"lemma", "root", "pos", "features"}: raise ValueError("invalid conflict dimension")
    return [dict(r._mapping) for r in session.execute(text("""select al.id alignment_id,al.external_locator,al.conflict_dimensions_json,ma.source_lemma,ma.source_root,ma.source_pos,ma.source_features_json from annotation_alignment al join morphology_ingestion_run r on r.id=al.ingestion_run_id join morphological_analysis ma on ma.id=al.morphological_analysis_id where r.annotation_source_release_id=:sid and al.alignment_status='conflict' and al.conflict_dimensions_json ? :dim order by al.id"""), {"sid": source_id, "dim": dimension})]


def export_entity(session: Any, run_id: int, entity: str, fmt: str, output: Path) -> dict[str, Any]:
    queries = {
        "alignments": "select * from annotation_alignment where ingestion_run_id=:id order by id",
        "source-records": "select r.* from annotation_source_record r join morphology_ingestion_run run on run.annotation_source_release_id=r.annotation_source_release_id where run.id=:id order by r.source_record_number",
        "analyses": "select * from morphological_analysis where ingestion_run_id=:id order by id",
        "segments": "select s.* from morphological_segment s join morphological_analysis a on a.id=s.morphological_analysis_id where a.ingestion_run_id=:id order by s.id",
        "unresolved": "select * from annotation_alignment where ingestion_run_id=:id and alignment_status in ('ambiguous','partial','unaligned','conflict') order by id",
        "conflicts": "select * from annotation_alignment where ingestion_run_id=:id and alignment_status='conflict' order by id",
        "validation": None,
    }
    if entity not in queries: raise ValueError("invalid export entity")
    if fmt not in {"json", "jsonl", "csv"}: raise ValueError("invalid export format")
    rows = [validate_ingestion(session, run_id)] if entity == "validation" else [dict(r._mapping) for r in session.execute(text(queries[entity]), {"id": run_id})]
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json": output.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    elif fmt == "jsonl": output.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    else:
        keys = sorted({k for r in rows for k in r.keys()}) if rows else ["empty"]
        with output.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    fhash = file_sha256(output); manifest = {"ingestion_run_id": run_id, "entity": entity, "format": fmt, "path": str(output), "export_file_sha256": fhash, "schema": "morphology-export-v1"}; mh = canonical_hash(manifest)
    session.execute(text("insert into morphology_export_manifest(ingestion_run_id,entity,path,format,export_file_sha256,manifest_sha256,canonical_json) values (:run,:entity,:path,:fmt,:fh,:mh,cast(:j as jsonb))"), {"run": run_id, "entity": entity, "path": str(output), "fmt": fmt, "fh": fhash, "mh": mh, "j": json.dumps(manifest)})
    session.commit(); return manifest | {"manifest_sha256": mh, "row_count": len(rows)}


def verify_export(session: Any, path: Path) -> dict[str, Any]:
    h = file_sha256(path)
    row = session.execute(text("select * from morphology_export_manifest where path=:p order by id desc limit 1"), {"p": str(path)}).mappings().first()
    ok = bool(row and row.export_file_sha256 == h)
    return {"path": str(path), "ok": ok, "sha256": h, "expected_sha256": row.export_file_sha256 if row else None, "manifest_sha256": row.manifest_sha256 if row else None}
