"""add users.session_version, so login cookies can be revoked.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-16

A login cookie carries the version its user had when it was made; raising the user's version (sign out other
devices, a new password) makes every older cookie stop working. Cookies made before this had no version and
count as version 0, so they keep working until then. downgrade() drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}


def upgrade() -> None:
    """Add the version, 0 for everyone."""
    if "session_version" not in _columns():
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Drop the version."""
    if "session_version" in _columns():
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("session_version")
