from pathlib import Path
import hashlib
from sqlalchemy import select, func
from quran_analysis.config import settings
from quran_analysis.sources.pipe import parse_pipe_ayah_v1, parse_source, diagnostics_failed
from quran_analysis.tokenization.core import tokenize_reversible, reconstruct_from_tokens, graphemes, tokenization_metadata
from quran_analysis.unicode.inventory import codepoints
from quran_analysis.models.tables import SourceRelease, SourceLine, Surah, TextUnit, OrthographicToken, UnicodeCodepoint, GraphemeCluster

LINE_ENDING_LABEL = {"\n":"LF", "\r\n":"CRLF", "\r":"CR", "":"none"}

def ingest_memory(path: Path) -> dict:
    text=path.read_text(encoding="utf-8")
    diag=parse_pipe_ayah_v1(text)
    units=[]; token_stream=0; cp_stream=0; numbered_cp=0; token_surah_counts={}
    for source_order,r in enumerate(diag.records,1):
        toks=tokenize_reversible(r.text); token_surah_counts.setdefault(r.surah_number,0)
        for n,t in enumerate(toks,1):
            token_stream += 1; token_surah_counts[r.surah_number]+=1
            t["token_in_unit"]=n; t["token_in_surah"]=token_surah_counts[r.surah_number]; t["token_in_full_source_stream"]=token_stream; t["token_in_numbered_stream"]=token_stream
        cps=codepoints(r.text)
        for cp in cps:
            cp_stream += 1; numbered_cp += 1
            cp["codepoint_in_full_source_stream"]=cp_stream; cp["codepoint_in_numbered_stream"]=numbered_cp
        units.append({"surah_number":r.surah_number,"ayah_number":r.ayah_number,"source_order":source_order,"global_numbered_ayah_position":source_order,"text_raw":r.text,"source_line_number":r.line_number,"tokens":toks,"codepoints":cps,"graphemes":graphemes(r.text),"metadata_json":tokenization_metadata(toks)})
    return {"diagnostics":diag,"units":units}

def stored_source_path(sr: SourceRelease) -> Path:
    p=Path(sr.stored_filename)
    return p if p.exists() else settings.data_dir/"raw"/sr.stored_filename

def ingest_source_release(session, source_id: int) -> dict:
    sr=session.get(SourceRelease, source_id)
    if sr is None: raise ValueError(f"source_release not found: {source_id}")
    if session.scalar(select(func.count(SourceLine.id)).where(SourceLine.source_release_id==source_id)):
        return {"status":"already_ingested","source_id":source_id}
    path=stored_source_path(sr); diag=parse_source(path, sr.source_format)
    if diagnostics_failed(diag): return {"status":"rejected","diagnostics":{"unknown_lines":diag.unknown_lines,"malformed":diag.malformed}}
    surah_map={}
    for source_order,sn in enumerate(sorted({r.surah_number for r in diag.records}),1):
        row=Surah(source_release_id=source_id,surah_number=sn,source_order=source_order,arabic_name=None,transliterated_name=None,metadata_json={})
        session.add(row); session.flush(); surah_map[sn]=row.id
    line_to_text_unit={}; token_stream=0; cp_stream=0; token_surah_counts={}; text_units=0; tokens_count=0; cps_count=0; graphemes_count=0
    for source_order,r in enumerate(diag.records,1):
        toks=tokenize_reversible(r.text); meta=tokenization_metadata(toks) | {"address_space_notes":"global_numbered_ayah_position is source-release ordered numbered ayah stream; token positions depend on tokenizer_version; codepoint positions are raw source text positions."}
        tu=TextUnit(source_release_id=source_id,surah_id=surah_map[r.surah_number],unit_type="numbered_ayah",surah_number=r.surah_number,ayah_number=r.ayah_number,source_order=source_order,global_numbered_ayah_position=source_order,text_raw=r.text,source_line_number=r.line_number,source_byte_start=r.byte_start,source_byte_end=r.byte_end,metadata_json=meta)
        session.add(tu); session.flush(); line_to_text_unit[r.line_number]=tu.id; text_units += 1
        token_surah_counts.setdefault(r.surah_number,0); token_rows=[]
        for n,t in enumerate(toks,1):
            token_stream += 1; token_surah_counts[r.surah_number]+=1; tokens_count += 1
            tr=OrthographicToken(text_unit_id=tu.id,token_in_unit=n,token_in_surah=token_surah_counts[r.surah_number],token_in_numbered_stream=token_stream,token_in_full_source_stream=token_stream,surface_raw=t["surface_raw"],delimiter_before=t["delimiter_before"],delimiter_after=t.get("delimiter_after",""),start_codepoint_in_unit=t["start_codepoint_in_unit"],end_codepoint_in_unit=t["end_codepoint_in_unit"],start_byte_in_unit=len(r.text[:t["start_codepoint_in_unit"]].encode("utf-8")),end_byte_in_unit=len(r.text[:t["end_codepoint_in_unit"]].encode("utf-8")),tokenizer_version=t["tokenizer_version"])
            session.add(tr); token_rows.append((tr,t))
        session.flush()
        cps=codepoints(r.text); cp_maps=[]
        for cp in cps:
            cp_stream += 1; cps_count += 1
            owner=None; cp_in_token=None
            for tr,t in token_rows:
                if t["start_codepoint_in_unit"] <= cp["codepoint_in_text_unit"] < t["end_codepoint_in_unit"]:
                    owner=tr.id; cp_in_token=cp["codepoint_in_text_unit"]-t["start_codepoint_in_unit"]; break
            cp_maps.append({"text_unit_id":tu.id,"orthographic_token_id":owner,"codepoint_in_text_unit":cp["codepoint_in_text_unit"],"codepoint_in_token":cp_in_token,"codepoint_in_numbered_stream":cp_stream,"codepoint_in_full_source_stream":cp_stream,"character":cp["character"],"unicode_hex":cp["unicode_hex"],"unicode_name":cp["unicode_name"],"general_category":cp["general_category"],"canonical_combining_class":cp["canonical_combining_class"],"is_combining_mark":cp["is_combining_mark"],"is_whitespace":cp["is_whitespace"],"is_punctuation":cp["is_punctuation"],"is_quranic_annotation":cp["is_quranic_annotation"],"metadata_json":{"address_space":"source_release_codepoint_v1"}})
        session.bulk_insert_mappings(UnicodeCodepoint, cp_maps)
        for g in graphemes(r.text):
            graphemes_count += 1
            session.add(GraphemeCluster(text_unit_id=tu.id,orthographic_token_id=None,grapheme_in_text_unit=g["grapheme_in_text_unit"],grapheme_in_token=None,raw_value=g["raw_value"],start_codepoint_in_text_unit=g["start_codepoint_in_text_unit"],end_codepoint_in_text_unit=g["end_codepoint_in_text_unit"],segmentation_version=g["segmentation_version"]))
    for sl in diag.source_lines:
        session.add(SourceLine(source_release_id=source_id,source_line_number=sl.line_number,record_type=sl.record_type,raw_line_content=sl.raw_line_content,line_ending=sl.line_ending,byte_start=sl.byte_start,byte_end=sl.byte_end,classification_reason=sl.classification_reason,parsed_text_unit_id=line_to_text_unit.get(sl.line_number),metadata_json=sl.metadata_json or {}))
    session.commit()
    return {"status":"ingested","source_id":source_id,"surah_rows":len(surah_map),"text_unit_rows":text_units,"source_line_rows":len(diag.source_lines),"token_rows":tokens_count,"codepoint_rows":cps_count,"grapheme_rows":graphemes_count}

