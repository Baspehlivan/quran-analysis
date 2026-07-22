import unicodedata

def codepoints(text: str) -> list[dict]:
    out=[]
    for i,ch in enumerate(text):
        cat=unicodedata.category(ch)
        out.append({'codepoint_in_text_unit':i,'character':ch,'unicode_hex':f'U+{ord(ch):04X}','unicode_name':unicodedata.name(ch,'<unassigned>'),'general_category':cat,'canonical_combining_class':unicodedata.combining(ch),'is_combining_mark':cat.startswith('M'),'is_whitespace':ch.isspace(),'is_punctuation':cat.startswith('P'),'is_quranic_annotation':0x06D6 <= ord(ch) <= 0x06ED})
    return out
