import hashlib
import json

import regex
TOKENIZER_VERSION="whitespace-spans-v1"
TOKENIZER_CONFIGURATION={"algorithm":"split on str.isspace false runs","span_unit":"python_unicode_codepoint_index","delimiter_policy":"delimiter_before"}
TOKENIZER_CONFIGURATION_SHA256=hashlib.sha256(json.dumps(TOKENIZER_CONFIGURATION,sort_keys=True,separators=(",", ":")).encode()).hexdigest()

def tokenize_reversible(text: str) -> list[dict]:
    out=[]; delimiter=""; token=""; start=None
    for i,ch in enumerate(text):
        if ch.isspace():
            if token:
                out.append({"surface_raw":token,"delimiter_before":delimiter,"delimiter_after":"","start_codepoint_in_unit":start,"end_codepoint_in_unit":i,"tokenizer_version":TOKENIZER_VERSION})
                token=""; delimiter=ch; start=None
            else:
                delimiter += ch
        else:
            if not token: start=i
            token += ch
    if token:
        out.append({"surface_raw":token,"delimiter_before":delimiter,"delimiter_after":"","start_codepoint_in_unit":start,"end_codepoint_in_unit":len(text),"tokenizer_version":TOKENIZER_VERSION,"final_trailing_delimiter":""})
    elif out:
        out[-1]["final_trailing_delimiter"] = delimiter
    return out

def reconstruct_from_tokens(tokens: list[dict], final_trailing_delimiter: str | None = None) -> str:
    if final_trailing_delimiter is None:
        final_trailing_delimiter = tokens[-1].get("final_trailing_delimiter", "") if tokens else ""
    return "".join(t["delimiter_before"]+t["surface_raw"]+t.get("delimiter_after", "") for t in tokens) + final_trailing_delimiter

def tokenization_metadata(tokens: list[dict]) -> dict:
    return {"tokenizer_version": TOKENIZER_VERSION, "delimiter_ownership": "token owns delimiter_before; text_unit metadata owns final_trailing_delimiter", "final_trailing_delimiter": tokens[-1].get("final_trailing_delimiter", "") if tokens else ""}

def graphemes(text: str) -> list[dict]:
    out=[]
    for idx,m in enumerate(regex.finditer(r"\X", text),1):
        out.append({"grapheme_in_text_unit":idx,"raw_value":m.group(0),"start_codepoint_in_text_unit":m.start(),"end_codepoint_in_text_unit":m.end(),"segmentation_version":"regex-\\X"})
    return out
