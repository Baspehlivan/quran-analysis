from pathlib import Path


def test_placeholder_phase1_file_exists():
    assert Path('pyproject.toml').exists()
