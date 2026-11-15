#!/usr/bin/env python3
"""Probe which Pollo models are actually enabled for an API key.

Pollo gates models per key: a model shown in the picker can still answer 403
"not enabled for API access" (or 404 "Not found") when you submit. This maps
that out WITHOUT spending credits or uploading anything, by asking each model's
free `.../estimate` twin — the same endpoint the composer uses to price a
request (web/providers/pollo_estimate.py). The estimate takes the real request
body with placeholder media URLs and returns a price without starting a job.

    estimate accepted (a price came back)  -> ENABLED (at least for pricing)
    403 / "not enabled for API access"     -> DISABLED for this key
    404 "Not found"                        -> not available to this key
    anything else                          -> shown verbatim, decide yourself

Usage (from the repo root; `make` puts src/py on the path):
    POLLO_API_KEY=sk-... make probe-models                          # motion/recast family
    make probe-models ARGS="--key sk-... --family motion"
    make probe-models ARGS="--key sk-... --all-video"               # every video model
    make probe-models ARGS="--key sk-... --live"                    # GROUND TRUTH: SPENDS CREDITS

The estimate probe is free but only proves the estimate endpoint is enabled.
A model can in principle gate generation separately; `--live` submits a real
job (one per enabled model, so it costs credits and takes time) to confirm.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import requests

from web.providers.pollo_engine import VIDEO_GENERATORS
from web.providers.pollo_engine import video_generator as get_video_generator
from web.providers.pollo_estimate import PLACEHOLDERS
from web.providers.pollo_models import MODEL_INFO

if TYPE_CHECKING:
    from web.providers.pollo_engine.registry import PolloGenerator
    from web.types import JsonValue


def write(text: str, *, err: bool = False) -> None:
    """Write one line of this command's output (stdout, or stderr for progress notes)."""
    (sys.stderr if err else sys.stdout).write(text + "\n")


TIMEOUT = 20


def _models(family: str | None, *, all_video: bool) -> list[str]:
    """The video model keys to probe, in catalogue order."""
    keys: list[str] = []
    for key in VIDEO_GENERATORS:
        info = MODEL_INFO.get(key, {})
        if all_video or (family and info.get("type") == family):
            keys.append(key)
    return keys


def _build(key: str, api_key: str) -> PolloGenerator:
    """Build a video generator for a key using placeholder media.

    This follows the composer's estimate path in ``web/providers/pollo.py``.
    """
    info = MODEL_INFO.get(key, {})
    cls = VIDEO_GENERATORS[key]
    kw: dict[str, JsonValue] = {"api_key": api_key, "project": "probe", "prompt": "probe"}
    # A reference/first image when the model takes one; a source video when it
    # reads one. Motion/recast models take both.
    if getattr(cls, "ACCEPTS_IMAGES", True):
        kw["image_url"] = PLACEHOLDERS["image"]
    if info.get("video_input"):
        kw["video_url"] = PLACEHOLDERS["video"]
    if info.get("type") == "lipsync" or info.get("audio_input"):
        kw["audio_url"] = PLACEHOLDERS["audio"]
    return get_video_generator(key, **kw)


def _classify(status: int, text: str) -> tuple[str, str]:
    """Classify a probe response as a verdict and note.

    A placeholder probe is conclusive only when it returns a price or task ID
    (ENABLED), or an enablement refusal (DISABLED). Media-input models (motion,
    edit, faceswap, extend) fetch media before checking enablement, so a fake
    URL may return a 400 before reaching the 403 check. Those are UNKNOWN here;
    only a real submit with valid media settles them.
    """
    low = text.lower()
    if status == HTTPStatus.UNAUTHORIZED:
        return "KEY?", "401 — check the API key itself"
    if status in (403, 404) or "not enabled" in low or "not authorized" in low or "no access" in low:
        return "DISABLED", f"{status} / not enabled for API access on this key"
    if status == HTTPStatus.OK:
        return "ENABLED", "priced the request"
    # Any other answer (typically a 400 rejecting our fake media) didn't reach
    # the enablement check — we can't tell without real media.
    return "UNKNOWN", f"can't confirm without real media (HTTP {status}): {text[:70]}"


