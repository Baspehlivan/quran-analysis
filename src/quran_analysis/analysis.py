from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from quran_analysis import __version__
from quran_analysis.models.tables import AnalysisEvidence, AnalysisRun, EnvironmentSnapshot, ExportManifest, NormalizationProfile, NormalizedToken, OrthographicToken, SourceRelease, TextUnit, UnicodeCodepoint
from quran_analysis.normalization.profiles import PROFILES, normalize_token
from quran_analysis.provenance import EVIDENCE_HASH_ALGORITHM_VERSION, EXPORT_SCHEMA_VERSION, QUERY_HASH_ALGORITHM_VERSION, canonical_hash, environment, environment_snapshot_payload, evidence_hash as compute_evidence_hash, file_sha256, git_dirty, ngram_sequence_hash, query_hash_payload, utc_now_iso
from quran_analysis.tokenization.core import TOKENIZER_CONFIGURATION_SHA256, TOKENIZER_VERSION

DEFAULT_SCOPE = {"name": "numbered_ayah", "version": "v1", "unit_type": "numbered_ayah"}


def scope_config(scope: str) -> dict[str, Any]:
    if scope in {"all", "numbered", "numbered_ayah", "numbered-only"}:
        return DEFAULT_SCOPE
    return json.loads(scope)


def latest_source(session: Any) -> SourceRelease:
    sr = session.scalars(select(SourceRelease).order_by(SourceRelease.id.desc())).first()
    if sr is None:
        raise ValueError("no registered source_release")
    return sr


def ensure_profiles(session: Any) -> dict[str, int]:
    ids = {}
    for profile_id, profile in PROFILES.items():
        row = session.scalar(select(NormalizationProfile).where(NormalizationProfile.name == profile["name"], NormalizationProfile.version == profile["version"]))
        if row is None:
            row = NormalizationProfile(name=profile["name"], version=profile["version"], description=profile["description"], configuration_json=profile["configuration"], configuration_sha256=profile["configuration_sha256"], is_frozen=True)
            session.add(row); session.flush()
        elif row.configuration_sha256 != profile["configuration_sha256"] or not row.is_frozen:
            raise ValueError(f"normalization profile immutable violation: {profile_id}")
        ids[profile_id] = row.id
    session.commit()
    return ids


def profile_row(session: Any, profile_id: str) -> NormalizationProfile:
    ids = ensure_profiles(session)
    return session.get(NormalizationProfile, ids[profile_id])


def tokens_query(source_id: int):
    return select(OrthographicToken, TextUnit).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).where(TextUnit.source_release_id == source_id).order_by(OrthographicToken.token_in_full_source_stream)


def token_source_ids(session: Any, token: OrthographicToken) -> list[int]:
    cps = session.scalars(select(UnicodeCodepoint).where(UnicodeCodepoint.orthographic_token_id == token.id).order_by(UnicodeCodepoint.codepoint_in_token)).all()
    return [cp.id for cp in cps]


def ensure_normalized_tokens(session: Any, source_id: int, profile_id: str) -> NormalizationProfile:
    pr = profile_row(session, profile_id)
    rows = session.execute(tokens_query(source_id)).all()
    existing = set(session.scalars(select(NormalizedToken.orthographic_token_id).where(NormalizedToken.normalization_profile_id == pr.id)).all())
    needed = [token for token, _unit in rows if token.id not in existing]
    if not needed:
        return pr
    needed_ids = [token.id for token in needed]
    cps_by_token: dict[int, list[int]] = defaultdict(list)
    for offset in range(0, len(needed_ids), 5000):
        chunk = needed_ids[offset : offset + 5000]
        cp_rows = session.scalars(select(UnicodeCodepoint).where(UnicodeCodepoint.orthographic_token_id.in_(chunk)).order_by(UnicodeCodepoint.orthographic_token_id, UnicodeCodepoint.codepoint_in_token)).all()
        for cp in cp_rows:
            cps_by_token[cp.orthographic_token_id].append(cp.id)
    mappings = []
    for token in needed:
        result = normalize_token(token.surface_raw, profile_id, cps_by_token[token.id])
        mappings.append({
            "orthographic_token_id": token.id,
            "normalization_profile_id": pr.id,
            "normalized_value": result["normalized_value"],
            "transformation_log_json": result["transformation_log"],
            "profile_configuration_sha256": result["profile_configuration_sha256"],
            "normalized_to_source_codepoint_ids_json": result["normalized_to_source_codepoint_ids"],
        })
    session.bulk_insert_mappings(NormalizedToken, mappings)
    session.commit()
    return pr


