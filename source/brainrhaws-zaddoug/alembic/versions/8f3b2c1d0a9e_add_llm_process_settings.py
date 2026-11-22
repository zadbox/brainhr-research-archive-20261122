"""add llm process settings

Revision ID: 8f3b2c1d0a9e
Revises: d2f4c1a7b9e0
Create Date: 2026-06-28 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f3b2c1d0a9e"
down_revision: Union[str, Sequence[str], None] = "d2f4c1a7b9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("llm_process_settings"):
        return
    op.create_table(
        "llm_process_settings",
        sa.Column("process_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("process_id"),
    )
    op.create_index(op.f("ix_llm_process_settings_provider"), "llm_process_settings", ["provider"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("llm_process_settings"):
        return
    op.drop_index(op.f("ix_llm_process_settings_provider"), table_name="llm_process_settings")
    op.drop_table("llm_process_settings")
