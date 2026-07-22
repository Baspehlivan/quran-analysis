import hashlib
import json

def canonical_scope(config: dict) -> dict:
    return json.loads(json.dumps(config, sort_keys=True))
def scope_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(canonical_scope(config),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def numbered_only() -> dict:
    return {'unit_types':['numbered_ayah'],'include_surahs':None,'exclude_surahs':[],'exact_ayahs':[],'ayah_ranges':[],'source_order_ranges':[],'ordered_unit_ids':None}
