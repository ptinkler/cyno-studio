"""web.safepath.inside: a joined path never leaves its folder."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from web.safepath import inside


def test_a_plain_name_is_joined(tmp_path: Path) -> None:
    """Names under the folder come back as the folder's own paths."""
    assert inside(tmp_path, "a.png") == tmp_path / "a.png"
    assert inside(tmp_path, "sub", "a.png") == tmp_path / "sub" / "a.png"
    assert inside(tmp_path) == tmp_path


@pytest.mark.parametrize("name", ["..", "../x", "a/../../x", "/etc/passwd", "", "."])
def test_a_name_that_leaves_the_folder_is_a_404(tmp_path: Path, name: str) -> None:
    """Traversal, an absolute path or nothing at all is refused."""
    with pytest.raises(HTTPException) as caught:
        inside(tmp_path, name)
    assert caught.value.status_code == 404


def test_a_sibling_with_the_same_prefix_is_not_inside(tmp_path: Path) -> None:
    """`data/chat-other` does not count as being under `data/chat`."""
    root = tmp_path / "chat"
    with pytest.raises(HTTPException):
        inside(root, "../chat-other/x")
