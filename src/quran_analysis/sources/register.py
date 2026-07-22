import hashlib
import json
import re
import unicodedata
from pathlib import Path
from quran_analysis.config import settings
from quran_analysis.sources.pipe import parse_source, diagnostics_failed

def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()

def normalization_booleans(text: str) -> dict[str, bool]:
    return {f"is_normalized_{form}": unicodedata.is_normalized(form, text) for form in ("NFC", "NFD", "NFKC", "NFKD")}

def diagnostics_to_json(d):
    return {
        "malformed": d.malformed,
        "empty_text": d.empty_text,
        "duplicate_addresses": d.duplicate_addresses,
        "invalid_numeric": d.invalid_numeric,
        "unknown_lines": d.unknown_lines,
        "observed_surah_count": d.surah_count,
        "quran_record_count": d.numbered_ayah_count,
        "non_quran_record_count": d.non_quran_record_count,
        "classifications": d.classifications,
        "first_address": d.first_address,
        "last_address": d.last_address,
        "gaps_in_ayah_numbering": d.gaps_in_ayah_numbering,
        "surah_order_gaps_reversals": d.surah_order_gaps_reversals,
        "unicode_inventory": d.unicode_inventory,
        "newline_inventory": d.newline_inventory,
    }

def inspect_source(path: Path, fmt: str) -> dict:
    d=parse_source(path,fmt)
    return diagnostics_to_json(d) | {"failed": diagnostics_failed(d)}

def register_source(path: Path, name: str, version: str, fmt: str, data_dir: Path | None=None) -> dict:
    if not path.exists(): raise FileNotFoundError(path)
    data=path.read_bytes(); text=data.decode("utf-8"); sha=hashlib.sha256(data).hexdigest(); d=parse_source(path,fmt)
    if diagnostics_failed(d):
        return {"status":"rejected","diagnostics":diagnostics_to_json(d)}
    base=data_dir or settings.data_dir; raw=base/"raw"; manifests=base/"manifests"; raw.mkdir(parents=True,exist_ok=True); manifests.mkdir(parents=True,exist_ok=True)
    stored=f"{safe_name(name)}_{safe_name(version)}_{safe_name(fmt)}_{sha}.txt"; target=raw/stored
    if not target.exists(): target.write_bytes(data)
    elif target.read_bytes()!=data: raise RuntimeError("deterministic raw target exists with different bytes")
    non_quran=[{"line_number":r.line_number,"record_type":r.record_type,"raw_line_content":r.raw_line_content,"line_ending":r.line_ending,"byte_start":r.byte_start,"byte_end":r.byte_end,"classification_reason":r.classification_reason} for r in d.source_lines if r.record_type != "ayah_record"]
    manifest={
        "source_name":name,"source_version":version,"adapter":fmt,"adapter_version":fmt,"source_format":fmt,
        "original_path":str(path),"original_filename":path.name,"stored_path":str(target),"stored_filename":stored,"encoding":"utf-8",
        "sha256":sha,"byte_size":len(data),"line_count":len(d.source_lines),"newline_inventory":d.newline_inventory,
        "quran_record_count":d.numbered_ayah_count,"non_quran_record_count":d.non_quran_record_count,"non_quran_records":non_quran,
        "classifications":d.classifications,**normalization_booleans(text),"diagnostics":diagnostics_to_json(d)
    }
    mpath=manifests/f"{stored}.manifest.json"; mpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    manifest["manifest_path"]=str(mpath)
    return {"status":"registered","manifest":manifest}
