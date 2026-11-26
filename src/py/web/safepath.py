"""Building a file path from a name a client sent: the result is always inside one folder."""

import os
from pathlib import Path

from fastapi import HTTPException


def inside(root: Path | str, *names: str) -> Path:
    """`root` joined with `names`, or 404 when that leaves `root` (`..`, an absolute name, nothing at all).

    The check is on the joined path itself (normalised, then compared with the folder's prefix), so every
    path built here is known to be under `root` wherever it is used afterwards.
    """
    base = str(Path(root).absolute())
    full = os.path.normpath(Path(base).joinpath(*names))
    if full == base and names:
        raise HTTPException(404, "Not found")
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(404, "Not found")
    return Path(full)