def make_run(session: Any, analysis_type: str, source: SourceRelease, scope: dict[str, Any], profile: NormalizationProfile | None, params: dict[str, Any], allow_dirty: bool = False) -> tuple[AnalysisRun, str]:
    if git_dirty(Path.cwd()) and not allow_dirty:
        raise ValueError("refusing reproducible analysis from dirty git tree; pass --allow-dirty")
    payload = query_hash_payload(analysis_type=analysis_type, source=source, scope=scope, profile=profile, params=params, representation=params.get("representation"), cross_unit=params.get("cross_unit"), n=params.get("n"), session=session)
    qh = canonical_hash(payload)
    snap_payload = environment_snapshot_payload(session, source=source, scope=scope, profile=profile, command_name=analysis_type, query_params=params)
    snap_hash = canonical_hash(snap_payload)
    snap = session.scalar(select(EnvironmentSnapshot).where(EnvironmentSnapshot.content_hash == snap_hash))
    if snap is None:
        snap = EnvironmentSnapshot(content_hash=snap_hash, canonical_json=snap_payload)
        session.add(snap); session.flush()
    env = environment(session)
    run = AnalysisRun(analysis_type=analysis_type, source_release_id=source.id, scope_configuration_json=scope, normalization_profile_id=profile.id if profile else None, tokenizer_version=TOKENIZER_VERSION, software_version=__version__, query_parameters_json=params, query_hash=qh, query_hash_algorithm_version=QUERY_HASH_ALGORITHM_VERSION, evidence_hash=None, evidence_hash_algorithm_version=EVIDENCE_HASH_ALGORITHM_VERSION, environment_snapshot_id=snap.id, environment_snapshot_hash=snap_hash, git_commit_hash=env.get("git_commit_hash"), git_dirty=env.get("git_dirty"), schema_revision=env.get("alembic_revision"), status="running", result_count=None, completed_at=None, result_manifest_path=None, error_message=None)
    session.add(run); session.commit(); session.refresh(run)
    return run, qh


