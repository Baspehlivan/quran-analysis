"""Bounded, provenance-preserving QAC morphology to Tanzil token alignment."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import text

from quran_analysis.normalization.profiles import normalize_token

ALGORITHM_VERSION = "qac-tanzil-locator-v1"
METHODS = {"DIRECT", "NORMALIZED", "AMBIGUOUS", "UNMATCHED"}


def decide(segment: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all bounded candidates; never select an arbitrary candidate."""
    evidence = {"locator": segment["locator"], "qac_form": segment.get("form"), "candidate_count": len(candidates)}
    if not candidates:
        return [{"token_id": None, "method": "UNMATCHED", "status": "unmatched", "confidence": 0.0, "ambiguous": False, "evidence": evidence | {"reason": "no Tanzil token at QAC locator"}}]
    if len(candidates) > 1:
        return [{"token_id": c["id"], "method": "AMBIGUOUS", "status": "ambiguous", "confidence": 0.0, "ambiguous": True, "evidence": evidence | {"reason": "multiple Tanzil candidates at bounded locator", "candidate_ids": [x["id"] for x in candidates]}} for c in candidates]
    candidate = candidates[0]
    # Locator is the authoritative mapping; FORM is a segment and is compared only
    # when it equals the complete authoritative token representation.
    if segment.get("form") == candidate["surface_raw"]:
        return [{"token_id": candidate["id"], "method": "DIRECT", "status": "direct", "confidence": 1.0, "ambiguous": False, "evidence": evidence | {"comparison_representation": "source-native FORM == Tanzil raw token"}}]
    qac_normal = normalize_token(segment.get("form") or "", "base_arabic_letters_v1")
    token_normal = normalize_token(candidate["surface_raw"], "base_arabic_letters_v1")
    if qac_normal["normalized_value"] and qac_normal["normalized_value"] == token_normal["normalized_value"]:
        return [{"token_id": candidate["id"], "method": "NORMALIZED", "status": "normalized", "confidence": 0.95, "ambiguous": False, "evidence": evidence | {"normalization_profile": "base_arabic_letters_v1", "qac_normalized": qac_normal["normalized_value"], "tanzil_normalized": token_normal["normalized_value"]}}]
    return [{"token_id": candidate["id"], "method": "DIRECT", "status": "direct", "confidence": 1.0, "ambiguous": False, "evidence": evidence | {"comparison_representation": "QAC locator -> Tanzil authoritative token; FORM is a segment, not compared to token"}}]


def _run(session: Any, source_id: int) -> Any:
    return session.execute(text("""select r.id,r.annotation_source_release_id from morphology_ingestion_run r where r.annotation_source_release_id=:source and r.ingestion_kind='qac-source-parse-v1' and r.status='completed' order by r.id desc limit 1"""), {"source": source_id}).mappings().first()


def align_qac_source(session: Any, source_id: int, quran_source_id: int = 1) -> dict[str, Any]:
    ingest = _run(session, source_id)
    if not ingest:
        raise ValueError(f"source {source_id} has no completed QAC source ingestion")
    if not session.execute(text("select 1 from source_release where id=:id"), {"id": quran_source_id}).scalar():
        raise ValueError(f"Tanzil source {quran_source_id} not found")
    existing = session.execute(text("""select * from qac_alignment_run where morphology_ingestion_run_id=:run and quran_source_release_id=:quran and algorithm_version=:algorithm"""), {"run": ingest.id, "quran": quran_source_id, "algorithm": ALGORITHM_VERSION}).mappings().first()
    if existing and existing.status == "completed":
        return dict(existing.statistics_json) | {"alignment_run_id": existing.id, "idempotent": True}
    if existing:
        raise ValueError(f"alignment run {existing.id} is not completed")
    run_id = session.execute(text("""insert into qac_alignment_run(annotation_source_release_id,morphology_ingestion_run_id,quran_source_release_id,status,algorithm_version) values (:source,:ingest,:quran,'running',:algorithm) returning id"""), {"source": source_id, "ingest": ingest.id, "quran": quran_source_id, "algorithm": ALGORITHM_VERSION}).scalar_one()
    segments = session.execute(text("""select s.id segment_id,a.id analysis_id,a.annotation_source_record_id,a.parsed_locator_json,s.source_surface from morphological_segment s join morphological_analysis a on a.id=s.morphological_analysis_id where a.ingestion_run_id=:run order by s.id"""), {"run": ingest.id}).mappings().all()
    candidates_by_locator: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for token in session.execute(text("""select t.id,t.surface_raw,u.surah_number,u.ayah_number,t.token_in_unit from orthographic_token t join text_unit u on u.id=t.text_unit_id where u.source_release_id=:source"""), {"source": quran_source_id}).mappings():
        candidates_by_locator.setdefault((token.surah_number, token.ayah_number, token.token_in_unit), []).append(dict(token))
    by_method: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for segment in segments:
        locator = segment.parsed_locator_json
        candidates = candidates_by_locator.get((locator["surah"], locator["ayah"], locator["token"]), [])
        for result in decide({"locator": locator, "form": segment.source_surface}, candidates):
            by_method[result["method"]] += 1
            rows.append({"run": run_id, "source": source_id, "analysis": segment.analysis_id, "segment": segment.segment_id, "token": result["token_id"], "method": result["method"], "status": result["status"], "confidence": result["confidence"], "ambiguous": result["ambiguous"], "evidence": json.dumps(result["evidence"], ensure_ascii=False)})
    session.execute(text("""insert into qac_morphology_alignment(alignment_run_id,annotation_source_release_id,morphological_analysis_id,morphological_segment_id,orthographic_token_id,method,status,confidence,is_ambiguous,evidence_json) values (:run,:source,:analysis,:segment,:token,:method,:status,:confidence,:ambiguous,cast(:evidence as jsonb))"""), rows)
    covered = session.execute(text("select count(distinct morphological_segment_id) from qac_morphology_alignment where alignment_run_id=:run"), {"run": run_id}).scalar_one()
    total = len(segments)
    stats = {"total": total, "direct": by_method["DIRECT"], "normalized": by_method["NORMALIZED"], "ambiguous": by_method["AMBIGUOUS"], "unmatched": by_method["UNMATCHED"], "covered_segments": covered, "partition_ok": covered == total and sum(by_method.values()) >= total}
    if not stats["partition_ok"]:
        raise RuntimeError("alignment did not explicitly cover every morphology segment")
    session.execute(text("update qac_alignment_run set status='completed',completed_at=:now,statistics_json=cast(:stats as jsonb) where id=:id"), {"now": datetime.utcnow(), "stats": json.dumps(stats), "id": run_id})
    session.commit()
    return stats | {"alignment_run_id": run_id, "idempotent": False}