def probe_estimate(key: str, api_key: str) -> tuple[str, str]:
    """Ask the model's free estimate endpoint whether it answers; returns (verdict, note)."""
    try:
        gen = _build(key, api_key)
        payload = gen.get_payload()
    except (ValueError, TypeError, KeyError) as e:  # model-specific body construction errors
        return "N/A", f"can't build a probe request: {e}"
    url = gen.estimate_url
    if not url:
        return "N/A", "no estimate endpoint for this model"
    try:
        resp = requests.post(
            url,
            data=json.dumps(payload),
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return "ERR", f"not reachable: {e}"
    return _classify(resp.status_code, resp.text)


def _probe_live(key: str, api_key: str) -> tuple[str, str]:
    """Submit a live probe that may spend credits on enabled models.

    Pollo may reject placeholder URLs even when the model is enabled, which
    still proves the model itself is not gated by a 403 response.
    """
    gen = _build(key, api_key)
    try:
        resp = gen.send_request()
    except (ConnectionError, ValueError, requests.RequestException) as e:
        return "ERR", str(e)[:140]
    try:
        body = cast("JsonValue", resp.json())
    except ValueError:
        return _classify(resp.status_code, resp.text)
    data = body.get("data") if isinstance(body, dict) else None
    task_id = data.get("taskId") if isinstance(data, dict) else None
    if task_id:
        return "ENABLED", f"accepted, taskId={task_id} (a job was created — may cost credits)"
    # Only a real taskId or an enablement refusal is conclusive; a media-rejection
    # 400 means the enablement check wasn't reached (see _classify).
    return _classify(resp.status_code, resp.text)


class _Args(argparse.Namespace):
    """The parsed command line."""

    key: str | None = None
    family: str = "motion"
    all_video: bool = False
    live: bool = False
    yes_bill_me: bool = False


def main() -> int:
    """Probe the selected Pollo video models and report their availability."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.getenv("POLLO_API_KEY"), help="Pollo API key (or set POLLO_API_KEY)")
    ap.add_argument("--family", default="motion", help="model type to probe (default: motion/recast)")
    ap.add_argument("--all-video", action="store_true", help="probe every video model, not just one family")
    ap.add_argument("--live", action="store_true", help="really submit — GROUND TRUTH, SPENDS REAL MONEY when enabled")
    ap.add_argument(
        "--yes-bill-me",
        action="store_true",
        help="required with --live: you accept that REAL, non-refundable jobs are created and billed",
    )
    args = ap.parse_args(namespace=_Args())

    if not args.key:
        ap.error("no API key — pass --key or set POLLO_API_KEY")

    # Hard guard: --live creates REAL generation jobs. Pollo has no cancel/refund,
    # so every enabled model billed is money spent. Media-input models (motion /
    # edit / faceswap / extend) can ONLY be tested this way — there is no free
    # enablement check for them, so DON'T probe them live unless you accept that.
    if args.live and not args.yes_bill_me:
        ap.error(
            "--live SUBMITS REAL JOBS THAT COST REAL MONEY (Pollo can't cancel or refund them). "
            "Every model that turns out enabled is billed in full. Re-run with --yes-bill-me only if "
            "you explicitly accept those charges. Prefer the free estimate probe (omit --live); note it "
            "cannot determine enablement for media-input models — test those one at a time in the app."
        )

    keys = _models(None if args.all_video else args.family, all_video=args.all_video)
    if not keys:
        write(f"No models match family={args.family!r}.")
        return 1

    mode = "free estimate probe"
    if args.live:
        mode = "LIVE submit"
        write(f"⚠  LIVE: creating real non-refundable jobs for up to {len(keys)} models — every enabled one is BILLED.")
    scope = "all video models" if args.all_video else f"family={args.family!r}"
    write(f"Probing {len(keys)} models ({scope}) via {mode}\n")
    probe = _probe_live if args.live else probe_estimate

    results: list[tuple[str, str, str, str]] = []
    for key in keys:
        label = MODEL_INFO.get(key, {}).get("label") or key
        verdict, note = probe(key, args.key)
        results.append((verdict, key, label, note))
        write(f"  {verdict:8}  {key:24}  {label:24}  {note}")

    tally = {v: sum(1 for r in results if r[0] == v) for v in {r[0] for r in results}}
    summary = ", ".join(f"{n} {v.lower()}" for v, n in sorted(tally.items()))
    write(f"\n{summary}.")
    if tally.get("UNKNOWN"):
        write("UNKNOWN = media-input model; a placeholder can't confirm enablement — test it in-app with real media.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
