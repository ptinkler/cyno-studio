"""Expired upload URLs are blanked from stored media and request logs, and live ones are left alone."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.stubs import stub
from web.core import config
from web.core.metadata import MetadataDB
from web.uploads import cleanup, hosts
from web.uploads.settings import UploadPrefs

pytest_plugins = ["tests.chat_fixtures"]

DEAD = "https://litter.example/dead.png"
LIVE = "https://litter.example/live.png"


def _now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


def _message_with(db: MetadataDB, url: str) -> int:
    conv = db.create_conversation()
    msg = db.add_chat_message(conv.id, "assistant", media=[{"id": "m1", "log": {"request": {"image": url}}}])
    return msg.id


@pytest.mark.usefixtures("chat")
def test_only_expired_urls_are_scrubbed(db: MetadataDB, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a dead URL is replaced in messages and logs, the live one stays, and the row is forgotten."""
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    logs = tmp_path / "logs" / "u1"
    logs.mkdir(parents=True)
    (logs / "requests.jsonl").write_text(f'{{"request": "{DEAD}"}}\n{{"request": "{LIVE}"}}\n', encoding="utf-8")
    db.record_hosted_upload(DEAD, _now() - timedelta(minutes=1))
    db.record_hosted_upload(LIVE, _now() + timedelta(hours=1))
    dead_msg, live_msg = _message_with(db, DEAD), _message_with(db, LIVE)

    assert cleanup.purge_expired() == 1

    texts = {m.id: m.media_json or "" for m in db.get_chat_messages_by_ids([dead_msg, live_msg])}
    assert DEAD not in texts[dead_msg]
    assert cleanup.PLACEHOLDER in texts[dead_msg]
    assert LIVE in texts[live_msg]
    log_text = (logs / "requests.jsonl").read_text(encoding="utf-8")
    assert DEAD not in log_text
    assert LIVE in log_text
    assert db.expired_hosted_uploads() == []


@pytest.mark.usefixtures("chat")
def test_nothing_expired_does_nothing() -> None:
    """Test that with no expired URLs nothing is touched."""
    assert cleanup.purge_expired() == 0


@pytest.mark.usefixtures("chat")
def test_upload_records_when_the_host_drops_it(db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an upload is remembered with the host's real retention (tmpfiles keeps files an hour)."""
    seen: dict[str, datetime] = {}

    def record(url: str, at: datetime) -> None:
        seen[url] = at

    monkeypatch.setattr(hosts, "_dispatch", stub(lambda: DEAD))
    monkeypatch.setattr(hosts, "_served_url", stub(lambda: DEAD))
    monkeypatch.setattr(db, "record_hosted_upload", record)
    prefs = UploadPrefs(primary="tmpfiles", backup=None, expiry_minutes=720, selfhost_base="")
    assert hosts.upload_file(Path("f"), prefs) == DEAD
    assert timedelta(minutes=59) < seen[DEAD] - _now() <= timedelta(minutes=60)
