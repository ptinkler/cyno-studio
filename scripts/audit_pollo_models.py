#!/usr/bin/env python3
"""Audit our Pollo model catalogue against the docs and against a live key.

Two independent signals decide what to list and how to configure each model —
neither is enough alone, as our Seedance models prove (they work but aren't in
the public spec):

  1. DOCUMENTED?  Pollo's OpenAPI spec (docs.pollo.ai/openapi.json) is the
     source of truth for a model's FEATURES — whether it has a reference-to-
     video branch, the refs cap, allowed ref types, durations, resolutions,
     ratios. This script extracts those and diffs them against our registry
     (src/py/web/providers/pollo/engine/video/models.py VIDEO_MODELS + pollo/models.py MODEL_INFO)
     so you never hand-find a model's feature set again.

  2. ENABLED ON YOUR KEY?  (--key / POLLO_API_KEY) The free estimate probe
     (scripts/probe_pollo_models.py) says which models actually answer for your
     key. This is the real show/hide signal: show = enabled, hide = 403/404,
     regardless of whether the model is documented.

Usage:
    # Feature diff only (fetches the ~10 MB spec, or pass a saved copy):
    PYTHONPATH=src/py python -m scripts.audit_pollo_models
    PYTHONPATH=src/py python -m scripts.audit_pollo_models --spec /path/to/openapi.json

    # Add the live availability column:
    PYTHONPATH=src/py python -m scripts.audit_pollo_models --key sk-...

Output per model: docs? | enabled? | refs(cap/types) | mismatches vs our config.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypedDict, cast

import requests

from scripts.probe_pollo_models import probe_estimate
from web.jsonutil import as_int, as_list, as_object, as_objects, as_str, body_of
from web.providers.pollo.engine.video import VIDEO_MODELS
from web.providers.pollo.models import MODEL_INFO

if TYPE_CHECKING:
    from web.providers.pollo.engine.video import VideoRow
    from web.providers.pollo.models import ModelInfo, RefMode
    from web.types import JsonValue


def write(text: str, *, err: bool = False) -> None:
    """Write one line of this command's output (stdout, or stderr for progress notes)."""
    (sys.stderr if err else sys.stdout).write(text + "\n")


type LimitKind = Literal["image", "video", "audio"]
type Spec = dict[str, JsonValue]


class DocRefs(TypedDict):
    """The Reference-To-Video branch the docs describe for one model."""

    max: int | None
    types: list[str]
    limits: dict[LimitKind, int]


class DocFeature(TypedDict):
    """One documented model's generation path and feature set."""

    path: str
    refs: DocRefs | None
    resolutions: list[str] | None
    ratios: list[str] | None


class OurModel(TypedDict):
    """One model in our registry: its key, presentation info and endpoint row."""

    key: str
    info: ModelInfo
    cfg: VideoRow


class _Remove(Enum):
    """Marker for an edit that deletes a field instead of setting it."""

    REMOVE = "remove"


type EditValue = str | _Remove
type Edits = dict[str, dict[str, EditValue]]


class _Args(argparse.Namespace):
    """Typed view of the command-line options."""

    spec: str | None = None
    key: str | None = None
    write: bool = False


class InlineEntryError(ValueError):
    """A one-line model entry did not have the expected `"key": {...},` shape."""

    def __init__(self, line: str) -> None:
        """Remember the offending source line."""
        super().__init__(f"cannot edit one-line entry: {line!r}")


SPEC_URL = "https://docs.pollo.ai/openapi.json"
# Per-type ref caps live in the free-text "constraints" of the refs description;
# pull the common phrasings so the audit can compare them to our ref_mode limits.
_LIMIT_PATTERNS: dict[LimitKind, re.Pattern[str]] = {
    "image": re.compile(r"(?:up to|most)\s+(\d+)\s+image", re.IGNORECASE),
    "video": re.compile(r"(?:up to|most)\s+(\d+)\s+(?:reference\s+)?video", re.IGNORECASE),
    "audio": re.compile(r"(?:up to|most)\s+(\d+)\s+(?:audio|voice)", re.IGNORECASE),
}


