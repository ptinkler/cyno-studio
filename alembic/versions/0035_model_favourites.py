"""add chat_settings.model_favourites_json, the user's starred models per picker kind.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-21

They lived in each browser's localStorage, so they were lost on another browser, device or host.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column."""
    if "model_favourites_json" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_settings")}:
        with op.batch_alter_table("chat_settings") as batch_op:
            batch_op.add_column(sa.Column("model_favourites_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("chat_settings") as batch_op:
        batch_op.drop_column("model_favourites_json")
