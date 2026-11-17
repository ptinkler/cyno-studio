"""Venice reference images are sent untouched when small, and shrunk when together they are too big."""

import base64
import io
import os
from pathlib import Path

import pytest
from PIL import Image

from web.providers.venice import refs


def _noise_png(path: Path, side: int) -> Path:
    Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(path, "PNG")
    return path


def _decoded(url: str) -> bytes:
    return base64.b64decode(url.split(",", 1)[1])


class TestDataUrls:
    """``data_urls`` against the combined-size budget."""

    def test_small_references_are_sent_as_they_are(self, tmp_path: Path) -> None:
        """Under the budget the original files go out byte for byte."""
        path = _noise_png(tmp_path / "a.png", 64)
        [url] = refs.data_urls([path])
        assert url.startswith("data:image/png;base64,")
        assert _decoded(url) == path.read_bytes()

    def test_references_over_the_budget_are_recompressed_to_fit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Over the budget every reference becomes a JPEG small enough that together they fit."""
        monkeypatch.setattr(refs, "TOTAL_BUDGET", 700_000)
        paths = [_noise_png(tmp_path / f"{i}.png", 400) for i in range(3)]
        assert sum(p.stat().st_size for p in paths) > refs.TOTAL_BUDGET
        urls = refs.data_urls(paths)
        assert len(urls) == 3
        assert all(u.startswith("data:image/jpeg;base64,") for u in urls)
        assert sum(len(_decoded(u)) for u in urls) <= refs.TOTAL_BUDGET
        assert all(Image.open(io.BytesIO(_decoded(u))).size[0] <= 400 for u in urls)

    def test_still_returns_every_reference_when_nothing_fits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An impossible budget still sends all the images (at the smallest size) rather than dropping any."""
        monkeypatch.setattr(refs, "TOTAL_BUDGET", 10)
        paths = [_noise_png(tmp_path / f"{i}.png", 100) for i in range(2)]
        assert len(refs.data_urls(paths)) == 2