def _load_spec(path_or_none: str | None) -> Spec:
    """The OpenAPI spec from a saved file, or fetched from docs.pollo.ai."""
    if path_or_none:
        with Path(path_or_none).open(encoding="utf-8") as f:
            return as_object(cast("object", json.load(f)))
    write(f"Fetching {SPEC_URL} (~10 MB)…", err=True)
    resp = requests.get(SPEC_URL, timeout=60)
    resp.raise_for_status()
    return as_object(body_of(resp))


def _resolve(spec: Spec, node: Spec) -> Spec:
    """Follow a single $ref (one level is enough for these schemas)."""
    ref = as_str(node.get("$ref"))
    if not ref:
        return node
    cur = spec
    for part in ref.lstrip("#/").split("/"):
        cur = as_object(cur.get(part))
    return cur


def _ref_branch(spec: Spec, input_schema: Spec) -> Spec | None:
    """The Reference-To-Video branch of an `input` oneOf — the one with refs."""
    for branch in as_objects(input_schema.get("oneOf")):
        b = _resolve(spec, branch)
        if "refs" in as_object(b.get("properties")):
            return b
    return None


def _enum(schema: Spec, prop: str) -> list[str] | None:
    """A property's `enum` values (the string ones), or None when it declares none."""
    raw = as_object(as_object(schema.get("properties")).get(prop)).get("enum")
    if raw is None:
        return None
    return [s for item in as_list(raw) if (s := as_str(item)) is not None]


def _docs_feature(spec: Spec, path: str, op: Spec) -> DocFeature:
    """Extract one model's refs/durations/resolutions feature set from its POST op."""
    content = as_object(as_object(op.get("requestBody")).get("content"))
    body = _resolve(spec, as_object(as_object(content.get("application/json")).get("schema")))
    input_schema = _resolve(spec, as_object(as_object(body.get("properties")).get("input")))
    refs: DocRefs | None = None
    branch = _ref_branch(spec, input_schema)
    if branch:
        refs_prop = as_object(as_object(branch.get("properties")).get("refs"))
        items = _resolve(spec, as_object(refs_prop.get("items")))
        desc = str(refs_prop.get("description") or "") + " " + str(branch.get("description") or "")
        limits: dict[LimitKind, int] = {
            k: int(m.group(1)) for k, pat in _LIMIT_PATTERNS.items() if (m := pat.search(desc))
        }
        refs = {
            "max": as_int(refs_prop.get("maxItems")),
            "types": _enum(items, "type") or [t for t in ("image", "video", "audio") if t in desc],
            "limits": limits,
        }
    return {
        "path": path,
        "refs": refs,
        "resolutions": _enum(input_schema, "resolution"),
        "ratios": _enum(input_schema, "aspectRatio"),
    }


def parse_docs(spec: Spec) -> dict[str, DocFeature]:
    """{last path segment's model slug -> feature dict} for every POST generation path."""
    out: dict[str, DocFeature] = {}
    for path, methods in as_object(spec.get("paths")).items():
        method_ops = as_object(methods)
        if "/generation/" not in path or "post" not in method_ops:
            continue
        # .../<provider>/<model-slug>/video  (slug is the identifying segment)
        parts = [p for p in path.split("/") if p]
        slug = parts[-2] if parts[-1] in ("video", "image", "audio") else parts[-1]
        out[slug] = _docs_feature(spec, path, as_object(method_ops["post"]))
    return out


def _our_models() -> dict[str, OurModel]:
    """Our video registry keyed by Pollo model slug (MODEL)."""
    out: dict[str, OurModel] = {}
    for key, cfg in VIDEO_MODELS.items():
        slug = cfg.get("MODEL")
        if slug:
            out[slug] = {"key": key, "info": MODEL_INFO.get(key, {}), "cfg": cfg}
    return out


def _refs_mismatches(rm: RefMode, doc_refs: DocRefs) -> list[str]:
    """Where our ref_mode numbers disagree with the docs' refs branch."""
    msgs: list[str] = []
    if doc_refs["max"] and rm.get("max") != doc_refs["max"]:
        msgs.append(f"refs max ours={rm.get('max')} docs={doc_refs['max']}")
    our_limits = rm.get("limits") or {}
    msgs.extend(
        f"{t} cap ours={our_limits.get(t)} docs={n}" for t, n in doc_refs["limits"].items() if our_limits.get(t) != n
    )
    return msgs


