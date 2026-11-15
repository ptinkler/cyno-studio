"""add global chat settings (default buckets).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-15

Global chat defaults move from the per-snippet/group `is_default` flag into a
single chat_settings row (id=1) holding default character/snippet/group id
lists. A space's own defaults stack on top of these. The old is_default columns
are left in place (unused) and their data is carried into chat_settings.
"""

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create chat settings."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "chat_settings" not in insp.get_table_names():
        op.create_table(
            "chat_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("default_character_ids_json", sa.Text(), nullable=True),
            sa.Column("default_instruction_ids_json", sa.Text(), nullable=True),
            sa.Column("default_instruction_group_ids_json", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if bind.execute(sa.text("SELECT 1 FROM chat_settings WHERE id = 1")).first():
        return
    # Carry the old is_default flags into the global bucket
    values: dict[str, str] = {}
    for field, table in (
        ("default_instruction_ids_json", "chat_instructions"),
        ("default_instruction_group_ids_json", "chat_instruction_groups"),
    ):
        if insp.has_table(table) and "is_default" in {c["name"] for c in insp.get_columns(table)}:
            flagged = sa.table(table, sa.column("id", sa.Integer), sa.column("is_default", sa.Boolean))
            ids = list(bind.execute(sa.select(flagged.c.id).where(flagged.c.is_default.is_(True))).scalars().all())
            if ids:
                values[field] = json.dumps(ids)
    settings = sa.table(
        "chat_settings",
        sa.column("id", sa.Integer),
        sa.column("updated_at", sa.DateTime()),
        *(sa.column(name, sa.Text()) for name in values),
    )
    bind.execute(
        sa.insert(settings).values(id=1, updated_at=datetime.now().astimezone().replace(tzinfo=None), **values)
    )


def downgrade() -> None:
    """Drop chat settings."""
    op.drop_table("chat_settings")
