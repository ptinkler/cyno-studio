"""Reference images for Venice edits, kept under its combined size limit."""

import base64
import io
from pathlib import Path

from PIL import Image

from web.providers.venice.video import data_url

# Venice rejects an edit whose images add up to too much ("Aggregate image bytes exceed the project media
# policy"; it appeared recently, the exact limit isn't published, and six full-size references used to be fine.
# Stay conservatively low: a 2048px JPEG is about 0.5-1 MB, so six references still keep most of their detail.
TOTAL_BUDGET = 8 * 1024 * 1024
LONG_SIDES = (2048, 1536, 1024, 768)
JPEG_QUALITY = 90


def _jpeg(path: Path, long_side: int) -> bytes:
    with Image.open(path) as src:
        img = src.convert("RGB")
    img.thumbnail((long_side, long_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


def data_urls(paths: list[Path]) -> list[str]:
    """Data URLs for the references: untouched when they fit, else recompressed smaller until they do."""
    if sum(p.stat().st_size for p in paths) <= TOTAL_BUDGET:
        return [data_url(p) for p in paths]
    for side in LONG_SIDES:
        encoded = [_jpeg(p, side) for p in paths]
        if sum(map(len, encoded)) <= TOTAL_BUDGET or side == LONG_SIDES[-1]:
            return [f"data:image/jpeg;base64,{base64.b64encode(b).decode()}" for b in encoded]
    raise AssertionError  # pragma: no cover - the loop always returns on its last size