def _mismatches(ours: OurModel, docs: DocFeature | None) -> list[str]:
    """Where our ref_mode config disagrees with the docs (empty = consistent)."""
    if not docs:
        return []
    rm = ours["info"].get("ref_mode")
    doc_refs = docs["refs"]
    if doc_refs and not rm:
        return [f"docs has refs (max {doc_refs['max']}) but we declare no ref_mode"]
    if rm and not doc_refs:
        return ["we declare ref_mode but docs show no refs branch"]
    if rm and doc_refs:
        return _refs_mismatches(rm, doc_refs)
    return []


def _enablement(keys: list[str], api_key: str) -> dict[str, str]:
    """Live estimate probe (reuses probe_pollo_models) -> {our_key: verdict}."""
    return {k: probe_estimate(k, api_key)[0] for k in keys}


# ── --write: safe, surgical edits to our source (you review the git diff) ──
# Only the mechanical, derivable fields are touched: `hidden` (enablement) and
# `ref_mode` in pollo/models.py, and `HAS_REFS` in video/models.py. Curated bits —
# labels, deliberate "Superseded" hides, ref_mode's own quirks like
# `no_audio_with_video` — are merged around, never overwritten.
REMOVE: Final = _Remove.REMOVE
_REPO = Path(__file__).resolve().parent.parent  # repo root
_PY = _REPO / "src" / "py"
MODELS_FILE = _PY / "web" / "providers" / "pollo" / "models.py"
ENGINE_FILE = _PY / "web" / "providers" / "pollo" / "engine" / "video" / "models.py"
# A hide we may clear is one justified by enablement; a deliberate hide is kept.
_ENABLEMENT_HIDE = re.compile(r"enabled|403|404|unavailable|access", re.IGNORECASE)
# Only for these does the free estimate speak for the model itself. A media-input model (edit, extend, motion,
# upscale, lip-sync, face swap) has its placeholder media refused before enablement is checked, so an ENABLED
# there means nothing (six edit models answered ENABLED yet 403'd a real generation).
_ESTIMATE_DECIDES = frozenset({"img2vid"})
# The ref types our frontend and backend understand; the docs also list others (element, file, link)
_REF_TYPES = ("image", "video", "audio")


