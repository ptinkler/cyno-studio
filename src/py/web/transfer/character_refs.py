"""A card's character-image references, carried in an export as ordinary chat files.

A card made with a character stores references like `char:42/img_8f….jpg`: the character's id and image
on the server that made it. Another server has no such character (ids are per server), so the picture
would be missing there. The export copies each of those images into the chat's folder in the zip and
points the card at the copy by name, so the card keeps showing, and can be redone with, what it was made from.
The link back to the character is dropped: on the new server they are plain reference pictures.
"""

import re
from collections.abc import Mapping
from pathlib import Path

from web import characters
from web.core.metadata import get_db
from web.jsonutil import as_list, as_object
from web.types import JsonValue

_CHAR_REF = re.compile(rf"^{re.escape(characters.REF_PREFIX)}(\d+)/(.+)$")
PREFIX = "cref_"  # the copied files' names: cref_<character id>_<original name>


def _own_image(character_id: int, file: str) -> Path | None:
    """The image file, if the character is this user's, lists the image, and it is still on disk."""
    character = get_db().get_character(character_id)
    if character is None or file not in character.images:
        return None
    path = characters.char_dir(character_id) / file
    return path if path.is_file() else None


def _carry(ref: JsonValue, taken: dict[str, Path]) -> JsonValue:
    """One reference: a character's image becomes a chat file name (and is noted in `taken`); anything else stays."""
    match = _CHAR_REF.match(ref) if isinstance(ref, str) else None
    if match is None:
        return ref
    character_id, file = int(match.group(1)), match.group(2)
    path = _own_image(character_id, file)
    if path is None:  # gone, or not this user's: left as it was
        return ref
    name = f"{PREFIX}{character_id}_{file}"
    taken[name] = path
    return name


def _params(params: Mapping[str, JsonValue], taken: dict[str, Path]) -> dict[str, JsonValue]:
    refs = as_list(params.get("refs"))
    return {**params, "refs": [_carry(r, taken) for r in refs]} if refs else dict(params)


def snapshot_card(item: Mapping[str, JsonValue], taken: dict[str, Path]) -> dict[str, JsonValue]:
    """A media card with its (and its earlier versions') character-image references swapped for chat files.

    `taken` collects each copied file's new name and where it is on disk, for the caller to put in the zip.
    """
    out: dict[str, JsonValue] = {**item}
    if "params" in item:
        out["params"] = _params(as_object(item.get("params")), taken)
    if isinstance(item.get("versions"), list):
        out["versions"] = [
            {**v, "params": _params(as_object(v.get("params")), taken)} if isinstance(v, dict) and "params" in v else v
            for v in as_list(item.get("versions"))
        ]
    return out
