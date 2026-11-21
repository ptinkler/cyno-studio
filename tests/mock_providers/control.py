"""The test-facing control API: what the app sent, reset between tests, and the configurable behaviours."""

from dataclasses import asdict, fields

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tests.mock_providers.state import Settings, state
from web.types import JsonValue

router = APIRouter(prefix="/__mock")


class RequestList(BaseModel):
    """Every request recorded since the last reset, oldest first."""

    requests: list[dict[str, JsonValue]]


@router.get("/requests")
def requests(provider: str | None = None, path: str | None = None) -> RequestList:
    """The recorded requests, optionally only one provider's or those whose path ends with `path`."""
    return RequestList(
        requests=[
            r.as_json()
            for r in state.requests
            if (provider is None or r.provider == provider) and (path is None or r.path.endswith(path))
        ]
    )


@router.post("/reset")
def reset() -> dict[str, bool]:
    """Forget the requests and restore the default behaviours."""
    state.reset()
    return {"ok": True}


@router.get("/settings")
def get_settings() -> dict[str, float | int]:
    """The current behaviour knobs."""
    return asdict(state.settings)


@router.post("/settings")
def set_settings(changes: dict[str, float]) -> dict[str, float | int]:
    """Change some behaviour knobs (see ``Settings``); unknown names are refused."""
    known = {f.name for f in fields(Settings)}
    if unknown := set(changes) - known:
        raise HTTPException(400, f"Unknown settings: {sorted(unknown)}")
    for name, value in changes.items():
        setattr(state.settings, name, value)
    return asdict(state.settings)
