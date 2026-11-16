"""The audit's --write editor must make only the intended surgical change.

That is, to a model entry, leaving everything else (including curated fields) intact.
"""

import ast
from pathlib import Path
from typing import cast

import pytest
from pydantic import TypeAdapter

from scripts import audit_pollo_models as audit
from scripts.audit_pollo_models import DocFeature, DocRefs, OurModel
from tests.jsonpath import dig, obj
from web.providers.pollo.engine.video import VideoRow
from web.providers.pollo.models import ModelInfo
from web.types import JsonValue

_MODEL_INFO_VALUE = TypeAdapter(dict[str, JsonValue])


def _model_info(src: str) -> dict[str, JsonValue]:
    """The MODEL_INFO literal from generated source, parsed rather than run.

    Proves the output is valid Python and reads the value back without
    executing it, which exec would.
    """
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MODEL_INFO" for target in node.targets
        ):
            return _MODEL_INFO_VALUE.validate_python(cast("object", ast.literal_eval(node.value)))
    pytest.fail("generated source defines no MODEL_INFO")


pytestmark = pytest.mark.no_tenant

SAMPLE = """MODEL_INFO = {
    "alpha": {
        "label": "Alpha",
        "type": "img2vid",
        "hidden": "Not enabled for API access on this key (403)",  # old
        "options": ["image_tail"],
    },
    "beta": {
        "label": "Beta",
        "type": "img2vid",
        "ref_mode": {
            "types": ["image", "video"],
            "max": 7,
            "limits": {"image": 4, "video": 1},
            "no_audio_with_video": True,
        },
    },
}
"""


def _write_apply(tmp_path: Path, edits: audit.Edits) -> tuple[str, int, list[str]]:
    f = tmp_path / "m.py"
    f.write_text(SAMPLE, encoding="utf-8")
    warnings: list[str] = []
    n = audit.apply_edits(str(f), edits, warnings)
    return f.read_text(encoding="utf-8"), n, warnings


def test_py_literal_double_quotes_and_bools() -> None:
    """Test that py literal double quotes and bools."""
    assert audit.py_literal({"types": ["image"], "max": 7, "no_audio_with_video": True}) == (
        '{"types": ["image"], "max": 7, "no_audio_with_video": True}'
    )


def test_remove_hidden_leaves_rest(tmp_path: Path) -> None:
    """Test that remove hidden leaves rest."""
    out, n, warns = _write_apply(tmp_path, {"alpha": {"hidden": audit.REMOVE}})
    assert n == 1
    assert not warns
    assert '"hidden"' not in out.split('"beta"')[0]  # alpha's hidden gone
    assert '"label": "Alpha"' in out
    assert '"options": ["image_tail"]' in out


def test_insert_field(tmp_path: Path) -> None:
    """Test that insert field."""
    out, n, _ = _write_apply(tmp_path, {"alpha": {"ref_mode": '{"types": ["image"], "max": 3}'}})
    assert n == 1
    assert '"ref_mode": {"types": ["image"], "max": 3},' in out
    # still valid Python
    assert dig(_model_info(out), "alpha", "ref_mode") == {"types": ["image"], "max": 3}


def test_replace_multiline_refmode_preserving_curated(tmp_path: Path) -> None:
    # The caller merges; here we just prove a multi-line value is replaced wholesale.
    """Test that replace multiline refmode preserving curated."""
    merged = audit.py_literal(
        {"types": ["image", "video"], "max": 15, "limits": {"image": 10, "video": 5}, "no_audio_with_video": True}
    )
    out, n, warns = _write_apply(tmp_path, {"beta": {"ref_mode": merged}})
    assert n == 1
    assert not warns
    rm = obj(_model_info(out), "beta", "ref_mode")
    assert rm["max"] == 15
    assert dig(rm, "limits", "image") == 10
    assert rm["no_audio_with_video"] is True


def test_value_with_trailing_comment_stays_valid(tmp_path: Path) -> None:
    # The comma must land before the comment, not inside it.
    """Test that value with trailing comment stays valid."""
    val = '"Not enabled for API access (403)"  # 2026-11-09 probe'
    out, n, _ = _write_apply(tmp_path, {"alpha": {"hidden": val}})
    assert n == 1
    assert '"hidden": "Not enabled for API access (403)",  # 2026-11-09 probe' in out
    assert dig(_model_info(out), "alpha", "hidden") == "Not enabled for API access (403)"


