"""Reading videos with OpenCV: a first frame, and a length."""

import functools
from pathlib import Path

import cv2


@functools.lru_cache(maxsize=4096)
def video_seconds(path: str, _mtime_ns: int) -> float | None:
    """A video's length in seconds, from its header (cached per file version)."""
    cap = cv2.VideoCapture(path)
    try:
        fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        return round(frames / fps, 1) if fps > 0 and frames > 0 else None
    finally:
        cap.release()


def first_frame_jpeg(video_path: Path) -> bytes | None:
    """Return a video's first frame as JPEG bytes, or None if unreadable.

    Uncached — the caller caches the thumbnail it makes from this.
    """
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpeg.tobytes()
    except (cv2.error, OSError, ValueError):  # unreadable videos have no frame
        return None
