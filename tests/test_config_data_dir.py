"""The data directory setting: CYNO_DATA_DIR, else the repo root."""

from pathlib import Path

import pytest

from web.core import config


def test_cyno_data_dir_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CYNO_DATA_DIR sets the data directory."""
    monkeypatch.setenv("CYNO_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_defaults_to_the_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that with neither variable set the repo root is the data directory."""
    monkeypatch.delenv("CYNO_DATA_DIR", raising=False)
    assert (config.data_dir() / "pyproject.toml").is_file()
