"""The data directory setting (CYNO_DATA_DIR, else the repo root) and the folders that can be moved out of it."""

from pathlib import Path

import pytest

from web.core import config
from web.media import cache, paths


def test_cyno_data_dir_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CYNO_DATA_DIR sets the data directory."""
    monkeypatch.setenv("CYNO_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_defaults_to_the_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that with neither variable set the repo root is the data directory."""
    monkeypatch.delenv("CYNO_DATA_DIR", raising=False)
    assert (config.data_dir() / "pyproject.toml").is_file()


def test_cache_dir_defaults_inside_the_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that without CYNO_CACHE_DIR the cache folder is <data dir>/cache, read at call time."""
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    assert config.cache_dir() == tmp_path / "cache"


def test_cache_dir_can_be_moved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CYNO_CACHE_DIR relocates the cache folder."""
    monkeypatch.setenv("CYNO_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert config.cache_dir() == tmp_path / "elsewhere"


def test_backup_dir_defaults_and_can_be_moved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that the backup folder is <data dir>/backups unless CYNO_BACKUP_DIR says otherwise."""
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    assert config.backup_dir() == tmp_path / "backups"
    monkeypatch.setenv("CYNO_BACKUP_DIR", str(tmp_path / "off-host"))
    assert config.backup_dir() == tmp_path / "off-host"


def test_media_caches_follow_the_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that thumbnails and the duration cache live under CYNO_CACHE_DIR, not under the data dir."""
    monkeypatch.setenv("CYNO_CACHE_DIR", str(tmp_path / "fast"))
    assert paths.thumb_dir() == tmp_path / "fast" / "media-thumbs"
    assert cache.db_path() == tmp_path / "fast" / "media-cache.sqlite"
