"""Small real media files for the mock's answers (thumbnailing and probing need valid ones)."""

import io
import tempfile
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@cache
def png(color: str = "teal") -> bytes:
    """A 64x64 PNG of one colour."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


@cache
def mp4() -> bytes:
    """A one-second 64x64 MP4."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), 8, (64, 64))
        for i in range(8):
            writer.write(np.full((64, 64, 3), i * 30, dtype=np.uint8))
        writer.release()
        return path.read_bytes()
