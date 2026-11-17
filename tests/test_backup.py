"""Scheduled database backups: a real, restorable copy; pruning; the schedule."""

import os
import sqlite3
from pathlib import Path

import pytest

from web.core import backup
from web.core.metadata import get_db


def test_backup_is_a_readable_copy(tmp_path: Path) -> None:
    """Test that a backup is a complete SQLite database with the app's tables."""
    path = backup.run_backup(tmp_path)
    assert path.parent == tmp_path
    assert path.name.startswith(backup.PREFIX)
    assert not list(tmp_path.glob("*.partial"))
    with sqlite3.connect(path) as conn:
        found = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'chat_conversations'").fetchall()
    assert len(found) == 1
    assert get_db().db_path != path


def test_backup_prunes_to_the_newest(tmp_path: Path) -> None:
    """Test that only the newest `keep` backups survive."""
    for stamp in ("20240101-000000", "20240102-000000", "20240103-000000"):
        (tmp_path / f"{backup.PREFIX}{stamp}{backup.SUFFIX}").write_bytes(b"x")
    newest = backup.run_backup(tmp_path, keep=2)
    kept = backup.list_backups(tmp_path)
    assert [p.name for p in kept][-1] == newest.name
    assert len(kept) == 2


def test_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the defaults, a custom value, off, and garbage falling back to the default."""
    assert backup.interval_seconds() == 24 * 3600
    assert backup.keep_count() == backup.DEFAULT_KEEP
    monkeypatch.setenv("BACKUP_INTERVAL_HOURS", "0")
    monkeypatch.setenv("BACKUP_KEEP", "0")
    assert backup.interval_seconds() == 0
    assert backup.keep_count() == 1
    monkeypatch.setenv("BACKUP_INTERVAL_HOURS", "soon")
    assert backup.interval_seconds() == 24 * 3600


def test_off_starts_no_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that BACKUP_INTERVAL_HOURS=0 starts nothing."""
    monkeypatch.setenv("BACKUP_INTERVAL_HOURS", "0")
    assert backup.start_backups() is None


def test_due_time_counts_the_newest_backup(tmp_path: Path) -> None:
    """Test that a restart doesn't reset the clock, and a first run is soon."""
    assert backup.seconds_until_due(3600, tmp_path) == 60.0
    newest = tmp_path / f"{backup.PREFIX}20240101-000000{backup.SUFFIX}"
    newest.write_bytes(b"x")
    os.utime(newest, (0, 0))
    assert backup.seconds_until_due(3600, tmp_path) == 60.0  # ancient: due now
    os.utime(newest)
    assert 3000 < backup.seconds_until_due(3600, tmp_path) <= 3600
