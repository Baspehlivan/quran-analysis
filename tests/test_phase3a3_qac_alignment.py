from __future__ import annotations

from quran_analysis.annotation_sources.alignment import decide


def test_direct_match_uses_source_native_representation():
    result = decide({"locator": {"surah": 1, "ayah": 1, "token": 1}, "form": "بِسْمِ"}, [{"id": 7, "surface_raw": "بِسْمِ"}])
    assert result[0]["method"] == "DIRECT"
    assert result[0]["token_id"] == 7


def test_multiple_segments_can_map_to_one_token():
    candidate = [{"id": 7, "surface_raw": "بِسْمِ"}]
    first = decide({"locator": {"surah": 1, "ayah": 1, "token": 1}, "form": "بِ"}, candidate)
    second = decide({"locator": {"surah": 1, "ayah": 1, "token": 1}, "form": "سْمِ"}, candidate)
    assert first[0]["token_id"] == second[0]["token_id"] == 7
    assert first[0]["method"] == second[0]["method"] == "DIRECT"


def test_unmatched_segment_is_explicit():
    result = decide({"locator": {"surah": 1, "ayah": 1, "token": 99}, "form": "x"}, [])
    assert result[0]["method"] == "UNMATCHED"
    assert result[0]["token_id"] is None


def test_ambiguous_candidates_are_all_preserved():
    result = decide({"locator": {"surah": 1, "ayah": 1, "token": 1}, "form": "x"}, [{"id": 7, "surface_raw": "x"}, {"id": 8, "surface_raw": "x"}])
    assert {item["token_id"] for item in result} == {7, 8}
    assert {item["method"] for item in result} == {"AMBIGUOUS"}


def test_named_normalization_is_provenanced():
    result = decide({"locator": {"surah": 1, "ayah": 1, "token": 1}, "form": "أ"}, [{"id": 7, "surface_raw": "ا"}])
    assert result[0]["method"] == "NORMALIZED"
    assert result[0]["evidence"]["normalization_profile"] == "base_arabic_letters_v1"
