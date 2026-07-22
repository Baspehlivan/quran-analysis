from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from quran_analysis import __version__
from quran_analysis.models.tables import AnalysisEvidence, AnalysisRun, NormalizationProfile, NormalizedToken, OrthographicToken, SourceRelease, TextUnit, UnicodeCodepoint
from quran_analysis.normalization.profiles import PROFILES, normalize_token
from quran_analysis.provenance import environment, stable_hash
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


def make_run(session: Any, analysis_type: str, source: SourceRelease, scope: dict[str, Any], profile: NormalizationProfile | None, params: dict[str, Any]) -> tuple[AnalysisRun, str]:
    qh = stable_hash({"analysis_type": analysis_type, "source_sha256": source.sha256, "scope": scope, "profile_hash": profile.configuration_sha256 if profile else None, "params": params, "tokenizer_hash": TOKENIZER_CONFIGURATION_SHA256})
    run = AnalysisRun(analysis_type=analysis_type, source_release_id=source.id, scope_configuration_json=scope, normalization_profile_id=profile.id if profile else None, tokenizer_version=TOKENIZER_VERSION, software_version=__version__, query_parameters_json=params | {"environment": environment(session)}, query_hash=qh, status="running", result_count=None, completed_at=None, result_manifest_path=None, error_message=None)
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
    session.execute(update(AnalysisRun).where(AnalysisRun.id == run.id).values(status="completed", completed_at=datetime.utcnow(), result_count=len(results), result_manifest_path=str(json_path)))
    for idx, r in enumerate(results, 1):
        text_unit_id = r.get("text_unit_id") or r.get("first_text_unit_id")
        if text_unit_id is None:
            continue
        session.add(AnalysisEvidence(analysis_run_id=run.id, result_index=idx, text_unit_id=text_unit_id, orthographic_token_id=r.get("orthographic_token_id"), codepoint_start=r.get("codepoint_start"), codepoint_end=r.get("codepoint_end"), raw_value=str(r.get("raw_surface") or r.get("sequence") or r.get("value") or ""), normalized_value=r.get("normalized_surface"), inclusion_reason=run.analysis_type, evidence_json=r))
    session.commit()


def result_for_token(token: OrthographicToken, unit: TextUnit, source: SourceRelease, query_hash: str, profile: NormalizationProfile | None = None, normalized: str | None = None) -> dict[str, Any]:
    return {"text_unit_id": unit.id, "orthographic_token_id": token.id, "surah": unit.surah_number, "ayah": unit.ayah_number, "token_position_in_ayah": token.token_in_unit, "global_token_position": token.token_in_full_source_stream, "raw_surface": token.surface_raw, "normalized_surface": normalized, "codepoint_start": token.start_codepoint_in_unit, "codepoint_end": token.end_codepoint_in_unit, "source_release_sha256": source.sha256, "tokenizer_version": token.tokenizer_version, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "normalization_profile_sha256": profile.configuration_sha256 if profile else None, "query_hash": query_hash}


def exact_token_search(session: Any, surface: str, scope: str = "numbered_ayah") -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); sc = scope_config(scope); run, qh = make_run(session, "exact_raw_token_search", source, sc, None, {"surface": surface})
    results = [result_for_token(t, u, source, qh) for t, u in session.execute(tokens_query(source.id)).all() if t.surface_raw == surface]
    finish_run(session, run, results); return run, results


def normalized_token_search(session: Any, value: str, profile_id: str, scope: str = "numbered_ayah") -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id); sc = scope_config(scope); run, qh = make_run(session, "exact_normalized_token_search", source, sc, pr, {"value": value, "profile": profile_id})
    rows = session.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id == OrthographicToken.id).where(TextUnit.source_release_id == source.id, NormalizedToken.normalization_profile_id == pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
    results = [result_for_token(t, u, source, qh, pr, nt.normalized_value) | {"normalized_to_source_codepoint_ids": nt.normalized_to_source_codepoint_ids_json} for t, u, nt in rows if nt.normalized_value == value]
    finish_run(session, run, results); return run, results


def substring_search(session: Any, value: str) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); run, qh = make_run(session, "raw_substring_search", source, DEFAULT_SCOPE, None, {"value": value, "representation": "raw"})
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


def frequency_count(session: Any, representation: str, profile_id: str | None = None, scope: str = "numbered_ayah") -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if profile_id else None; run, qh = make_run(session, "token_frequency_count", source, scope_config(scope), pr, {"representation": representation, "profile": profile_id})
    counter: Counter[str] = Counter()
    if representation == "raw-token":
        for t, _u in session.execute(tokens_query(source.id)).all(): counter[t.surface_raw] += 1
    else:
        for value in session.scalars(select(NormalizedToken.normalized_value).where(NormalizedToken.normalization_profile_id == pr.id)).all(): counter[value] += 1
    results = [{"value": k, "count": v, "source_release_sha256": source.sha256, "tokenizer_version": TOKENIZER_VERSION, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "normalization_profile_sha256": pr.configuration_sha256 if pr else None, "query_hash": qh} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    finish_run(session, run, results); return run, results


def phrase_search(session: Any, phrase: str, representation: str = "raw-token", profile_id: str | None = None, cross_unit: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if representation == "normalized-token" else None; query_tokens = phrase.split(); run, qh = make_run(session, "phrase_search", source, DEFAULT_SCOPE, pr, {"phrase": phrase, "representation": representation, "cross_unit": cross_unit})
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


def repeated_ngrams(session: Any, n: int, representation: str = "raw-token", profile_id: str | None = None, cross_unit: bool = False) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    if n < 2 or n > 10: raise ValueError("n must be 2..10")
    source = latest_source(session); pr = ensure_normalized_tokens(session, source.id, profile_id) if representation == "normalized-token" else None; run, qh = make_run(session, "repeated_ngrams", source, DEFAULT_SCOPE, pr, {"n": n, "representation": representation, "cross_unit": cross_unit})
    if pr:
        data = session.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id == TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id == OrthographicToken.id).where(TextUnit.source_release_id == source.id, NormalizedToken.normalization_profile_id == pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
        rows=[(t,u,nt.normalized_value) for t,u,nt in data]
    else:
        rows=[(t,u,t.surface_raw) for t,u in session.execute(tokens_query(source.id)).all()]
    locs=defaultdict(list)
    for i in range(0, len(rows)-n+1):
        window=rows[i:i+n]
        if not cross_unit and len({u.id for _,u,_ in window}) > 1: continue
        seq=" ".join(v for _,_,v in window); t,u,_=window[0]
        locs[seq].append({"surah": u.surah_number, "ayah": u.ayah_number, "token_position_in_ayah": t.token_in_unit, "global_token_position": t.token_in_full_source_stream})
    results=[{"sequence": seq, "sequence_hash": stable_hash(seq), "n": n, "occurrence_count": len(loc), "locations": loc, "source_release_sha256": source.sha256, "normalization_profile_sha256": pr.configuration_sha256 if pr else None, "tokenizer_version": TOKENIZER_VERSION, "tokenizer_configuration_sha256": TOKENIZER_CONFIGURATION_SHA256, "query_hash": qh, "first_text_unit_id": loc[0]["surah"] if False else rows[0][1].id} for seq, loc in sorted(locs.items()) if len(loc) > 1]
    finish_run(session, run, results); return run, results
