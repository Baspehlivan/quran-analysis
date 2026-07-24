from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from quran_analysis.annotation_sources.capabilities import UnsupportedDimensionError
from quran_analysis.research import ResearchBoolean, ResearchPredicate, ResearchQuery, ResearchQueryError


def test_research_ast_is_immutable_and_canonicalizes_commutative_nesting():
    root = {"dimension": "root", "operator": "eq", "value": "smw"}
    pos = {"dimension": "pos", "operator": "eq", "value": "N"}
    first = ResearchQuery.from_dict({"where": {"and": [root, pos]}})
    second = ResearchQuery.from_dict({"where": {"and": [pos, {"and": [root]}]}})
    assert first.dumps() == second.dumps()
    with pytest.raises(FrozenInstanceError):
        first.limit = 2  # type: ignore[misc]


def test_research_ast_requires_explicit_boolean_shape_and_valid_dimensions():
    with pytest.raises(ResearchQueryError):
        ResearchQuery.loads('{"where":{"root":"smw"}}')
    with pytest.raises(ResearchQueryError):
        ResearchQuery.loads('{"where":{"not":[{"dimension":"root","operator":"eq","value":"smw"},{"dimension":"pos","operator":"eq","value":"N"}]}}')
    with pytest.raises(UnsupportedDimensionError) as error:
        ResearchPredicate("page", "eq", 1)
    assert error.value.to_dict()["code"] == "unsupported_dimension"


def test_research_json_yaml_round_trip_and_bounds():
    query = ResearchQuery(ResearchBoolean("or", (ResearchPredicate("token", "prefix", "ب"), ResearchPredicate("feature", "eq", "POS:N"))), limit=3, offset=1)
    assert ResearchQuery.loads(query.dumps("json")) == query.canonical()
    assert ResearchQuery.loads(query.dumps("yaml"), "yaml") == query.canonical()
    with pytest.raises(ResearchQueryError, match="between"):
        ResearchQuery(ResearchPredicate("root", "eq", "smw"), limit=501)
