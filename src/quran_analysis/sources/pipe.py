from dataclasses import dataclass
from collections import Counter, defaultdict
import unicodedata

TANZIL_ADAPTER_NAME = "tanzil-text-with-ayah-numbers-v1"
SUPPORTED_FORMATS = {"pipe-ayah-v1", TANZIL_ADAPTER_NAME}

@dataclass(frozen=True)
class SourceLineRecord:
    line_number: int
    record_type: str
    raw_line_content: str
    line_ending: str
    byte_start: int
    byte_end: int
    classification_reason: str
    surah_number: int | None = None
    ayah_number: int | None = None
    text: str | None = None
    metadata_json: dict | None = None

@dataclass(frozen=True)
class PipeAyahRecord:
    line_number: int
    surah_number: int
    ayah_number: int
    text: str
    byte_start: int = 0
    byte_end: int = 0
    line_ending: str = ""

@dataclass(frozen=True)
class PipeDiagnostics:
    records: list[PipeAyahRecord]
    source_lines: list[SourceLineRecord]
    malformed: list[dict]
    empty_text: list[int]
    duplicate_addresses: list[dict]
    invalid_numeric: list[dict]
    unknown_lines: list[dict]
    surah_count: int
    numbered_ayah_count: int
    non_quran_record_count: int
    classifications: dict[str, int]
    first_address: tuple[int, int] | None
    last_address: tuple[int, int] | None
    gaps_in_ayah_numbering: list[dict]
    surah_order_gaps_reversals: list[dict]
    unicode_inventory: list[dict]
    newline_inventory: dict[str, int]

def split_source_bytes(data: bytes) -> list[tuple[str, str, int, int]]:
    out=[]; start=0; i=0
    while i < len(data):
        if data[i:i+2] == b"\r\n":
            raw=data[start:i].decode("utf-8"); out.append((raw,"\r\n",start,i+2)); i += 2; start = i
        elif data[i:i+1] == b"\n":
            raw=data[start:i].decode("utf-8"); out.append((raw,"\n",start,i+1)); i += 1; start = i
        elif data[i:i+1] == b"\r":
            raw=data[start:i].decode("utf-8"); out.append((raw,"\r",start,i+1)); i += 1; start = i
        else:
            i += 1
    if start < len(data):
        out.append((data[start:].decode("utf-8"),"",start,len(data)))
    elif not data:
        return []
    return out

def _footer_type(line: str) -> tuple[str, str]:
    if line == "":
        return "blank", "empty source line"
    if not line.startswith("#"):
        return "unknown", "non-ayah line is not blank or comment"
    lower = line.lower()
    if any(s in lower for s in ("copyright", "license", "terms of use", "permission is granted", "changing it is not allowed", "copyright notice", "verbatim copies", "derived from", "website or application", "reproduced appropriately")):
        return "license", "confirmed Tanzil copyright/license footer line"
    if any(s in lower for s in ("tanzil quran text", "tanzil project", "tanzil.net", "verified", "specialists", "updates", "this copy of the quran text")):
        return "source_metadata", "confirmed Tanzil source metadata/attribution footer line"
    return "comment", "comment line"

def parse_tanzil_text_with_ayah_numbers_v1(data: bytes) -> PipeDiagnostics:
    records=[]; source_lines=[]; malformed=[]; empty=[]; invalid=[]; unknown=[]; seen={}; duplicates=[]; inv=Counter(); cats={}; classes=Counter(); newline_inv=Counter()
    for i,(line,ending,start,end) in enumerate(split_source_bytes(data),1):
        newline_inv[{"\n":"LF","\r\n":"CRLF","\r":"CR","":"none"}[ending]] += 1
        parts=line.split("|",2)
        if len(parts)==3 and parts[0].isdecimal() and parts[1].isdecimal():
            s=int(parts[0]); a=int(parts[1]); body=parts[2]
            if s <= 0 or a <= 0:
                invalid.append({"line_number":i,"surah":parts[0],"ayah":parts[1]})
                rtype="unknown"; reason="ayah address numbers must be positive"
            else:
                if body == "": empty.append(i)
                key=(s,a)
                if key in seen: duplicates.append({"address":key,"first_line":seen[key],"duplicate_line":i})
                else: seen[key]=i
                records.append(PipeAyahRecord(i,s,a,body,start,end,ending))
                rtype="ayah_record"; reason="surah|ayah|text record"
                for ch in body:
                    hx=f"U+{ord(ch):04X}"; inv[hx]+=1; cats[hx]=(ch,unicodedata.name(ch,"<unassigned>"),unicodedata.category(ch))
            source_lines.append(SourceLineRecord(i,rtype,line,ending,start,end,reason,s if rtype=="ayah_record" else None,a if rtype=="ayah_record" else None,body if rtype=="ayah_record" else None,{}))
            classes[rtype]+=1
            continue
        if "|" in line and not line.startswith("#") and line != "":
            malformed.append({"line_number":i,"reason":"expected surah|ayah|text with positive numeric address or confirmed non-Quran record"})
            rtype="unknown"; reason="malformed ayah-like line"
        else:
            rtype, reason = _footer_type(line)
        if rtype == "unknown": unknown.append({"line_number":i,"raw_line_content":line,"reason":reason})
        source_lines.append(SourceLineRecord(i,rtype,line,ending,start,end,reason,None,None,None,{})); classes[rtype]+=1
    by_surah=defaultdict(list)
    for r in records: by_surah[r.surah_number].append(r.ayah_number)
    gaps=[]
    for s, ayahs in by_surah.items():
        uniq=sorted(set(ayahs)); missing=[n for n in range(uniq[0], uniq[-1]+1) if n not in set(uniq)] if uniq else []
        if missing: gaps.append({"surah_number":s,"missing_ayah_numbers":missing})
    order=[]; last=None
    for r in records:
        if last is not None and r.surah_number < last:
            order.append({"line_number":r.line_number,"previous_surah":last,"current_surah":r.surah_number,"type":"reversal"})
        last=r.surah_number
    surahs=sorted(set(by_surah)); missing_surahs=[n for n in range(surahs[0], surahs[-1]+1) if n not in set(surahs)] if surahs else []
    if missing_surahs: order.append({"type":"gap","missing_surah_numbers":missing_surahs})
    inventory=[{"unicode_hex":k,"character":cats[k][0],"unicode_name":cats[k][1],"general_category":cats[k][2],"count":v} for k,v in sorted(inv.items())]
    return PipeDiagnostics(records,source_lines,malformed,empty,duplicates,invalid,unknown,len(by_surah),len(records),len(source_lines)-len(records),dict(classes),(records[0].surah_number,records[0].ayah_number) if records else None,(records[-1].surah_number,records[-1].ayah_number) if records else None,gaps,order,inventory,dict(newline_inv))

def parse_pipe_ayah_v1(text: str) -> PipeDiagnostics:
    return parse_tanzil_text_with_ayah_numbers_v1(text.encode("utf-8"))

def parse_source(path, fmt: str) -> PipeDiagnostics:
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unrecognized source format: {fmt}")
    return parse_tanzil_text_with_ayah_numbers_v1(path.read_bytes())

def diagnostics_failed(d: PipeDiagnostics) -> bool:
    return bool(d.malformed or d.invalid_numeric or d.duplicate_addresses or d.empty_text or d.unknown_lines)
