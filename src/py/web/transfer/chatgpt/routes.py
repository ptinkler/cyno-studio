"""The import routes: what is in the imports folder, starting a run, and chunked uploads."""

import contextlib
import contextvars
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, TypedDict, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from web.auth.users import require_user
from web.core import config
from web.core.metadata import current_tenant
from web.transfer import export as chat_export
from web.transfer.chatgpt.common import NOT_AN_EXPORT
from web.transfer.chatgpt.importer import run_import
from web.transfer.limits import MAX_IMPORT_BYTES
from web.transfer.schemas import ImportFile, ImportJob, ImportStatus, UploadCancelled, UploadProgress, UploadStarted
from web.types import JsonValue
from web.uploads.files import safe_filename

log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/chat/import", dependencies=[Depends(require_user)])


class _UploadMeta(TypedDict):
    name: str
    size: int


UPLOAD_CHUNK = 16 * 1024 * 1024  # bytes per upload request, under nginx's 25 MB cap
UPLOAD_STALE_SECONDS = 24 * 60 * 60  # unfinished uploads older than this are deleted


def _import_dir() -> Path:
    # Per-tenant (<data>/imports/<uid>/) so one user can't import another user's
    # uploaded export by guessing its filename.
    base = config.ROOT_DIR / "imports"
    uid = current_tenant()
    return base / uid if uid else base


# Per-tenant import progress, keyed by user id (so one user's import status and
# single-flight don't leak into or block another's).
_jobs: dict[str, dict[str, JsonValue]] = {}
_job_lock = threading.Lock()


def reset_jobs() -> None:
    """Forget every tenant's import progress (tests, between runs)."""
    _jobs.clear()


def _job_key() -> str:
    return current_tenant() or ""


def _current_job() -> dict[str, JsonValue]:
    return _jobs.get(_job_key(), {"state": "idle"})


class StartImport(BaseModel):
    """Name of an export zip already stored in the imports folder."""

    file: str  # a zip in the imports folder


@router.get("/chatgpt")
def api_import_status() -> ImportStatus:
    """The exports in the imports folder (newest first) and this user's last import's progress."""
    folder = _import_dir()
    files = sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return ImportStatus(
        folder=str(folder),
        files=[
            ImportFile(
                name=p.name,
                size=p.stat().st_size,
                modified=datetime.fromtimestamp(p.stat().st_mtime).astimezone().replace(tzinfo=None).isoformat(),
            )
            for p in files
        ],
        job=ImportJob.model_validate(_current_job()),
    )


@router.post("/chatgpt")
def api_start_import(data: StartImport) -> ImportJob:
    """Start importing an export in the background; progress is in GET."""
    path = _import_dir() / safe_filename(data.file)
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise HTTPException(404, "That export isn't in the imports folder")
    key = _job_key()
    with _job_lock:
        if _jobs.get(key, {}).get("state") == "running":
            raise HTTPException(409, "An import is already running")
        job: dict[str, JsonValue] = {
            "state": "running",
            "file": path.name,
            "started_at": datetime.now().astimezone().replace(tzinfo=None).isoformat(),
        }
        _jobs[key] = job
    # Copy the request context so imported rows belong to the signed-in user
    ctx = contextvars.copy_context()
    threading.Thread(target=lambda: ctx.run(_run_job, path, job), daemon=True).start()
    return ImportJob.model_validate(job)


def _run_job(path: Path, job: dict[str, JsonValue]) -> None:
    try:
        run_import(path, job)
        job["state"] = "done"
    except Exception as e:  # report unexpected worker failures to the UI
        log.exception("ChatGPT import job failed")
        job.update(state="error", error=str(e))


# In chunks: start an upload, send each chunk with its offset (resending one
# replaces what was there from that offset), and the last one turns the
# upload into <name>.zip in the imports folder.


class StartUpload(BaseModel):
    """Original filename and total byte size for a chunked export upload."""

    name: str
    size: int = Field(gt=0, le=MAX_IMPORT_BYTES)


def _upload_paths(upload_id: str) -> tuple[Path, Path]:
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise HTTPException(404, "Upload not found")
    folder = _import_dir()
    return folder / f".upload-{upload_id}.part", folder / f".upload-{upload_id}.json"


def _clear_stale_uploads(folder: Path) -> None:
    for p in folder.glob(".upload-*"):
        with contextlib.suppress(OSError):
            if time.time() - p.stat().st_mtime > UPLOAD_STALE_SECONDS:
                p.unlink()


@router.post("/chatgpt/uploads")
def api_start_upload(data: StartUpload) -> UploadStarted:
    """Start a chunked upload and return its ID and chunk size."""
    name = Path(data.name.replace("\\", "/")).name
    if not name.lower().endswith(".zip") or name.startswith("."):
        raise HTTPException(400, "Choose a .zip: a chat export from here, or the one ChatGPT's export email links to")
    folder = _import_dir()
    folder.mkdir(parents=True, exist_ok=True)
    _clear_stale_uploads(folder)
    upload_id = uuid.uuid4().hex
    part, meta = _upload_paths(upload_id)
    part.touch()
    meta.write_text(json.dumps({"name": name, "size": data.size}))
    return UploadStarted(id=upload_id, received=0, chunk_size=UPLOAD_CHUNK)


@router.post("/chatgpt/uploads/{upload_id}")
async def api_upload_chunk(
    upload_id: str,
    offset: Annotated[int, Form(..., ge=0)],
    chunk: Annotated[UploadFile, File(...)],
) -> UploadProgress:
    """Write one chunk at `offset`.

    Returns how much has arrived, and once
    it's all there, the export's `file` name in the imports folder.
    """
    part, meta = _upload_paths(upload_id)
    if not part.is_file() or not meta.is_file():
        raise HTTPException(404, "Upload not found (unfinished uploads are cleared after a day)")
    info = cast("_UploadMeta", json.loads(meta.read_text()))
    raw = await chunk.read(UPLOAD_CHUNK + 1)
    if len(raw) > UPLOAD_CHUNK or offset + len(raw) > info["size"]:
        raise HTTPException(400, "Chunk too large")
    return await run_in_threadpool(_write_chunk, part, meta, info, offset, raw)


def _write_chunk(part: Path, meta: Path, info: _UploadMeta, offset: int, raw: bytes) -> UploadProgress:
    received = part.stat().st_size
    if offset > received:
        raise HTTPException(409, f"Expected the chunk at {received}")
    with part.open("r+b") as f:
        f.truncate(offset)  # a resent chunk replaces what was there
        f.seek(offset)
        f.write(raw)
    received = offset + len(raw)
    if received < info["size"]:
        return UploadProgress(received=received)
    if not zipfile.is_zipfile(part):
        part.unlink()
        meta.unlink()
        raise HTTPException(400, "That isn't a zip file")
    with zipfile.ZipFile(part) as zf:
        if "conversations.json" not in zf.namelist() and not chat_export.is_native_export(zf):
            part.unlink()
            meta.unlink()
            raise HTTPException(400, NOT_AN_EXPORT)
    target = part.parent / info["name"]
    n = 1
    while target.exists():
        n += 1
        target = part.parent / f"{Path(info['name']).stem} ({n}).zip"
    part.rename(target)
    meta.unlink()
    return UploadProgress(received=received, file=target.name)


@router.delete("/chatgpt/uploads/{upload_id}")
def api_cancel_upload(upload_id: str) -> UploadCancelled:
    """Cancel an unfinished upload and remove its temporary files."""
    for p in _upload_paths(upload_id):
        p.unlink(missing_ok=True)
    return UploadCancelled(cancelled=upload_id)