def validate_reconstruction(state: dict) -> dict:
    mismatches=[]
    for u in state["units"]:
        from_cp="".join(cp["character"] for cp in u["codepoints"]); from_tok=reconstruct_from_tokens(u["tokens"], u.get("metadata_json",{}).get("final_trailing_delimiter"))
        if from_cp != u["text_raw"] or from_tok != u["text_raw"]:
            mismatches.append({"address":(u["surah_number"],u["ayah_number"]),"text_raw":u["text_raw"],"from_codepoints":from_cp,"from_tokens":from_tok})
    return {"ok":not mismatches,"mismatches":mismatches}

def validate_source_release(session, source_id: int) -> dict:
    sr=session.get(SourceRelease, source_id)
    if sr is None: raise ValueError(f"source_release not found: {source_id}")
    rows=session.scalars(select(SourceLine).where(SourceLine.source_release_id==source_id).order_by(SourceLine.source_line_number)).all()
    reconstructed="".join(r.raw_line_content + r.line_ending for r in rows).encode("utf-8")
    source_bytes=stored_source_path(sr).read_bytes(); source_sha=hashlib.sha256(source_bytes).hexdigest(); reconstructed_sha=hashlib.sha256(reconstructed).hexdigest()
    ayah_bad=[]; token_bad=[]
    tus=session.scalars(select(TextUnit).where(TextUnit.source_release_id==source_id).order_by(TextUnit.global_numbered_ayah_position)).all()
    for tu in tus:
        cps=session.scalars(select(UnicodeCodepoint).where(UnicodeCodepoint.text_unit_id==tu.id).order_by(UnicodeCodepoint.codepoint_in_text_unit)).all()
        if "".join(c.character for c in cps) != tu.text_raw: ayah_bad.append(tu.id)
        toks=session.scalars(select(OrthographicToken).where(OrthographicToken.text_unit_id==tu.id).order_by(OrthographicToken.token_in_unit)).all()
        if "".join(t.delimiter_before+t.surface_raw+t.delimiter_after for t in toks)+tu.metadata_json.get("final_trailing_delimiter","") != tu.text_raw: token_bad.append(tu.id)
    return {"ok":source_bytes==reconstructed and not ayah_bad and not token_bad,"source_sha256":source_sha,"reconstructed_sha256":reconstructed_sha,"byte_identical":source_bytes==reconstructed,"codepoint_text_mismatches":ayah_bad[:5],"token_text_mismatches":token_bad[:5],"line_rows":len(rows),"text_unit_rows":len(tus)}
