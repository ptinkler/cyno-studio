"""Writing the export's images and videos into a chat's folder."""

import uuid
from pathlib import Path

from web.chat import conversation_dir
from web.media.kinds import IMAGE_EXTS, VIDEO_EXTS
from web.transfer.chatgpt.common import MISSING, SOURCE, ImportStats
from web.transfer.chatgpt.parse import Export
from web.types import JsonValue


def _sniffed_ext(raw: bytes) -> str:
    """The extension for image / video bytes, from their magic numbers (PNG when unrecognised)."""
    if raw.startswith(b"\x89PNG"):
        return ".png"
    if raw.startswith(b"\xff\xd8"):
        return ".jpg"
    if raw.startswith(b"GIF8"):
        return ".gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if raw[4:8] == b"ftyp":
        return ".mp4"
    return ".png"


def _ext(raw: bytes, mime: str | None) -> str:
    if mime in IMAGE_EXTS or mime in VIDEO_EXTS:
        return IMAGE_EXTS.get(mime) or VIDEO_EXTS[mime]
    return _sniffed_ext(raw)


class ChatMedia:
    """Media items for one chat, writing each export file into its folder once."""

    def __init__(self, export: Export, conv_id: str, known: list[dict[str, JsonValue]], stats: ImportStats) -> None:
        self.export, self.conv_id, self.stats = export, conv_id, stats
        self.saved: dict[str, dict[str, JsonValue]] = {}
        for item in known:
            import_file, file = item.get("import_file"), item.get("file")
            if isinstance(import_file, str) and isinstance(file, str):
                self.saved[import_file] = item

    def item(
        self, file_id: str, source: str, mime: str | None = None, name: str | None = None
    ) -> dict[str, JsonValue] | None:
        """None for a generated file that isn't in the export (one that never finished)."""
        fields: dict[str, JsonValue] = {"id": uuid.uuid4().hex[:8], "source": source, "import_file": file_id}
        if source == "generated":
            stem = Path(name or "").stem
            fields.update(model=SOURCE, prompt=stem if stem and stem.lower() != "image" else None)
        if file_id in self.saved:
            prev = self.saved[file_id]
            return {**fields, "kind": prev["kind"], "status": "done", "file": prev["file"]}
        raw = self.export.read(file_id)
        if raw is None:
            self.stats["missing_images"] += 1
            if source == "generated":
                return None
            return {**fields, "kind": "image", "status": "error", "file": None, "error": MISSING}
        ext = _ext(raw, mime)
        kind = "video" if ext in VIDEO_EXTS.values() else "image"
        file = f"{'up' if source == 'upload' else 'img'}_{uuid.uuid4().hex[:12]}{ext}"
        (conversation_dir(self.conv_id) / file).write_bytes(raw)
        self.export.new_files.append(conversation_dir(self.conv_id) / file)
        self.stats["images"] += 1
        item = {**fields, "kind": kind, "status": "done", "file": file}
        self.saved[file_id] = item
        return item
