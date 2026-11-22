"""add tenant cv templates and enterprise tenant

Revision ID: b7a1c2d3e4f5
Revises: a5c6d7e8f901
Create Date: 2026-05-10 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "b7a1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "a5c6d7e8f901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    enterprise_columns = {column["name"] for column in inspector.get_columns("enterprises")}
    if "tenant_id" not in enterprise_columns:
        op.add_column(
            "enterprises",
            sa.Column("tenant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        )
        op.create_index(op.f("ix_enterprises_tenant_id"), "enterprises", ["tenant_id"], unique=False)
        op.create_foreign_key(
            "fk_enterprises_tenant_id_tenants",
            "enterprises",
            "tenants",
            ["tenant_id"],
            ["id"],
        )

    if not inspector.has_table("tenant_cv_templates"):
        op.create_table(
            "tenant_cv_templates",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("tenant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("original_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("storage_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("metadata_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("is_valid", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("uploaded_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_tenant_cv_templates_tenant_id"), "tenant_cv_templates", ["tenant_id"], unique=False)
        op.create_index(op.f("ix_tenant_cv_templates_name"), "tenant_cv_templates", ["name"], unique=False)
        op.create_index(
            op.f("ix_tenant_cv_templates_content_hash"),
            "tenant_cv_templates",
            ["content_hash"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("tenant_cv_templates"):
        op.drop_index(op.f("ix_tenant_cv_templates_content_hash"), table_name="tenant_cv_templates")
        op.drop_index(op.f("ix_tenant_cv_templates_name"), table_name="tenant_cv_templates")
        op.drop_index(op.f("ix_tenant_cv_templates_tenant_id"), table_name="tenant_cv_templates")
        op.drop_table("tenant_cv_templates")

    enterprise_columns = {column["name"] for column in inspector.get_columns("enterprises")}
    if "tenant_id" in enterprise_columns:
        op.drop_constraint("fk_enterprises_tenant_id_tenants", "enterprises", type_="foreignkey")
        op.drop_index(op.f("ix_enterprises_tenant_id"), table_name="enterprises")
        op.drop_column("enterprises", "tenant_id")
