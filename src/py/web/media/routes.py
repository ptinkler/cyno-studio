"""Media library — one place for every upload and creation in the app.

It's an index over files that already live elsewhere, not a store of its own:

  • library  — images uploaded straight to the library (<data>/library/)
  • chat     — a chat's uploads and generated images/videos (<data>/chat/<id>/)
  • orphan   — files in a chat's folder that nothing records any more: an
               attachment that was never sent, a file a message dropped, or
               the folder of a chat that's gone

Item ids say where a file is: "lib:<file>", "chat:<conversation id>:<file>".

Every item has a small cached thumbnail (/api/media/thumb/<id>) for the
grids, so they don't load full-size images or videos.

Using an item (as a character image or a chat attachment) copies the file to
that destination — the way uploads already work there — so deleting it from
the library never breaks what used it.
"""

import io
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from anyio import to_thread
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from web import characters
from web.auth.users import require_user
from web.core.metadata import ChatLibraryItem, get_db
from web.jsonutil import as_str
from web.media.blank import blocked_generations
from web.media.durations import fill_durations
from web.media.index import all_items, invalidate_list, item_matches, library_items, remove_unused_file
from web.media.paths import LibraryEntry, chat_dir, library_dir, library_file, library_kind, resolve
from web.media.places import media_dirs
from web.media.thumbs import forget_file, thumb_response
from web.uploads.files import (
    adopt_deduped,
    read_image_upload,
    read_video_upload,
    safe_filename,
    store_deduped,
)

if TYPE_CHECKING:
    from web.types import JsonValue

router = APIRouter(prefix="/api/media", dependencies=[Depends(require_user)])


# One entry of the library list (id, kind, name, url, thumb_url, origin, ...) as the frontend consumes it


class MediaPage(TypedDict):
    """One page of the media list, with the count of matching items before paging."""

    items: list[LibraryEntry]
    total: int
    offset: int


@router.get("/thumb/{media_id:path}")
async def api_media_thumb(media_id: str) -> FileResponse:
    """A library item's thumbnail (see thumb_response)."""
    _, path, _ = await to_thread.run_sync(resolve, media_id)
    return await thumb_response(path)


@dataclass
class MediaFilter:
    """The list's filters, as query parameters (FastAPI builds this from them)."""

    kind: str = "all"
    source: str = "all"
    origin: str = "all"
    q: str = ""

    @property
    def active(self) -> bool:
        """Whether any filter narrows the list."""
        return self.kind != "all" or self.source != "all" or self.origin != "all" or bool(self.q.strip())


@router.get("")
def api_list_media(
    filters: Annotated[MediaFilter, Depends()],
    offset: int = 0,
    limit: int = 0,  # 0 = everything from `offset` on (the default — the whole library)
) -> MediaPage:
    """Return a filtered page of media, newest first.

    ``total`` is the number of matching items before paging.
    """
    items = all_items()
    if filters.active:
        ql = filters.q.strip().lower()
        items = [i for i in items if item_matches(i, filters.kind, filters.source, filters.origin, ql)]
    total = len(items)
    items = items[offset : offset + limit] if limit else items[offset:]
    fill_durations(items)
    return {"items": items, "total": total, "offset": offset}


@router.get("/library/{filename}")
def api_library_file(filename: str) -> FileResponse:
    """Return a library file as a downloadable media response."""
    path = library_file(filename)
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/upload")
async def api_upload_media(file: Annotated[UploadFile, File()]) -> LibraryEntry:
    """Upload an image or video directly to the library.

    Audio uploads remain limited to chats.
    """
    ct = file.content_type or ""
    content, ext = await (read_video_upload(file) if ct.startswith("video/") else read_image_upload(file))
    name = store_deduped(library_dir(), "up_", content, ext, media_dirs())
    invalidate_list()
    return next(i for i in library_items() if i["name"] == name)


class MediaIds(BaseModel):
    """Request body containing media item IDs for bulk operations."""

    ids: list[str]


BULK_MAX = 500


class BulkDeleted(BaseModel):
    """What a bulk delete removed, and the ids it could not."""

    deleted: list[str]
    failed: list[str]
    kept: int = 0  # deleted items whose files stayed: another picture of the chat still uses them


class DeletedMedia(BaseModel):
    """The id of the item a delete removed, and whether its file stayed because another picture still uses it."""

    deleted: str
    file_kept: bool = False


class BlockedCounts(BaseModel):
    """How many chat generations a content filter blocked."""

    moderated: int
    black: int  # black images saved before the app detected them


class ClearedBlocked(BaseModel):
    """How many blocked generations were removed."""

    cleared: int


@router.post("/bulk-delete")
def api_bulk_delete_media(data: MediaIds) -> BulkDeleted:
    """Delete several items (see api_delete_media). Ones already gone are skipped."""
    deleted: list[str] = []
    failed: list[str] = []
    kept = 0
    for media_id in data.ids[:BULK_MAX]:
        try:
            kept += _delete_item(media_id).file_kept
            deleted.append(media_id)
        except HTTPException:
            failed.append(media_id)
    return BulkDeleted(deleted=deleted, failed=failed, kept=kept)


