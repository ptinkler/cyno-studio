"""Shared configuration — single source of truth for data paths and API settings.

All modules that need ROOT_DIR, ASSETS_DIR, DB_PATH, or API constants should
import from here instead of computing them independently.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (the repo directory)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # src/py/web/core/config.py

# The one .env load for the whole app, by absolute path (so it doesn't depend
# on the working directory) and WITHOUT override: a variable already in the
# environment — docker-compose's env_file, the Dockerfile's ENV, a shell
# export — beats the file. Overriding hid the data dir variable in containers.
load_dotenv(_PROJECT_ROOT / ".env")


def data_dir() -> Path:
    """The data directory: CYNO_DATA_DIR, else the repo root."""
    if configured := os.environ.get("CYNO_DATA_DIR"):
        return Path(configured)
    return _PROJECT_ROOT


def _folder_setting(name: str, default: Path) -> Path:
    """A folder from the environment variable `name`, else `default`."""
    if configured := os.environ.get(name):
        return Path(configured)
    return default


def cache_dir() -> Path:
    """Thumbnails and derived-media caches: CYNO_CACHE_DIR, else <data dir>/cache. Disposable, may be local disk."""
    # Read ROOT_DIR at call time so tests can redirect it
    return _folder_setting("CYNO_CACHE_DIR", ROOT_DIR / "cache")


def backup_dir() -> Path:
    """Scheduled database backups: CYNO_BACKUP_DIR, else <data dir>/backups."""
    return _folder_setting("CYNO_BACKUP_DIR", ROOT_DIR / "backups")


# Support external data directory via the CYNO_DATA_DIR env var
ROOT_DIR = data_dir()
ASSETS_DIR = ROOT_DIR / "assets"
# The database folder (CYNO_DB_DIR, else <data dir>/data) is separate so it can live on local disk while the
# media sits on a network share.
DB_PATH = _folder_setting("CYNO_DB_DIR", ROOT_DIR / "data") / "metadata.db"

# Pollo API settings. Three bases, because Pollo splits them that way:
# the account/config endpoints sit at the platform root, task status under
# /generation, and the generation endpoints under /v1/generation.
POLLO_PLATFORM_BASE = "https://pollo.ai/api/platform"
POLLO_TASK_BASE = f"{POLLO_PLATFORM_BASE}/generation"
# Generation endpoints (https://docs.pollo.ai): /{provider}/{model}/video|image
# |audio, where the provider is a slug per model ("wanx" -> "alibaba",
# "seedream" -> "bytedance"). Each has a free ".../estimate" price-check twin.
POLLO_GENERATION_BASE = f"{POLLO_PLATFORM_BASE}/v1/generation"
# Pollo bills in credits; its API converts them to USD at this fixed rate (costUsd in a task's status)
POLLO_USD_PER_CREDIT = 0.06
POLLO_API_TIMEOUT = 30  # per-request timeout in seconds for individual HTTP calls