def py_literal(v: JsonValue) -> str:
    """A Python literal using double quotes and True/False (ruff-style)."""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, Mapping):
        return "{" + ", ".join(f'"{k}": {py_literal(x)}' for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(py_literal(x) for x in v) + "]"
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    return str(v)


def _to_json(value: object) -> JsonValue:
    """A JSON-shaped copy of an in-memory literal (tuples become lists)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {k: _to_json(v) for k, v in as_object(cast("object", value)).items()}
    return [_to_json(v) for v in as_list(value)]


def _ref_mode_json(rm: RefMode) -> dict[str, JsonValue]:
    """A ref_mode as a plain JSON object, keeping its key order."""
    return {k: _to_json(v) for k, v in rm.items()}


def _block_range(lines: list[str], key: str) -> tuple[int, int] | None:
    """Find a block's first and last line indices.

    A one-line `    "key": {…},` entry returns (i, i).
    """
    opener = re.compile(r'^    "' + re.escape(key) + r'": \{')
    for i, ln in enumerate(lines):
        if opener.match(ln):
            if sum(ln.count(c) for c in "{[") - sum(ln.count(c) for c in "}]") <= 0:
                return i, i  # balanced on one line
            for j in range(i + 1, len(lines)):
                if re.match(r"^    \},?$", lines[j]):
                    return i, j
            return None
    return None


def _edit_inline(line: str, field: str, val: str) -> str:
    """Add or replace a member inside a one-line dictionary entry.

    Inline values cannot carry comments, so any comment is dropped.
    """
    val = re.sub(r"\s+#.*$", "", val)
    m = re.match(r'^(\s*".*?": \{)(.*?)(\},?\s*)$', line)
    if not m:
        raise InlineEntryError(line)
    prefix, inner, suffix = m.group(1), m.group(2).rstrip(), m.group(3)
    existing = re.search(r'("' + re.escape(field) + r'": )[^,}]+', inner)
    if existing:
        inner = inner[: existing.start(1)] + existing.group(1) + val + inner[existing.end() :]
    else:
        inner = f'{inner}{", " if inner else ""}"{field}": {val}'
    return f"{prefix}{inner}{suffix}"


def _field_range(lines: list[str], start: int, end: int, field: str) -> tuple[int, int] | None:
    """Find a field's first and last line indices.

    Multi-line dict and list values are followed to their closing line by brace balance.
    """
    pat = re.compile(r'^        "' + re.escape(field) + r'":')
    for i in range(start + 1, end):
        if pat.match(lines[i]):
            depth = 0
            for j in range(i, end):
                depth += sum(lines[j].count(c) for c in "{[") - sum(lines[j].count(c) for c in "}]")
                code = re.sub(r"\s+#.*$", "", lines[j])  # ignore a trailing comment
                if depth <= 0 and code.rstrip().endswith(","):
                    return i, j
            return i, i
    return None


def _member_line(field: str, val: str) -> str:
    """A new `"field": value,` dict member.

    The comma terminates the member and must sit before any trailing comment,
    else it gets commented out and breaks the dict.
    """
    cm = re.match(r"^(.*?)(\s+#.*)$", val)
    return f'        "{field}": {cm.group(1)},{cm.group(2)}' if cm else f'        "{field}": {val},'


def _apply_edit(lines: list[str], blk: tuple[int, int], field: str, val: EditValue) -> int:
    """Apply one field edit to a model's block in place; returns 1 if it changed, else 0."""
    s, e = blk
    if s == e:  # one-line inline entry
        if isinstance(val, _Remove):
            return 0
        lines[s] = _edit_inline(lines[s], field, val)
        return 1
    fr = _field_range(lines, s, e, field)
    if isinstance(val, _Remove):
        if not fr:
            return 0
        del lines[fr[0] : fr[1] + 1]
        return 1
    newline = _member_line(field, val)
    if fr:
        lines[fr[0] : fr[1] + 1] = [newline]
    else:
        lines.insert(s + 1, newline)
    return 1


def apply_edits(path: str, edits: Mapping[str, Mapping[str, EditValue]], warnings: list[str]) -> int:
    """Apply model-field edits to a source file and return the edit count.

    Re-scan after each change so line indices stay valid.
    """
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    n = 0
    for key, fields in edits.items():
        for field, val in fields.items():
            blk = _block_range(lines, key)
            if not blk:
                warnings.append(f"{Path(path).name}: {key!r} not found — skipped {field}")
                continue
            n += _apply_edit(lines, blk, field, val)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return n


def _plan_hidden(info: ModelInfo, verdict: str | None, today: str) -> str | _Remove | None:
    """The `hidden` edit the enablement probe calls for, if any."""
    hide = info.get("hidden")
    if verdict == "ENABLED" and hide and _ENABLEMENT_HIDE.search(hide) and info.get("type") in _ESTIMATE_DECIDES:
        return REMOVE
    if verdict == "DISABLED" and not hide:
        return f'"Not enabled for API access on this key (403)"  # audit {today}'
    return None


def _merged_ref_mode(info: ModelInfo, doc_refs: DocRefs) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Our current ref_mode, and it merged with the docs' numbers (curated keys survive)."""
    cur = _ref_mode_json(info.get("ref_mode") or {})
    types = [t for t in doc_refs["types"] if t in _REF_TYPES] or cur.get("types") or []
    merged: dict[str, JsonValue] = {**cur, "types": types, "max": doc_refs["max"]}
    limits = {**as_object(cur.get("limits")), **{str(k): v for k, v in doc_refs["limits"].items()}}
    if limits:
        merged["limits"] = limits
    return cur, merged


def _plan_refs(o: OurModel, doc_refs: DocRefs | None, edits: tuple[Edits, Edits], notes: list[str]) -> None:
    """Plan the ref_mode / HAS_REFS edits (img2vid models only) or a note for a human, for one model."""
    models_edits, engine_edits = edits
    key, info = o["key"], o["info"]
    if doc_refs and info.get("type") not in _ESTIMATE_DECIDES:
        notes.append(f"{key}: docs show a refs branch but this is a {info.get('type')} model — not auto-applied")
    elif doc_refs:
        cur, merged = _merged_ref_mode(info, doc_refs)
        if merged != cur:
            models_edits.setdefault(key, {})["ref_mode"] = py_literal(merged)
        if not o["cfg"].get("HAS_REFS"):
            engine_edits.setdefault(key, {})["HAS_REFS"] = "True"
    elif info.get("ref_mode"):
        notes.append(f"{key}: we declare ref_mode but docs show none — review by hand (may be a docs gap)")


def plan_writes(
    ours: Mapping[str, OurModel], docs: Mapping[str, DocFeature], enabled: Mapping[str, str]
) -> tuple[Edits, Edits, list[str]]:
    """Plan source edits and human-only notes from the model audit.

    Add or update ``ref_mode`` from docs but never remove it because the spec is
    incomplete; clear hides only when they were justified by enablement.
    """
    models_edits: Edits = {}
    engine_edits: Edits = {}
    notes: list[str] = []
    today = datetime.now().astimezone().date().isoformat()
    for slug, o in ours.items():
        # Enablement → hidden (needs the probe)
        hidden = _plan_hidden(o["info"], enabled.get(o["key"]), today)
        if hidden is not None:
            models_edits.setdefault(o["key"], {})["hidden"] = hidden
        # Features → ref_mode (+ engine HAS_REFS), merged so curated keys survive
        d = docs.get(slug)
        _plan_refs(o, d["refs"] if d else None, (models_edits, engine_edits), notes)
    return models_edits, engine_edits, notes


def _write(ours: Mapping[str, OurModel], docs: Mapping[str, DocFeature], enabled: Mapping[str, str]) -> None:
    """Apply the mechanical fixes to our source, then report; you review the diff."""
    models_edits, engine_edits, notes = plan_writes(ours, docs, enabled)
    warnings: list[str] = []
    n = apply_edits(str(MODELS_FILE), models_edits, warnings) + apply_edits(str(ENGINE_FILE), engine_edits, warnings)
    for w in warnings:
        write(f"  ! {w}")
    if notes:
        write("\nHand-review (not auto-applied):")
        for note in notes:
            write(f"  - {note}")
    write(f"\nApplied {n} edit(s) to pollo/models.py / video/models.py.")
    write("Run `ruff format` on them, then review with `git diff` before committing.")


def main() -> int:
    """Audit the local model catalogue against Pollo's docs and API key."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", help="path to a saved openapi.json (else fetched from docs.pollo.ai)")
    ap.add_argument("--key", default=os.getenv("POLLO_API_KEY"), help="probe live availability (or POLLO_API_KEY)")
    ap.add_argument(
        "--write",
        action="store_true",
        help="apply the mechanical fixes (hidden/ref_mode/HAS_REFS) to our source — review the git diff after",
    )
    args = ap.parse_args(namespace=_Args())

    docs = parse_docs(_load_spec(args.spec))
    ours = _our_models()
    enabled = _enablement([v["key"] for v in ours.values()], args.key) if args.key else {}

    if args.write:
        _write(ours, docs, enabled)
        return 0

    write(f"\n{'model (our key)':26} {'slug':22} docs enabled refs            notes")
    write("-" * 110)
    for slug, o in sorted(ours.items(), key=lambda kv: kv[1]["key"]):
        d = docs.get(slug)
        refs = d["refs"] if d else None
        refs_s = f"{refs['max']}:{','.join(refs['types'])}"[:15] if refs else "-"
        notes = "; ".join(_mismatches(o, d))
        if o["info"].get("hidden"):
            notes = (notes + "; " if notes else "") + "hidden in UI"
        write(f"{o['key']:26} {slug:22} {'Y' if d else '-':4} {enabled.get(o['key'], '?'):7} {refs_s:15} {notes}")

    # Models documented but absent from our registry — candidates to add.
    missing = sorted(set(docs) - set(ours))
    if missing:
        write("\nIn docs, not in our registry (candidates to add):")
        for slug in missing:
            r = docs[slug]["refs"]
            write(f"  {slug:28} {docs[slug]['path']}" + (f"  refs max {r['max']}" if r else ""))
    write(f"\n{len(ours)} models in registry, {len(docs)} documented, {len(missing)} documented-but-missing.")
    if enabled:
        write(f"{sum(1 for v in enabled.values() if v == 'ENABLED')}/{len(enabled)} enabled on this key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
