"""Read, validate and store uploaded media.

The HTTP routes and provider layer share these upload helpers.
"""

import base64
import hashlib
import io
import mimetypes
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image

_BLANK_MAX_BRIGHTNESS = 4  # an image whose brightest pixel is at most this (of 255) counts as blank

# What Pillow raises for corrupt or non-image bytes
_NOT_AN_IMAGE = (OSError, ValueError, SyntaxError, Image.DecompressionBombError)

# Image uploads both pages accept (content type → saved extension)
IMAGE_UPLOAD_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024

# Video uploads (chat's Recast source video); clips are short (4-30s)
VIDEO_UPLOAD_TYPES = {"video/mp4": ".mp4"}
MAX_VIDEO_UPLOAD_BYTES = 200 * 1024 * 1024

# Audio uploads (chat's lip-sync track); content type → saved extension
AUDIO_UPLOAD_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}
MAX_AUDIO_UPLOAD_BYTES = 50 * 1024 * 1024

# Images above this go to a provider downscaled, so request bodies stay
# reasonable (providers cap inline image sizes).
MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024


def safe_filename(name: str) -> str:
    """A bare filename from a URL path, or 400 — no directories, traversal or dotfiles."""
    if not name or Path(name).name != name or "\\" in name or ".." in name or name.startswith("."):
        raise HTTPException(400, "Invalid filename")
    return name


def image_media_type(path: Path | str) -> str | None:
    """The image MIME type for a filename, from its extension."""
    media_type = mimetypes.guess_type(str(path))[0]
    return media_type if media_type and media_type.startswith("image/") else None


def is_blank_image(data: bytes) -> bool:
    """Check whether an image is nearly solid black.

    Providers sometimes return a black image when a safety filter blocks content.
    """
    try:
        with Image.open(io.BytesIO(data)) as im:
            grey = im.convert("L")
            grey.thumbnail((64, 64))
            _, brightest = grey.getextrema()
            return isinstance(brightest, int) and brightest <= _BLANK_MAX_BRIGHTNESS
    except _NOT_AN_IMAGE:  # Pillow rejects corrupt or non-image bytes this way
        return False  # not an image Pillow reads; leave it to the caller


def _is_real_image(content: bytes) -> bool:
    """The bytes really are an image, whatever content type the client claimed."""
    try:
        Image.open(io.BytesIO(content)).verify()
    except _NOT_AN_IMAGE:  # anything Pillow rejects is not an image
        return False
    return True


def _is_real_video(content: bytes) -> bool:
    """Check whether a file has the MP4/QuickTime signature.

    These formats carry an ``ftyp`` box near the beginning of the file.
    """
    return b"ftyp" in content[:64]


@dataclass(frozen=True)
class _UploadRule:
    """What one kind of upload must be: content types (→ saved extension), a size cap and a content check."""

    types: dict[str, str]
    max_bytes: int
    accepted: str  # the formats, as named in the "unsupported type" error
    kind: str = ""  # what the file must be, as named in the "not a valid …" error
    check: Callable[[bytes], bool] | None = None


_IMAGE_RULE = _UploadRule(IMAGE_UPLOAD_TYPES, MAX_IMAGE_UPLOAD_BYTES, "PNG, JPEG, WebP or GIF", "image", _is_real_image)
_VIDEO_RULE = _UploadRule(VIDEO_UPLOAD_TYPES, MAX_VIDEO_UPLOAD_BYTES, "MP4", "MP4 video", _is_real_video)
_AUDIO_RULE = _UploadRule(AUDIO_UPLOAD_TYPES, MAX_AUDIO_UPLOAD_BYTES, "MP3, WAV, M4A or AAC")


async def _read_upload(file: UploadFile, rule: _UploadRule) -> tuple[bytes, str]:
    """Validate an upload against `rule` and return its bytes and storage extension."""
    ext = rule.types.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}. Use {rule.accepted}.")
    content = await file.read()
    if len(content) > rule.max_bytes:
        raise HTTPException(400, f"File too large (max {rule.max_bytes // 1024 // 1024} MB)")
    if rule.check and not rule.check(content):
        raise HTTPException(400, f"File is not a valid {rule.kind}")
    return content, ext


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate and read an image upload."""
    return await _read_upload(file, _IMAGE_RULE)


async def read_video_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate and read an MP4 upload."""
    return await _read_upload(file, _VIDEO_RULE)


async def read_audio_upload(file: UploadFile) -> tuple[bytes, str]:
    """Read an audio upload with an accepted content type and size."""
    return await _read_upload(file, _AUDIO_RULE)


def file_to_data_url(path: Path) -> str:
    """Encode a local image as a data URL.

    Large images and GIFs are downscaled because several providers reject them.
    """
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if len(raw) > MAX_INLINE_IMAGE_BYTES or mime == "image/gif":
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        img.thumbnail((2048, 2048))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        raw, mime = buf.getvalue(), "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def link_or_copy(src: Path, dst: Path) -> None:
    """Make `dst` another name for `src`'s bytes: a hard link (no second copy on disk), else a copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:  # another filesystem, or one without links
        shutil.copy2(src, dst)


def _stored_name(prefix: str, content: bytes, ext: str) -> str:
    return f"{prefix}{hashlib.sha256(content).hexdigest()[:16]}{ext}"


def store_deduped(directory: Path, prefix: str, content: bytes, ext: str, elsewhere: Iterable[Path] = ()) -> str:
    """Save content under a hash-derived name and return that name.

    Identical content reuses the same file instead of storing another copy: in `directory`, and when
    another of the `elsewhere` folders already has it, a link to that file.
    """
    name = _stored_name(prefix, content, ext)
    path = directory / name
    if not path.is_file():
        found = next((d / name for d in elsewhere if (d / name).is_file()), None)
        if found:
            link_or_copy(found, path)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return name


def adopt_deduped(directory: Path, prefix: str, source: Path, ext: str) -> str:
    """Put an existing file into `directory` under its hash-derived name, linking to it rather than copying."""
    name = _stored_name(prefix, source.read_bytes(), ext)
    path = directory / name
    if not path.is_file():
        link_or_copy(source, path)
    return name
