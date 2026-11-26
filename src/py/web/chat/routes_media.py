"""Chat attachments, the served media files, the library of detached media and the request log."""

from typing import TYPE_CHECKING

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from web.chat.constants import (
    CHAT_PREVIEW_SIZE,
)
from web.chat.deps import router
from web.chat.helpers import (
    conversation_dir,
    require_conv,
    require_own_conversation,
)
from web.chat.schemas import (
    AttachedFile,
    DeletedLibraryItem,
    Discarded,
    LibraryCard,
    LibraryList,
    RequestLog,
)
from web.core import request_log
from web.core.metadata import get_db, iso
from web.media.index import remove_unused_file
from web.media.kinds import VIDEO_SUFFIXES
from web.media.paths import chat_file
from web.media.places import media_dirs
from web.media.thumbs import thumb_response
from web.uploads.files import read_audio_upload, read_image_upload, read_video_upload, safe_filename, store_deduped

if TYPE_CHECKING:
    from web.types import JsonValue


@router.post("/conversations/{conv_id}/attachments")
async def api_upload_attachment(conv_id: str, file: UploadFile = File(...)) -> AttachedFile:
    """Save an image attachment for a conversation."""
    require_conv(conv_id)
    content, ext = await read_image_upload(file)
    return AttachedFile(file=store_deduped(conversation_dir(conv_id), "up_", content, ext, media_dirs()))


@router.post("/conversations/{conv_id}/attachments/video")
async def api_upload_video_attachment(conv_id: str, file: UploadFile = File(...)) -> AttachedFile:
    """A source video upload (e.g.

    Recast). Saved with a 'upv_' prefix so the
    message endpoint records it as a video (not image) media item.
    """
    require_conv(conv_id)
    content, ext = await read_video_upload(file)
    return AttachedFile(file=store_deduped(conversation_dir(conv_id), "upv_", content, ext, media_dirs()))


@router.post("/conversations/{conv_id}/attachments/audio")
async def api_upload_audio_attachment(conv_id: str, file: UploadFile = File(...)) -> AttachedFile:
    """A lip-sync audio upload.

    Saved with a 'upa_' prefix so the message
    endpoint records it as an audio (not image) media item.
    """
    require_conv(conv_id)
    content, ext = await read_audio_upload(file)
    return AttachedFile(file=store_deduped(conversation_dir(conv_id), "upa_", content, ext, media_dirs()))


@router.delete("/conversations/{conv_id}/attachments/{filename}")
def api_discard_attachment(conv_id: str, filename: str) -> Discarded:
    """Drop an attachment that was uploaded but never sent (removed from the composer).

    Files any message or library entry still uses are kept.
    """
    require_conv(conv_id)
    name = safe_filename(filename)
    if not name.startswith(("up_", "upv_", "upa_")):
        return Discarded(deleted=False)
    db = get_db()
    path = conversation_dir(conv_id) / name
    return Discarded(deleted=path.is_file() and remove_unused_file(db, conv_id, path))


@router.get("/media/{conv_id}/{filename}")
def api_chat_media(conv_id: str, filename: str) -> FileResponse:
    """Serve a conversation's original media file."""
    path = chat_file(conv_id, filename)  # rejects traversal (400)
    require_own_conversation(conv_id)
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/media/{conv_id}/{filename}/preview")
async def api_chat_media_preview(conv_id: str, filename: str) -> Response:
    """A chat image (or a video's first frame), scaled down and cached for showing in the chat.

    The full file is for the lightbox and downloads.
    """
    path = chat_file(conv_id, filename)  # rejects traversal (400)
    require_own_conversation(conv_id)
    if not path.is_file():
        raise HTTPException(404, "Not found")
    try:
        return await thumb_response(path, CHAT_PREVIEW_SIZE)
    except HTTPException:
        # No thumbnail could be made (odd format, half-written file): show the
        # image itself rather than a broken tile. Videos have nothing to fall back to.
        if path.suffix.lower() in VIDEO_SUFFIXES:
            raise
        return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/request-log")
def api_request_log(limit: int = 100) -> RequestLog:
    """The latest provider requests (Venice image/video calls): what was sent and what came back, newest first.

    See web/core/request_log.py.
    """
    return RequestLog(entries=request_log.recent_entries(max(1, min(limit, 1000))))


@router.get("/library")
def api_chat_library() -> LibraryList:
    """Every generated image/video across chats, newest first.

    `attached`
    items are still in their chat (on some branch); the rest were detached
    by edits/retries made before chats had branches.
    """
    db = get_db()
    titles = db.conversation_titles()
    items: list[dict[str, JsonValue]] = []
    for msg in db.get_chat_messages_with_media():
        items.extend(
            {
                **item,
                "conversation_id": msg.conversation_id,
                "message_id": msg.id,
                "attached": True,
                "created_at": iso(msg.created_at),
            }
            for item in msg.media
            if item.get("source") != "upload"
        )
    for lib in db.list_chat_library():
        if lib.item.get("source") == "upload":
            continue
        items.append(
            {
                **lib.item,
                "conversation_id": lib.conversation_id,
                "message_id": None,
                "attached": False,
                "created_at": iso(lib.created_at),
            }
        )
    items.sort(key=lambda i: str(i["created_at"]), reverse=True)
    for i in items:
        cid = i["conversation_id"]
        i["conversation_title"] = titles.get(cid) if isinstance(cid, str) else None
    return LibraryList(items=[LibraryCard.model_validate(i) for i in items])


@router.delete("/library/{media_id}")
def api_delete_library_item(media_id: str) -> DeletedLibraryItem:
    """Delete an unattached library item and its file.

    Attached media goes
    away with its message/chat instead.
    """
    db = get_db()
    lib = db.get_chat_library_item(media_id)
    if not lib:
        raise HTTPException(404, "Not in the library (only unattached items can be deleted here)")
    db.delete_chat_library_item(media_id)
    file = lib.item.get("file")
    if isinstance(file, str):
        remove_unused_file(db, lib.conversation_id, chat_file(lib.conversation_id, file))
    return DeletedLibraryItem(deleted=media_id)