@router.post("/bulk-download")
def api_bulk_download_media(data: MediaIds) -> Response:
    """Return selected media items in an uncompressed ZIP archive.

    Images and videos are already compressed.
    """
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for media_id in data.ids[:BULK_MAX]:
            try:
                _, path, _ = resolve(media_id)
            except HTTPException:
                continue
            name, n = path.name, 1
            while name in used:  # same file name from two chats
                n += 1
                name = f"{path.stem}-{n}{path.suffix}"
            used.add(name)
            zf.write(path, name)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="media.zip"'},
    )


@router.delete("/{media_id:path}")
def api_delete_media(media_id: str) -> DeletedMedia:
    """Delete a media item and the record that indexes it."""
    return _delete_item(media_id)


def _delete_item(media_id: str) -> DeletedMedia:
    """Delete an item's file and the record that indexes it.

    Copies used as character images, attachments, or generation sources are separate files and remain
    intact. A picture another card of the same chat took as its reference keeps its file (only the card goes).
    """
    origin, path, parts = resolve(media_id)
    forget_file(path)
    db = get_db()
    kept = False
    if origin == "lib":
        path.unlink()
    else:
        conv_id, file = parts["conversation_id"], parts["file"]
        for msg in db.get_chat_messages(conv_id):
            if any(i.get("file") == file for i in msg.media):
                db.update_chat_message(msg.id, media=[i for i in msg.media if i.get("file") != file])
        for lib in db.list_chat_library():
            if lib.conversation_id == conv_id and lib.item.get("file") == file:
                db.delete_chat_library_item(lib.media_id)
        kept = not remove_unused_file(db, conv_id, path)
    invalidate_list()
    return DeletedMedia(deleted=media_id, file_kept=kept)


@router.get("/blocked")
def api_blocked_count() -> BlockedCounts:
    """Count moderated and black-image chat generations.

    Counts include black images saved before the app detected them.
    """
    found = blocked_generations(get_db())
    return BlockedCounts(
        moderated=sum(b.reason == "moderated" for b in found),
        black=sum(b.reason == "black" for b in found),
    )


@router.post("/blocked/clear")
def api_clear_blocked() -> ClearedBlocked:
    """Remove blocked generations and their saved black-image files.

    Removes failed cards from chats and detached items from the library.
    """
    db = get_db()
    found = blocked_generations(db)
    by_message: dict[int, list[JsonValue]] = {}
    for blocked in found:
        owner, item = blocked.owner, blocked.item
        if isinstance(owner, ChatLibraryItem):  # a detached library entry
            db.delete_chat_library_item(owner.media_id)
        else:
            by_message.setdefault(owner.id, []).append(item.get("id"))
        file = as_str(item.get("file"))
        if file and item.get("status", "done") == "done":
            path = chat_dir(owner.conversation_id) / safe_filename(file)
            forget_file(path)
            path.unlink(missing_ok=True)
    for msg_id, ids in by_message.items():
        msg = db.get_chat_message(msg_id)
        if msg:
            db.update_chat_message(msg_id, media=[i for i in msg.media if i.get("id") not in ids])
    invalidate_list()
    return ClearedBlocked(cleared=len(found))


class ImportMedia(BaseModel):
    """Request describing a library item and its import destination."""

    media_id: str
    target: Literal["chat", "character"]
    conversation_id: str | None = None  # target "chat"
    character_id: int | None = None  # target "character"


class ImportedFile(BaseModel):
    """The attachment name a library item was copied to in a chat."""

    file: str


@router.post("/import")
def api_import_media(data: ImportMedia) -> ImportedFile | characters.CharacterInfo:
    """Copy a library item to a chat or character.

    Chat imports return a file name for attachment; character imports add an
    image to the selected character.
    """
    origin, path, parts = resolve(data.media_id)
    kind = library_kind(path)
    db = get_db()
    ext = path.suffix.lower()

    if data.target == "chat":
        if kind not in ("image", "video"):  # videos can be reference-to-video refs
            raise HTTPException(400, "Only images and videos can be attached")
        conv_id = data.conversation_id or ""
        if not db.get_conversation(conv_id):
            raise HTTPException(404, "Conversation not found")
        if origin == "chat" and parts["conversation_id"] == conv_id:
            return ImportedFile(file=path.name)  # already in this chat
        name = adopt_deduped(chat_dir(conv_id), "up_", path, ext)
        invalidate_list()
        return ImportedFile(file=name)

    if kind != "image":
        raise HTTPException(400, "Only images can be used here")
    char = db.get_character(data.character_id or 0)
    if not char:
        raise HTTPException(404, "Character not found")
    return characters.add_image_from_file(char, path)
