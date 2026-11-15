"""Tests for web/uploads.py — image upload helpers shared by chat and Generate."""

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from web.uploads import image_media_type, read_image_upload, safe_filename


def _upload(content: bytes, content_type: str) -> UploadFile:
    """An upload carrying ``content`` and reporting ``content_type``."""
    return UploadFile(io.BytesIO(content), headers=Headers({"content-type": content_type}))


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("name", ["", "a/b.png", "..", "x..png", "a\\b.png", ".env", "../x"])
def test_safe_filename_rejects(name: str) -> None:
    """Test that safe filename rejects."""
    with pytest.raises(HTTPException) as e:
        safe_filename(name)
    assert e.value.status_code == 400


def test_safe_filename_accepts_plain_names() -> None:
    """Test that safe filename accepts plain names."""
    assert safe_filename("img_abc123.png") == "img_abc123.png"


def test_image_media_type() -> None:
    """Test that image media type."""
    assert image_media_type("a.JPG") == "image/jpeg"
    assert image_media_type("a.webp") == "image/webp"
    assert image_media_type("a.mp4") is None


def test_read_image_upload_ok() -> None:
    """Test that read image upload ok."""
    content, ext = asyncio.run(read_image_upload(_upload(_png(), "image/png")))
    assert ext == ".png"
    assert content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    ("content", "content_type", "msg"),
    [
        (b"x", "text/plain", "Unsupported file type"),
        (b"not an image", "image/png", "not a valid image"),
    ],
)
def test_read_image_upload_rejects(content: bytes, content_type: str, msg: str) -> None:
    """Test that read image upload rejects."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(read_image_upload(_upload(content, content_type)))
    assert e.value.status_code == 400
    assert msg in e.value.detail
