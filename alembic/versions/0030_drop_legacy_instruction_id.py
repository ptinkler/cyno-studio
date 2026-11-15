"""drop the legacy chat_conversations.instruction_id column.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-15

A chat's single attached instruction (added in 0005) was superseded by instruction_ids_json in 0011, which
carried every value across; nothing has read or written the column since. downgrade() puts it back, empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_conversations")}


def upgrade() -> None:
    """Drop the legacy single-instruction column."""
    if "instruction_id" in _columns():
        with op.batch_alter_table("chat_conversations") as batch_op:
            batch_op.drop_column("instruction_id")


def downgrade() -> None:
    """Add the legacy column back (empty)."""
    if "instruction_id" not in _columns():
        with op.batch_alter_table("chat_conversations") as batch_op:
            batch_op.add_column(sa.Column("instruction_id", sa.Integer(), nullable=True))
