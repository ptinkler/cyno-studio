"""The model catalogue as served: each provider row parsed into its kind's model, bad rows dropped."""

import logging

import pytest

from web.chat.model_schemas import parse_catalogue
from web.providers import pollo
from web.providers.model_tags import tags_for
from web.types import Catalogue, ModelEntry

KINDS = ("image", "video", "audio")


def _tagged(kind: str) -> list[ModelEntry]:
    """Pollo's rows of `kind` as the catalogue assembles them (tags added)."""
    rows = pollo.list_models(kind)
    for row in rows:
        row["tags"] = tags_for(kind, row)
    return rows


def test_every_real_pollo_row_parses(provider_keys: dict[str, str | None]) -> None:
    """No Pollo model is dropped: the rows its tables build all fit the models."""
    provider_keys["pollo"] = "pollo-test"
    rows = {kind: _tagged(kind) for kind in KINDS}
    assert all(rows.values())
    parsed = parse_catalogue(Catalogue(errors={}, text=[], **rows))
    assert [m.id for m in parsed.image] == [str(r["id"]) for r in rows["image"]]
    assert [m.id for m in parsed.video] == [str(r["id"]) for r in rows["video"]]
    assert [m.id for m in parsed.audio] == [str(r["id"]) for r in rows["audio"]]


def test_a_row_that_does_not_fit_is_dropped_and_the_rest_kept(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One odd third-party row must not take the whole catalogue down."""
    # alembic's logging config (run by other tests) switches existing loggers off
    monkeypatch.setattr(logging.getLogger("web.chat.model_schemas"), "disabled", False)
    good: ModelEntry = {"id": "a/ok", "name": "OK", "tags": [], "input_modalities": ["text"], "supports_tools": True}
    bad: ModelEntry = {"id": "a/bad", "name": "Bad", "tags": [], "input_modalities": "text", "supports_tools": True}
    with caplog.at_level(logging.WARNING):
        parsed = parse_catalogue(Catalogue(errors={"x": "down"}, text=[bad, good], image=[], video=[], audio=[]))
    assert [m.id for m in parsed.text] == ["a/ok"]
    assert parsed.errors == {"x": "down"}
    assert "a/bad" in caplog.text


def test_prices_from_openrouter_arrive_as_text_and_are_read_as_numbers() -> None:
    """OpenRouter lists per-token prices as strings."""
    row: ModelEntry = {
        "id": "a/m",
        "name": "M",
        "tags": [],
        "input_modalities": ["text"],
        "supports_tools": False,
        "prompt_price": "0.000001",
        "completion_price": "0.000002",
        "context_length": 8000,
        "created": 1700000000,
    }
    [model] = parse_catalogue(Catalogue(errors={}, text=[row], image=[], video=[], audio=[])).text
    assert (model.prompt_price, model.completion_price) == (1e-6, 2e-6)
    assert model.created == 1700000000
