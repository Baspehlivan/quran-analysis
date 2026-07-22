from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from typing import Any

QURANIC_ANNOTATION_RANGES = [(0x0610, 0x061A), (0x06D6, 0x06ED), (0x08D4, 0x08E1), (0x08E3, 0x08FF)]
ALIF_VARIANTS = {"آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا", "ٲ": "ا", "ٳ": "ا", "ٵ": "ا"}

PROFILES: dict[str, dict[str, Any]] = {
    "identity_v1": {
        "name": "identity",
        "version": "v1",
        "description": "Neutral no-op profile; preserves every codepoint as-is.",
        "configuration": {"profile_id": "identity_v1", "operations": [{"type": "identity"}]},
    },
    "remove_combining_marks_v1": {
        "name": "remove_combining_marks",
        "version": "v1",
        "description": "Neutral Unicode category operation dropping codepoints whose general category starts with M.",
        "configuration": {"profile_id": "remove_combining_marks_v1", "operations": [{"type": "drop_general_category_prefix", "prefix": "M"}]},
    },
    "normalize_alif_variants_v1": {
        "name": "normalize_alif_variants",
        "version": "v1",
        "description": "Neutral explicit codepoint substitution for configured Arabic alif-shaped codepoints.",
        "configuration": {"profile_id": "normalize_alif_variants_v1", "operations": [{"type": "replace_codepoints", "mapping": ALIF_VARIANTS}]},
    },
    "remove_quranic_annotations_v1": {
        "name": "remove_quranic_annotations",
        "version": "v1",
        "description": "Neutral Unicode-range operation dropping configured Quranic annotation codepoint ranges.",
        "configuration": {"profile_id": "remove_quranic_annotations_v1", "operations": [{"type": "drop_codepoint_ranges", "ranges": QURANIC_ANNOTATION_RANGES}]},
    },
    "base_arabic_letters_v1": {
        "name": "base_arabic_letters",
        "version": "v1",
        "description": "Neutral pipeline: drop combining marks and configured Quranic annotations, then replace configured alif variants.",
        "configuration": {
            "profile_id": "base_arabic_letters_v1",
            "operations": [
                {"type": "drop_general_category_prefix", "prefix": "M"},
                {"type": "drop_codepoint_ranges", "ranges": QURANIC_ANNOTATION_RANGES},
                {"type": "replace_codepoints", "mapping": ALIF_VARIANTS},
            ],
        },
    },
}

for _profile_id, _profile in PROFILES.items():
    _profile["id"] = _profile_id
    _profile["configuration_sha256"] = hashlib.sha256(json.dumps(_profile["configuration"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    _profile["immutable"] = True


def config_sha256(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def profile_hashes() -> dict[str, str]:
    return {profile_id: profile["configuration_sha256"] for profile_id, profile in PROFILES.items()}


def get_profile(profile_id: str) -> dict[str, Any]:
    if profile_id not in PROFILES:
        raise ValueError(f"unsupported normalization profile: {profile_id}")
    return deepcopy(PROFILES[profile_id])


def _is_in_ranges(ch: str, ranges: list[list[int] | tuple[int, int]]) -> bool:
    cp = ord(ch)
    return any(start <= cp <= end for start, end in ranges)


def normalize_token(value: str, profile: str, source_codepoint_ids: list[int] | None = None) -> dict[str, Any]:
    p = get_profile(profile)
    chars = [{"character": ch, "source_indices": [i], "source_codepoint_ids": [source_codepoint_ids[i]] if source_codepoint_ids else []} for i, ch in enumerate(value)]
    log: list[dict[str, Any]] = []
    for op_index, op in enumerate(p["configuration"]["operations"]):
        next_chars = []
        for current_index, item in enumerate(chars):
            ch = item["character"]
            action = "keep"
            output = ch
            reason = None
            if op["type"] == "identity":
                pass
            elif op["type"] == "drop_general_category_prefix" and unicodedata.category(ch).startswith(op["prefix"]):
                action = "drop"; output = ""; reason = f"general_category_prefix:{op['prefix']}"
            elif op["type"] == "drop_codepoint_ranges" and _is_in_ranges(ch, op["ranges"]):
                action = "drop"; output = ""; reason = "configured_codepoint_range"
            elif op["type"] == "replace_codepoints" and ch in op["mapping"]:
                action = "replace"; output = op["mapping"][ch]; reason = "configured_codepoint_mapping"
            elif op["type"] not in {"identity", "drop_general_category_prefix", "drop_codepoint_ranges", "replace_codepoints"}:
                raise ValueError(f"unsupported normalization operation: {op['type']}")
            entry = {
                "operation_index": op_index,
                "operation": op["type"],
                "input_index": current_index,
                "source_indices": item["source_indices"],
                "source_codepoint_ids": item["source_codepoint_ids"],
                "input_character": ch,
                "action": action,
                "output_character": output,
            }
            if reason:
                entry["reason"] = reason
            if action != "drop":
                entry["output_index"] = len(next_chars)
                next_chars.append({"character": output, "source_indices": item["source_indices"], "source_codepoint_ids": item["source_codepoint_ids"]})
            log.append(entry)
        chars = next_chars
    mapping = [item["source_codepoint_ids"] or item["source_indices"] for item in chars]
    return {
        "profile_id": profile,
        "profile_configuration_sha256": p["configuration_sha256"],
        "normalized_value": "".join(item["character"] for item in chars),
        "transformation_log": log,
        "normalized_to_source_codepoint_ids": mapping,
    }
