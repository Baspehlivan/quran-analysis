import json

from quran_analysis.normalization.profiles import PROFILES, get_profile, normalize_token
from quran_analysis.provenance import stable_hash
from quran_analysis.tokenization.core import reconstruct_from_tokens, tokenize_reversible


def test_phase2a_profiles_are_explicit_and_hashed():
    assert {"identity_v1", "remove_combining_marks_v1", "normalize_alif_variants_v1", "remove_quranic_annotations_v1", "base_arabic_letters_v1"} <= set(PROFILES)
    hashes = {p["configuration_sha256"] for p in PROFILES.values()}
    assert len(hashes) == len(PROFILES)
    assert all(len(h) == 64 for h in hashes)


def test_normalized_character_mapping_and_log_complete():
    result = normalize_token("أَ", "base_arabic_letters_v1", [101, 102])
    assert result["normalized_value"] == "ا"
    assert result["normalized_to_source_codepoint_ids"] == [[101]]
    assert {entry["action"] for entry in result["transformation_log"]} >= {"replace", "drop"}
    assert all("source_codepoint_ids" in entry for entry in result["transformation_log"])


def test_profile_getter_returns_copy_for_immutability():
    profile = get_profile("identity_v1")
    profile["configuration"]["operations"].append({"type": "mutated"})
    assert get_profile("identity_v1")["configuration"]["operations"] == [{"type": "identity"}]


def test_query_hash_stable_for_json_round_trip():
    payload = {"value": "abc", "nested": {"b": 2, "a": 1}}
    assert stable_hash(payload) == stable_hash(json.loads(json.dumps(payload)))


def test_reversible_tokenization_generated_arabic_marks_sample():
    text = "اَ بْ  ت"
    assert reconstruct_from_tokens(tokenize_reversible(text)) == text
