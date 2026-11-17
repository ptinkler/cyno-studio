"""Scrub expired upload URLs from stored requests (media cards, library items and request logs), hourly."""

import logging
import threading

from web.core import request_log
from web.core.metadata import get_db

log = logging.getLogger(__name__)

PLACEHOLDER = "(expired upload)"
INTERVAL_SECONDS = 3600
FIRST_RUN_SECONDS = 120


def purge_expired() -> int:
    """Blank every expired upload URL wherever it was stored; returns how many URLs."""
    db = get_db()
    urls = db.expired_hosted_uploads()
    if urls:
        request_log.scrub_urls(urls, PLACEHOLDER)
        db.scrub_hosted_uploads(urls, PLACEHOLDER)
        log.info("scrubbed %d expired upload URL(s)", len(urls))
    return len(urls)


def _loop(stop: threading.Event) -> None:
    wait = FIRST_RUN_SECONDS
    while not stop.wait(wait):
        wait = INTERVAL_SECONDS
        try:
            purge_expired()
        except Exception:  # one bad pass must not stop the next
            log.exception("expired-upload cleanup failed")


def start_cleanup() -> threading.Event:
    """Start the cleanup thread; returns the event that stops it."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="upload-cleanup").start()
    return stop
