import json
from pathlib import Path

import yaml

from quran_analysis import ResearchQuery, __version__
from quran_analysis.presentation import render_research, emit_research

ROOT = Path(__file__).parents[1]


def test_public_versions_examples_notebooks_and_citation_are_parseable(tmp_path):
    assert __version__ == "1.1.0"
    assert 'version = "1.1.0"' in (ROOT / "pyproject.toml").read_text()
    for path in (ROOT / "examples/research").iterdir():
        if path.suffix == ".json":
            value = json.loads(path.read_text())
            if value.get("schema") == "research-query-v1":
                ResearchQuery.from_dict(value)
        elif path.suffix == ".yaml":
            assert yaml.safe_load(path.read_text())["schema"].startswith("research-")
    index = yaml.safe_load((ROOT / "examples/research-index.yaml").read_text())
    assert all((ROOT / "examples/research" / item["file"]).exists() for item in index["examples"])
    yaml.safe_load((ROOT / "CITATION.cff").read_text())
    for path in (ROOT / "notebooks").glob("*.ipynb"):
        notebook = json.loads(path.read_text())
        assert notebook["nbformat"] == 4
        assert any(cell["cell_type"] == "code" for cell in notebook["cells"])


def test_research_presentations_are_deterministic_unicode_and_path_only(tmp_path):
    payload = {"matches": [{"token": "ٱللَّهِ", "evidence": {"source": "QAC"}}]}
    for format in ("csv", "json", "jsonl", "yaml", "markdown", "text"):
        assert render_research(payload, format) == render_research(payload, format)
    target = tmp_path / "result.csv"
    assert emit_research(payload, "csv", target) == ""
    assert target.read_bytes() == render_research(payload, "csv").encode("utf-8")
    assert "evidence" in target.read_text()
    assert render_research({"matches": []}, "csv") == "\n"
