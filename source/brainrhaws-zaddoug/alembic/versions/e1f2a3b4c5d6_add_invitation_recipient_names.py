"""Add optional recipient names to user invitations.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_invitations", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("user_invitations", sa.Column("last_name", sa.String(100), nullable=True))


def downgrade() -> None:
    # Recovery only; production rollback keeps the expanded schema.
    op.drop_column("user_invitations", "last_name")
    op.drop_column("user_invitations", "first_name")
