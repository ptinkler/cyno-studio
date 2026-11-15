"""Uploading local files to the public host Pollo needs: it only accepts URLs."""

from collections.abc import Mapping
from pathlib import Path

from web.providers.pollo_errors import ReferenceFileRequiredError, UploadFailedError
from web.types import JsonValue
from web.uploads import hosts as image_hosts


def upload(path: Path, what: str = "image") -> str:
    """Upload a local file to the user's configured public host.

    Pollo only accepts URLs; the host and retention follow upload preferences.
    """
    try:
        return image_hosts.upload_file(path)
    except ValueError as e:
        raise UploadFailedError(what, e) from e


def upload_ref_item(item: Mapping[str, object]) -> dict[str, JsonValue]:
    """Upload one image, video, or audio reference and shape it for Pollo.

    The result has ``url``, ``name`` (when supplied), and ``type``. Upload
    URLs are cached and reused across retries.
    """
    typ = str(item.get("type") or "image")
    path = item["path"]
    if not isinstance(path, Path):
        raise ReferenceFileRequiredError
    url = upload(path, "video") if typ == "video" else upload(path, "audio") if typ == "audio" else upload(path)
    ref: dict[str, JsonValue] = {"url": url, "type": typ}
    if name := item.get("name"):
        ref["name"] = str(name)
    return ref


def notice() -> dict[str, JsonValue]:
    """``upload_notice`` for the media card when a backup upload host was used."""
    notes = image_hosts.take_upload_notes()
    return {"upload_notice": "; ".join(notes)} if notes else {}
