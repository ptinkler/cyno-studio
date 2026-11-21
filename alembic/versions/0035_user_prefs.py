"""add chat_settings.model_favourites_json and presets_json: the user's starred models and composer presets.

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
    """Add the columns."""
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_settings")}
    with op.batch_alter_table("chat_settings") as batch_op:
        for name in ("model_favourites_json", "presets_json"):
            if name not in have:
                batch_op.add_column(sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the columns."""
    with op.batch_alter_table("chat_settings") as batch_op:
        batch_op.drop_column("presets_json")
        batch_op.drop_column("model_favourites_json")
