"""Snapshot regression tests for the data-driven Pollo payload engine.

The engine was built and verified byte-identical to the old generator-class
hierarchy (the oracle) via an old-vs-new harness; `tests/data/
pollo_payloads_golden.json` pins that proven output. Each builder must keep
producing exactly those payloads / model URLs (and the same errors on invalid
inputs). Regenerate the golden only on a deliberate, reviewed change.
"""

from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest
from pydantic import TypeAdapter

from tests.jsonpath import must
from web.providers import pollo_engine as eng
from web.providers.pollo_engine._shared import Payload
from web.types import JsonValue

pytestmark = pytest.mark.no_tenant


class _Case(TypedDict):
    """One golden vector: the builder's keyword arguments and what it must produce."""

    kw: dict[str, JsonValue]
    ok: NotRequired[Payload]
    error: NotRequired[str]


class _Outcome(TypedDict, total=False):
    """What a builder did: the payload it built, or the name of the error it raised."""

    ok: Payload
    error: str


class _GoldenModel(TypedDict):
    """The golden snapshot of one model."""

    url: str
    cases: list[_Case]


_GOLDEN_FILE = TypeAdapter(dict[str, dict[str, _GoldenModel]])
GOLDEN = _GOLDEN_FILE.validate_json((Path(__file__).parent / "data" / "pollo_payloads_golden.json").read_text())

# kind -> (payload builder, model-url builder). The builders take different keyword
# arguments per kind, so the golden vectors supply them as a mapping.
_FN: dict[str, tuple[Callable[..., Payload], Callable[[str], str]]] = {
    "video": (eng.video_payload, eng.video_model_url),
    "image": (eng.image_payload, eng.image_model_url),
    "audio": (eng.audio_payload, eng.audio_model_url),
}

_PARAMS = [(kind, mid) for kind, models in GOLDEN.items() for mid in models]


def test_golden_covers_every_registered_model() -> None:
    """The golden snapshot must list exactly the models the tables expose."""
    assert set(GOLDEN["video"]) == set(eng.VIDEO_MODELS)
    assert set(GOLDEN["image"]) == set(eng.IMAGE_MODELS)
    assert set(GOLDEN["audio"]) == set(eng.AUDIO_MODELS)


@pytest.mark.parametrize(("kind", "model_id"), _PARAMS)
def test_engine_payload_matches_golden(kind: str, model_id: str) -> None:
    """Test that engine payload matches golden."""
    build, model_url = _FN[kind]
    data = GOLDEN[kind][model_id]
    assert model_url(model_id) == data["url"], f"url mismatch: {model_id}"
    for c in data["cases"]:
        got: _Outcome
        try:
            got = {"ok": build(model_id, **c["kw"])}
        except ValueError:  # golden vectors cover the expected model-specific failures
            got = {"error": "ValueError"}
        expected: _Outcome = {"ok": c["ok"]} if "ok" in c else {"error": must(c.get("error"))}
        assert got == expected, f"mismatch: {model_id} {c['kw']}\n got={got}\n want={expected}"
