"""chat defaults apply live: take the copies of them out of existing chats.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16

The global and space defaults (characters, instruction snippets and groups)
used to be copied into a chat when it was made; now they apply to every chat
live, on top of what's attached to the chat itself (web/chat.py _inherited).
So each chat's own lists lose the ids its defaults now supply — otherwise
taking something out of the defaults would leave it in every older chat.
"""

import json
from collections.abc import Sequence
from typing import cast

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("character", "instruction", "instruction_group")


def _ids(raw: str | None) -> list[str]:
    try:
        return cast("list[str]", json.loads(raw)) if raw else []
    except json.JSONDecodeError:
        return []


def upgrade() -> None:
    """Apply default instructions to existing conversations."""
    bind = op.get_bind()
    default_cols = [f"default_{k}_ids_json" for k in KINDS]
    own_cols = [f"{k}_ids_json" for k in KINDS]
    settings = sa.table("chat_settings", sa.column("id", sa.Integer), *(sa.column(c, sa.Text()) for c in default_cols))
    spaces_t = sa.table("chat_spaces", sa.column("id", sa.Integer), *(sa.column(c, sa.Text()) for c in default_cols))
    convs = sa.table(
        "chat_conversations",
        sa.column("id", sa.String()),
        sa.column("space_id", sa.Integer),
        *(sa.column(c, sa.Text()) for c in own_cols),
    )
    glob_q = cast("sa.Select[tuple[str | None, ...]]", sa.select(*(settings.c[c] for c in default_cols)))
    glob = cast("tuple[str | None, ...] | None", bind.execute(glob_q.where(settings.c.id == 1)).first())
    spaces_q = cast(
        "sa.Select[tuple[int, *tuple[str | None, ...]]]",
        sa.select(spaces_t.c.id, *(spaces_t.c[c] for c in default_cols)),
    )
    spaces = {
        row[0]: row[1:]
        for row in cast(
            "list[tuple[int, *tuple[str | None, ...]]]",
            bind.execute(spaces_q).all(),
        )
    }
    convs_q = cast(
        "sa.Select[tuple[str, int | None, *tuple[str | None, ...]]]",
        sa.select(convs.c.id, convs.c.space_id, *(convs.c[c] for c in own_cols)),
    )
    for conv_id, space_id, *own in cast(
        "list[tuple[str, int | None, *tuple[str | None, ...]]]", bind.execute(convs_q).all()
    ):
        buckets = [b for b in (glob, spaces.get(space_id) if space_id is not None else None) if b]
        changes: dict[str, str] = {}
        for i, kind in enumerate(KINDS):
            inherited = {x for b in buckets for x in _ids(b[i])}
            ids = _ids(own[i])
            kept = [x for x in ids if x not in inherited]
            if kept != ids:
                changes[f"{kind}_ids_json"] = json.dumps(kept)
        if changes:
            bind.execute(sa.update(convs).where(convs.c.id == conv_id).values(changes))


def downgrade() -> None:
    """Keep applied defaults because their original sources are indistinguishable."""
    # the copies can't be told apart from what was attached by hand
