"""Response models for chat import and export."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExportableChat(BaseModel):
    """A chat that can be picked for export."""

    id: str
    title: str
    kind: str
    space: str | None
    updated_at: str | None


class ExportableChats(BaseModel):
    """Every chat, for picking which to export."""

    chats: list[ExportableChat]


class ImportFile(BaseModel):
    """An export zip waiting in the imports folder."""

    name: str
    size: int
    modified: str


class ImportFailure(BaseModel):
    """A chat that could not be imported, and why."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    title: str | None
    error: str


class ImportJob(BaseModel):
    """An import run: its state, then its counters as they move.

    The counters appear once a run has started, and `space_id` once new chats have a space to go in.
    """

    state: Literal["idle", "running", "done", "error"]
    file: str | None = None
    started_at: str | None = None
    error: str | None = None
    total: int | None = None
    processed: int | None = None
    new: int | None = None
    updated: int | None = None
    unchanged: int | None = None
    deleted: int | None = None
    empty: int | None = None
    images: int | None = None
    missing_images: int | None = None
    failed: list[ImportFailure] | None = None
    space_id: int | None = None


class ImportStatus(BaseModel):
    """What is in the imports folder (newest first), and this user's last import."""

    folder: str
    files: list[ImportFile]
    job: ImportJob


class UploadStarted(BaseModel):
    """A chunked upload begun: its id, and how much to send per request."""

    id: str
    received: int
    chunk_size: int


class UploadProgress(BaseModel):
    """How much of an upload has arrived; `file` is the stored name once it is all there."""

    received: int
    file: str | None = None


class UploadCancelled(BaseModel):
    """The id of the upload that was cancelled."""

    cancelled: str
