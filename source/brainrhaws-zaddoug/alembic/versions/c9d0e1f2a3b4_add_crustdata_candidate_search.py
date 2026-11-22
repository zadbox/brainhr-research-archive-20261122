"""add tenant-scoped Crustdata candidate search

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("crustdata_criteria",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("enterprise_id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("offer_derived_json", sa.Text(), nullable=False), sa.Column("current_json", sa.Text(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "enterprise_id", "project_id", name="uq_crustdata_criteria_scope"))
    op.create_index("ix_crustdata_criteria_tenant", "crustdata_criteria", ["tenant_id", "enterprise_id", "project_id"])
    op.create_table("crustdata_search_sessions",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("enterprise_id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False), sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("compiled_query_json", sa.Text(), nullable=False), sa.Column("next_cursor", sa.String()),
        sa.Column("requested_count", sa.Integer(), nullable=False), sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operation_id", name="uq_crustdata_search_session_operation"))
    op.create_index("ix_crustdata_search_session_scope", "crustdata_search_sessions", ["tenant_id", "enterprise_id", "project_id"])
    op.create_table("crustdata_search_results",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("search_session_id", sa.String(), sa.ForeignKey("crustdata_search_sessions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("enterprise_id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("provider_person_id", sa.String(), nullable=False), sa.Column("normalized_profile_url", sa.String()),
        sa.Column("lightweight_json", sa.Text(), nullable=False), sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("search_session_id", "provider_person_id", name="uq_crustdata_search_result_person"))
    op.create_index("ix_crustdata_search_result_scope", "crustdata_search_results", ["tenant_id", "enterprise_id", "project_id"])
    op.create_index("ix_crustdata_search_result_url", "crustdata_search_results", ["normalized_profile_url"])
    op.create_table("crustdata_wallets",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("scope_kind", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False), sa.Column("balance", sa.Numeric(20, 6), nullable=False),
        sa.Column("reserved", sa.Numeric(20, 6), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_last_synced_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scope_kind", "scope_id", name="uq_crustdata_wallet_scope"))
    op.create_table("crustdata_credit_operations",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("user_id", sa.String(), nullable=False), sa.Column("project_id", sa.String()),
        sa.Column("operation_type", sa.String(), nullable=False), sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("returned_or_matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_credits", sa.Numeric(20, 6), nullable=False), sa.Column("reported_credits_exact", sa.Numeric(20, 6)),
        sa.Column("settled_credits", sa.Numeric(20, 6)), sa.Column("provider_balance_before_or_last_known", sa.Numeric(20, 6)),
        sa.Column("provider_balance_after_or_next_sync", sa.Numeric(20, 6)), sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String()), sa.Column("response_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("operation_id", name="uq_crustdata_credit_operation_operation"))
    op.create_index("ix_crustdata_credit_operation_tenant", "crustdata_credit_operations", ["tenant_id", "created_at"])
    op.create_table("crustdata_identities",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("provider_person_id", sa.String(), nullable=False), sa.Column("normalized_profile_url", sa.String(), nullable=False),
        sa.Column("raw_snapshot_path", sa.String()), sa.Column("source_last_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider_person_id", name="uq_crustdata_identity_person"),
        sa.UniqueConstraint("tenant_id", "normalized_profile_url", name="uq_crustdata_identity_url"))
    op.create_table("crustdata_identity_enterprises",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("identity_id", sa.String(), sa.ForeignKey("crustdata_identities.id"), nullable=False),
        sa.Column("enterprise_id", sa.String(), nullable=False), sa.Column("talent_profile_id", sa.Integer(), sa.ForeignKey("talent_profiles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("identity_id", "enterprise_id", name="uq_crustdata_identity_enterprise"))
    op.create_index("ix_crustdata_identity_enterprise_talent", "crustdata_identity_enterprises", ["enterprise_id", "talent_profile_id"])


def downgrade() -> None:
    for table in ("crustdata_identity_enterprises", "crustdata_identities", "crustdata_credit_operations", "crustdata_wallets", "crustdata_search_results", "crustdata_search_sessions", "crustdata_criteria"):
        op.drop_table(table)
