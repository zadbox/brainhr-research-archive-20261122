"""add access grants table

Revision ID: d2f4c1a7b9e0
Revises: b7a1c2d3e4f5
Create Date: 2026-05-11 20:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = "d2f4c1a7b9e0"
down_revision: Union[str, Sequence[str], None] = "b7a1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'client_admin'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'project_manager'")

    if inspector.has_table("access_grants"):
        return

    if dialect == "postgresql":
        scope_kind_enum = postgresql.ENUM(
            "client",
            "enterprise",
            "project",
            name="accessscopekind",
            create_type=False,
        )
        scope_kind_enum.create(bind, checkfirst=True)
        role_enum = postgresql.ENUM(
            "platform_admin",
            "client_admin",
            "enterprise_admin",
            "project_manager",
            "recruiter",
            "viewer",
            name="userrole",
            create_type=False,
        )
    else:
        scope_kind_enum = sa.Enum("client", "enterprise", "project", name="accessscopekind")
        role_enum = sa.Enum(
            "platform_admin",
            "client_admin",
            "enterprise_admin",
            "project_manager",
            "recruiter",
            "viewer",
            name="userrole",
        )

    op.create_table(
        "access_grants",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope_kind", scope_kind_enum, nullable=False),
        sa.Column("scope_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "scope_kind",
            "scope_id",
            "role",
            name="uq_access_grants_user_scope_role",
        ),
    )
    op.create_index(op.f("ix_access_grants_user_id"), "access_grants", ["user_id"], unique=False)
    op.create_index(op.f("ix_access_grants_scope_kind"), "access_grants", ["scope_kind"], unique=False)
    op.create_index(op.f("ix_access_grants_scope_id"), "access_grants", ["scope_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if inspector.has_table("access_grants"):
        op.drop_index(op.f("ix_access_grants_scope_id"), table_name="access_grants")
        op.drop_index(op.f("ix_access_grants_scope_kind"), table_name="access_grants")
        op.drop_index(op.f("ix_access_grants_user_id"), table_name="access_grants")
        op.drop_table("access_grants")

    if dialect == "postgresql":
        access_scope_kind = sa.Enum(name="accessscopekind")
        access_scope_kind.drop(bind, checkfirst=True)
