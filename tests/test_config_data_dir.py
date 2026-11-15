"""The data directory setting: CYNO_DATA_DIR, with the pre-rename POLLO_DATA_DIR still honoured."""

from pathlib import Path

import pytest

from web.core import config


class _WarningLog:
    """Stands in for the module logger, so the test doesn't depend on global logging setup."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, msg: str) -> None:
        """Record a warning."""
        self.messages.append(msg)


def test_cyno_data_dir_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CYNO_DATA_DIR sets the data directory."""
    monkeypatch.setenv("CYNO_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_legacy_pollo_data_dir_still_works_with_a_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that an existing deployment's POLLO_DATA_DIR keeps pointing at its data (and says to rename it)."""
    warned = _WarningLog()
    monkeypatch.setattr(config, "log", warned)
    monkeypatch.delenv("CYNO_DATA_DIR", raising=False)
    monkeypatch.setenv("POLLO_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert any("CYNO_DATA_DIR" in m for m in warned.messages)


def test_new_name_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CYNO_DATA_DIR beats the legacy name."""
    monkeypatch.setenv("CYNO_DATA_DIR", str(tmp_path / "new"))
    monkeypatch.setenv("POLLO_DATA_DIR", str(tmp_path / "old"))
    assert config.data_dir() == tmp_path / "new"


def test_defaults_to_the_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that with neither variable set the repo root is the data directory."""
    monkeypatch.delenv("CYNO_DATA_DIR", raising=False)
    monkeypatch.delenv("POLLO_DATA_DIR", raising=False)
    assert (config.data_dir() / "pyproject.toml").is_file()
