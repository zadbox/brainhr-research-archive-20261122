"""Add the tenant-level client trial window.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("trial_duration_days", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("trial_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_tenants_trial_duration_days",
            "trial_duration_days IS NULL OR (trial_duration_days >= 1 AND trial_duration_days <= 365)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_constraint("ck_tenants_trial_duration_days", type_="check")
        batch_op.drop_column("trial_expires_at")
        batch_op.drop_column("trial_started_at")
        batch_op.drop_column("trial_duration_days")