def test_one_line_inline_entry(tmp_path: Path) -> None:
    """Test that one line inline entry."""
    src = 'MODEL_INFO = {\n    "inline": {"label": "In", "type": "motion", "video_input": True},\n}\n'
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    warnings: list[str] = []
    n = audit.apply_edits(str(f), {"inline": {"hidden": '"gated (403)"  # note'}}, warnings)
    out = f.read_text(encoding="utf-8")
    assert n == 1
    assert not warnings
    assert dig(_model_info(out), "inline") == {
        "label": "In",
        "type": "motion",
        "video_input": True,
        "hidden": "gated (403)",
    }


def test_unknown_model_warns_and_skips(tmp_path: Path) -> None:
    """Test that unknown model warns and skips."""
    out, n, warns = _write_apply(tmp_path, {"missing": {"hidden": audit.REMOVE}})
    assert n == 0
    assert warns
    assert out == SAMPLE


def test_write_targets_exist_and_hold_what_it_edits() -> None:
    """Test that the files --write edits exist (a moved file once broke it silently) and hold those fields."""
    assert audit.MODELS_FILE.is_file()
    assert audit.ENGINE_FILE.is_file()
    assert '"HAS_REFS"' in audit.ENGINE_FILE.read_text(encoding="utf-8")


def _ours(key: str, info: ModelInfo, cfg: VideoRow | None = None) -> dict[str, OurModel]:
    return {key: {"key": key, "info": info, "cfg": cfg or {}}}


def _docs(slug: str, refs: DocRefs | None) -> dict[str, DocFeature]:
    return {slug: {"path": f"/generation/x/{slug}/video", "refs": refs, "resolutions": None, "ratios": None}}


EDIT_HIDE = "Not enabled for API access on this key (403)"


def test_an_estimate_never_unhides_a_media_input_model() -> None:
    """Test that ENABLED clears a hide only for img2vid: a video-edit model's estimate can't see its 403 gate."""
    edit: ModelInfo = {"label": "Edit", "type": "video_edit", "options": [], "hidden": EDIT_HIDE}
    image: ModelInfo = {"label": "I2V", "type": "img2vid", "options": [], "hidden": EDIT_HIDE}
    ours = {"e": _ours("edit", edit)["edit"], "i": _ours("image", image)["image"]}
    models_edits, _, _ = audit.plan_writes(ours, {}, {"edit": "ENABLED", "image": "ENABLED"})
    assert "edit" not in models_edits
    assert models_edits["image"]["hidden"] is audit.REMOVE


def test_a_403_hides_any_model() -> None:
    """Test that a definitive 403 still hides a model, whatever its type."""
    info: ModelInfo = {"label": "Edit", "type": "video_edit", "options": []}
    models_edits, _, _ = audit.plan_writes(_ours("edit", info), {}, {"edit": "DISABLED"})
    assert "hidden" in models_edits["edit"]


def test_docs_refs_merge_into_the_curated_ref_mode() -> None:
    """Test that docs numbers update the cap but keep curated per-type limits and drop types we don't support."""
    info: ModelInfo = {
        "label": "Seedance",
        "type": "img2vid",
        "options": ["refs"],
        "ref_mode": {"types": ["image", "video", "audio"], "max": 15, "limits": {"image": 9, "video": 3, "audio": 3}},
    }
    docs = _docs("seedance-x", {"max": 12, "types": ["image", "video", "audio", "element"], "limits": {"image": 8}})
    ours = {"seedance-x": _ours("seedance", info)["seedance"]}
    models_edits, _, _ = audit.plan_writes(ours, docs, {})
    edit = models_edits["seedance"]["ref_mode"]
    assert isinstance(edit, str)
    assert '"element"' not in edit
    assert '"limits": {"image": 8, "video": 3, "audio": 3}' in edit
    assert '"max": 12' in edit


def test_refs_are_not_applied_to_a_video_edit_model() -> None:
    """Test that a documented refs branch on an edit model is a note for a human, not an edit."""
    info: ModelInfo = {"label": "Wan edit", "type": "video_edit", "options": []}
    ours = {"wan-edit": _ours("wanedit", info)["wanedit"]}
    docs = _docs("wan-edit", {"max": 10, "types": ["image", "video"], "limits": {}})
    models_edits, engine_edits, notes = audit.plan_writes(ours, docs, {})
    assert models_edits == {}
    assert engine_edits == {}
    assert any("wanedit" in n and "not auto-applied" in n for n in notes)