def finish_run(session: Any, run: AnalysisRun, results: list[dict[str, Any]], out_format: str | None = None) -> None:
    out_dir = Path("data/analysis_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"analysis_run_{run.id}.json"
    json_path.write_text(json.dumps({"analysis_run_id": run.id, "query_hash": run.query_hash, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = out_dir / f"analysis_run_{run.id}.csv"
    if results:
        keys = sorted({k for r in results for k in r.keys() if not isinstance(r.get(k), (dict, list))})
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows([{k: r.get(k) for k in keys} for r in results])
    eh = compute_evidence_hash(results)
    session.execute(update(AnalysisRun).where(AnalysisRun.id == run.id).values(status="completed", completed_at=datetime.utcnow(), result_count=len(results), result_manifest_path=str(json_path), evidence_hash=eh, evidence_hash_algorithm_version=EVIDENCE_HASH_ALGORITHM_VERSION))
    for idx, r in enumerate(results, 1):
        text_unit_id = r.get("text_unit_id") or r.get("first_text_unit_id")
        if text_unit_id is None:
            continue
        session.add(AnalysisEvidence(analysis_run_id=run.id, result_index=idx, text_unit_id=text_unit_id, orthographic_token_id=r.get("orthographic_token_id"), codepoint_start=r.get("codepoint_start"), codepoint_end=r.get("codepoint_end"), raw_value=str(r.get("raw_surface") or r.get("sequence") or r.get("value") or ""), normalized_value=r.get("normalized_surface"), inclusion_reason=run.analysis_type, evidence_json=r))
    session.commit()


def result_for_token(token: OrthographicToken, unit: TextUnit, source: SourceRelease, query_hash: str, profile: NormalizationProfile | None = None, normalized: str | None = None) -> dict[str, Any]:
    return {"text_unit_id": unit.id, "orthographic_token_id": token.id, "surah": unit.surah_number, "ayah": unit.ayah_number, "token_position_in_ayah": token.token_in_unit, "global_token_position": token.token_in_full_source_stream, "raw_surface": token.surface_raw, "normalized_surface": normalized, "codepoint_start": token.start_codepoint_in_unit, "codepoint_end": token.end_codepoint_in_unit, "source_release_sha256": source.sha256, "tokenizer_version": token.tokenizer_version, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "normalization_profile_sha256": profile.configuration_sha256 if profile else None, "query_hash": query_hash}


def exact_token_search(session: Any, surface: str, scope: str = "numbered_ayah", allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); sc = scope_config(scope); run, qh = make_run(session, "exact_raw_token_search", source, sc, None, {"surface": surface}, allow_dirty)
    results = [result_for_token(t, u, source, qh) for t, u in session.execute(tokens_query(source.id)).all() if t.surface_raw == surface]
    finish_run(session, run, results); return run, results


def normalized_token_search(session: Any, value: str, profile_id: str, scope: str = "numbered_ayah", allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id); sc = scope_config(scope); run, qh = make_run(session, "exact_normalized_token_search", source, sc, pr, {"value": value, "profile": profile_id}, allow_dirty)
    rows = session.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id == OrthographicToken.id).where(TextUnit.source_release_id == source.id, NormalizedToken.normalization_profile_id == pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
    results = [result_for_token(t, u, source, qh, pr, nt.normalized_value) | {"normalized_to_source_codepoint_ids": nt.normalized_to_source_codepoint_ids_json} for t, u, nt in rows if nt.normalized_value == value]
    finish_run(session, run, results); return run, results


def substring_search(session: Any, value: str, allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); run, qh = make_run(session, "raw_substring_search", source, DEFAULT_SCOPE, None, {"value": value, "representation": "raw"}, allow_dirty)
    results=[]
    for unit in session.scalars(select(TextUnit).where(TextUnit.source_release_id == source.id).order_by(TextUnit.source_order)).all():
        start = 0
        while True:
            idx = unit.text_raw.find(value, start)
            if idx < 0: break
            token = session.scalars(select(OrthographicToken).where(OrthographicToken.text_unit_id == unit.id, OrthographicToken.start_codepoint_in_unit <= idx, OrthographicToken.end_codepoint_in_unit >= idx + len(value)).order_by(OrthographicToken.token_in_unit)).first()
            results.append({"text_unit_id": unit.id, "orthographic_token_id": token.id if token else None, "surah": unit.surah_number, "ayah": unit.ayah_number, "token_position_in_ayah": token.token_in_unit if token else None, "global_token_position": token.token_in_full_source_stream if token else None, "raw_surface": token.surface_raw if token else value, "codepoint_start": idx, "codepoint_end": idx + len(value), "source_release_sha256": source.sha256, "tokenizer_version": token.tokenizer_version if token else TOKENIZER_VERSION, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "normalization_profile_sha256": None, "query_hash": qh})
            start = idx + 1
    finish_run(session, run, results); return run, results


def frequency_count(session: Any, representation: str, profile_id: str | None = None, scope: str = "numbered_ayah", allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if profile_id else None; run, qh = make_run(session, "token_frequency_count", source, scope_config(scope), pr, {"representation": representation, "profile": profile_id}, allow_dirty)
    counter: Counter[str] = Counter()
    if representation == "raw-token":
        for t, _u in session.execute(tokens_query(source.id)).all(): counter[t.surface_raw] += 1
    else:
        for value in session.scalars(select(NormalizedToken.normalized_value).where(NormalizedToken.normalization_profile_id == pr.id)).all(): counter[value] += 1
    results = [{"value": k, "count": v, "source_release_sha256": source.sha256, "tokenizer_version": TOKENIZER_VERSION, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "normalization_profile_sha256": pr.configuration_sha256 if pr else None, "query_hash": qh} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    finish_run(session, run, results); return run, results


def phrase_search(session: Any, phrase: str, representation: str = "raw-token", profile_id: str | None = None, cross_unit: bool = False, allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if representation == "normalized-token" else None; query_tokens = phrase.split(); run, qh = make_run(session, "phrase_search", source, DEFAULT_SCOPE, pr, {"phrase": phrase, "representation": representation, "cross_unit": cross_unit}, allow_dirty)
    rows=[]
    if pr:
        data = session.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id == OrthographicToken.id).where(TextUnit.source_release_id == source.id, NormalizedToken.normalization_profile_id == pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
        rows=[(t,u,nt.normalized_value) for t,u,nt in data]
    else:
        rows=[(t,u,t.surface_raw) for t,u in session.execute(tokens_query(source.id)).all()]
    results=[]; n=len(query_tokens)
    for i in range(0, len(rows)-n+1):
        window=rows[i:i+n]
        if not cross_unit and len({u.id for _,u,_ in window}) > 1: continue
        if [v for _,_,v in window] == query_tokens:
            first_t, first_u, _ = window[0]; last_t, _, _ = window[-1]
            results.append(result_for_token(first_t, first_u, source, qh, pr, " ".join(v for _,_,v in window) if pr else None) | {"sequence": " ".join(v for _,_,v in window), "codepoint_end": last_t.end_codepoint_in_unit})
    finish_run(session, run, results); return run, results


def repeated_ngrams(session: Any, n: int, representation: str = "raw-token", profile_id: str | None = None, cross_unit: bool = False, allow_dirty: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    if n < 2 or n > 10: raise ValueError("n must be 2..10")
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if representation == "normalized-token" else None; run, qh = make_run(session, "repeated_ngrams", source, DEFAULT_SCOPE, pr, {"n": n, "representation": representation, "cross_unit": cross_unit}, allow_dirty)
    if pr:
        data = session.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id == OrthographicToken.id).where(TextUnit.source_release_id == source.id, NormalizedToken.normalization_profile_id == pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
        rows=[(t,u,nt.normalized_value) for t,u,nt in data]
    else:
        rows=[(t,u,t.surface_raw) for t,u in session.execute(tokens_query(source.id)).all()]
    locs=defaultdict(list)
    for i in range(0, len(rows)-n+1):
        window=rows[i:i+n]
        if not cross_unit and len({u.id for _,u,_ in window}) > 1: continue
        tokens=[v for _,_,v in window]; seq=" ".join(tokens); t,u,_=window[0]
        locs[seq].append({"text_unit_id": u.id, "surah": u.surah_number, "ayah": u.ayah_number, "token_position_in_ayah": t.token_in_unit, "global_token_position": t.token_in_full_source_stream, "tokens": tokens})
    results=[{"sequence": seq, "sequence_hash": ngram_sequence_hash(loc[0]["tokens"], representation=representation, normalization_profile_sha256=pr.configuration_sha256 if pr else None, n=n), "n": n, "occurrence_count": len(loc), "locations": [{k:v for k,v in item.items() if k != "tokens"} for item in loc], "source_release_sha256": source.sha256, "normalization_profile_sha256": pr.configuration_sha256 if pr else None, "tokenizer_version": TOKENIZER_VERSION, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "query_hash": qh, "first_text_unit_id": loc[0]["text_unit_id"], "first_global_token_position": loc[0]["global_token_position"]} for seq, loc in sorted(locs.items()) if len(loc) > 1]
    finish_run(session, run, results); return run, results


EXPORT_FIELDS = ["text_unit_id", "orthographic_token_id", "surah", "ayah", "token_position_in_ayah", "global_token_position", "raw_surface", "normalized_surface", "codepoint_start", "codepoint_end", "sequence", "value", "count", "occurrence_count", "n", "sequence_hash", "source_release_sha256", "tokenizer_version", "tokenizer_configuration_sha256", "normalization_profile_sha256", "query_hash"]


def run_results(session: Any, run_id: int) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ValueError(f"analysis_run {run_id} not found")
    rows = session.scalars(select(AnalysisEvidence).where(AnalysisEvidence.analysis_run_id == run_id).order_by(AnalysisEvidence.result_index)).all()
    return run, [r.evidence_json for r in rows]


def write_export(session: Any, run_id: int, fmt: str, output: Path) -> dict[str, Any]:
    run, results = run_results(session, run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif fmt == "jsonl":
        output.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in results), encoding="utf-8")
    elif fmt == "csv":
        fields = [f for f in EXPORT_FIELDS if any(f in r and not isinstance(r.get(f), (dict, list)) for r in results)] or ["query_hash"]
        with output.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n"); w.writeheader(); w.writerows([{k: r.get(k) for k in fields} for r in results])
    else:
        raise ValueError("format must be csv, json, or jsonl")
    manifest = {"analysis_run_id": run.id, "query_hash": run.query_hash, "evidence_hash": run.evidence_hash, "source_sha256": session.get(SourceRelease, run.source_release_id).sha256, "environment_snapshot_hash": run.environment_snapshot_hash, "result_count": run.result_count, "export_row_count": len(results), "format": fmt, "export_schema_version": EXPORT_SCHEMA_VERSION, "export_file_sha256": file_sha256(output), "generated_at_utc": utc_now_iso(), "code_commit_hash": run.git_commit_hash, "dirty_status": run.git_dirty}
    manifest_hash = canonical_hash(manifest)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest | {"manifest_sha256": manifest_hash}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    session.add(ExportManifest(analysis_run_id=run.id, path=str(output), format=fmt, export_schema_version=EXPORT_SCHEMA_VERSION, export_file_sha256=manifest["export_file_sha256"], manifest_sha256=manifest_hash, canonical_json=manifest)); session.commit()
    return manifest | {"manifest_path": str(manifest_path), "manifest_sha256": manifest_hash}


def verify_export_file(path: Path) -> dict[str, Any]:
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return {"ok": False, "error": "manifest missing"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = file_sha256(path)
    if actual_sha != manifest.get("export_file_sha256"):
        return {"ok": False, "error": "export_file_sha256 mismatch", "expected": manifest.get("export_file_sha256"), "actual": actual_sha}
    fmt = manifest.get("format")
    if fmt == "json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    elif fmt == "jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    elif fmt == "csv":
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        return {"ok": False, "error": "unknown format"}
    if len(rows) != manifest.get("export_row_count"):
        return {"ok": False, "error": "row count mismatch", "expected": manifest.get("export_row_count"), "actual": len(rows)}
    return {"ok": True, "manifest": manifest, "export_file_sha256": actual_sha, "export_row_count": len(rows)}


def verify_run(session: Any, run_id: int) -> dict[str, Any]:
    run, results = run_results(session, run_id)
    eh = compute_evidence_hash(results)
    checks = {"status_completed": run.status == "completed", "environment_snapshot": bool(run.environment_snapshot_hash), "query_hash": bool(run.query_hash), "evidence_hash_match": eh == run.evidence_hash, "result_count_match": len(results) == run.result_count}
    return {"ok": all(checks.values()), "analysis_run_id": run.id, "checks": checks, "query_hash": run.query_hash, "evidence_hash": run.evidence_hash, "computed_evidence_hash": eh, "result_count": run.result_count}
