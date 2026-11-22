"""add Turnover IT publication and application inbox tables

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("turnover_job_publications"):
        op.create_table(
            "turnover_job_publications",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("enterprise_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("contract", sa.String(), nullable=False),
            sa.Column("remote", sa.String(), nullable=False, server_default="NONE"),
            sa.Column("country", sa.String(), nullable=False),
            sa.Column("region", sa.String(), nullable=True),
            sa.Column("postal_code", sa.String(), nullable=True),
            sa.Column("requested_status", sa.String(), nullable=False, server_default="Draft"),
            sa.Column("callback_url", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("remote_job_id", sa.String(), nullable=True),
            sa.Column("remote_public_url", sa.String(), nullable=True),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_turnover_job_publications_tenant_id", "turnover_job_publications", ["tenant_id"])
        op.create_index("ix_turnover_job_publications_enterprise_id", "turnover_job_publications", ["enterprise_id"])
        op.create_index("ix_turnover_job_publications_project_id", "turnover_job_publications", ["project_id"])
        op.create_index("ix_turnover_job_publications_status", "turnover_job_publications", ["status"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("turnover_application_inbox"):
        op.create_table(
            "turnover_application_inbox",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("publication_id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
            sa.ForeignKeyConstraint(["publication_id"], ["turnover_job_publications.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "publication_id", "payload_hash", name="uq_turnover_inbox_publication_hash"
            ),
        )
        op.create_index("ix_turnover_application_inbox_publication_id", "turnover_application_inbox", ["publication_id"])
        op.create_index("ix_turnover_application_inbox_tenant_id", "turnover_application_inbox", ["tenant_id"])


def downgrade() -> None:
    # Expand-only: data-bearing integration tables are intentionally not dropped.
    pass
