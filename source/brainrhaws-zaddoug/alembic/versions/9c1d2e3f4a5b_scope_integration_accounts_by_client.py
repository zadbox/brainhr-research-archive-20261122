"""scope integration accounts by client or platform

Revision ID: 9c1d2e3f4a5b
Revises: 8f3b2c1d0a9e
Create Date: 2026-07-14 18:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "8f3b2c1d0a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}


def _constraint_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _enum_type(bind, values: tuple[str, ...], name: str) -> sa.Enum:
    if bind.dialect.name != "postgresql":
        return sa.Enum(*values, name=name)
    enum_type = postgresql.ENUM(*values, name=name, create_type=False)
    enum_type.create(bind, checkfirst=True)
    return enum_type


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    scope_kind_type = _enum_type(
        bind,
        ("client", "platform", "enterprise_legacy"),
        "integrationscopekind",
    )

    if inspector.has_table("integration_accounts"):
        columns = {column["name"] for column in inspector.get_columns("integration_accounts")}
        if "scope_kind" not in columns:
            op.add_column(
                "integration_accounts",
                sa.Column("scope_kind", scope_kind_type, nullable=True),
            )
        if "scope_id" not in columns:
            op.add_column(
                "integration_accounts",
                sa.Column("scope_id", sa.String(), nullable=True),
            )

        bind.execute(
            sa.text(
                """
                UPDATE integration_accounts
                SET scope_kind = 'enterprise_legacy',
                    scope_id = enterprise_id
                WHERE scope_kind IS NULL OR scope_id IS NULL
                """
            )
        )

        unresolved = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM integration_accounts
                WHERE scope_kind IS NULL OR scope_id IS NULL
                """
            )
        ).scalar_one()
        if unresolved:
            raise RuntimeError(
                "Migration impossible: une integration historique ne possède pas enterprise_id."
            )

        inspector = sa.inspect(bind)
        constraints = _constraint_names(inspector, "integration_accounts")
        with op.batch_alter_table("integration_accounts") as batch_op:
            if "uq_intaccount_ent_conn" in constraints:
                batch_op.drop_constraint("uq_intaccount_ent_conn", type_="unique")
            batch_op.alter_column("enterprise_id", existing_type=sa.String(), nullable=True)
            batch_op.alter_column(
                "scope_kind",
                existing_type=scope_kind_type,
                nullable=False,
            )
            batch_op.alter_column("scope_id", existing_type=sa.String(), nullable=False)

        inspector = sa.inspect(bind)
        constraints = _constraint_names(inspector, "integration_accounts")
        indexes = _index_names(inspector, "integration_accounts")
        if "uq_intaccount_scope_conn" not in constraints:
            with op.batch_alter_table("integration_accounts") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_intaccount_scope_conn",
                    ["scope_kind", "scope_id", "connector_id"],
                )
        if "ix_integration_accounts_scope_kind" not in indexes:
            op.create_index(
                "ix_integration_accounts_scope_kind",
                "integration_accounts",
                ["scope_kind"],
                unique=False,
            )
        if "ix_integration_accounts_scope_id" not in indexes:
            op.create_index(
                "ix_integration_accounts_scope_id",
                "integration_accounts",
                ["scope_id"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    if not inspector.has_table("connector_scope_policies"):
        scope_policy_type = _enum_type(
            bind,
            ("client_only", "platform_only", "client_or_platform"),
            "connectorscopepolicy",
        )
        op.create_table(
            "connector_scope_policies",
            sa.Column("connector_id", sa.String(), nullable=False),
            sa.Column(
                "scope_policy",
                scope_policy_type,
                nullable=False,
            ),
            sa.Column("updated_by_user_id", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("connector_id"),
        )
        op.create_index(
            "ix_connector_scope_policies_scope_policy",
            "connector_scope_policies",
            ["scope_policy"],
            unique=False,
        )
        op.create_index(
            "ix_connector_scope_policies_updated_by_user_id",
            "connector_scope_policies",
            ["updated_by_user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("integration_accounts"):
        non_legacy = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM integration_accounts
                WHERE scope_kind <> 'enterprise_legacy'
                """
            )
        ).scalar_one()
        if non_legacy:
            raise RuntimeError(
                "Downgrade refusé: des intégrations client ou plateforme existent."
            )

    if inspector.has_table("connector_scope_policies"):
        op.drop_index(
            "ix_connector_scope_policies_updated_by_user_id",
            table_name="connector_scope_policies",
        )
        op.drop_index(
            "ix_connector_scope_policies_scope_policy",
            table_name="connector_scope_policies",
        )
        op.drop_table("connector_scope_policies")

    inspector = sa.inspect(bind)
    if inspector.has_table("integration_accounts"):
        indexes = _index_names(inspector, "integration_accounts")
        if "ix_integration_accounts_scope_id" in indexes:
            op.drop_index(
                "ix_integration_accounts_scope_id",
                table_name="integration_accounts",
            )
        if "ix_integration_accounts_scope_kind" in indexes:
            op.drop_index(
                "ix_integration_accounts_scope_kind",
                table_name="integration_accounts",
            )

        constraints = _constraint_names(sa.inspect(bind), "integration_accounts")
        with op.batch_alter_table("integration_accounts") as batch_op:
            if "uq_intaccount_scope_conn" in constraints:
                batch_op.drop_constraint("uq_intaccount_scope_conn", type_="unique")
            batch_op.alter_column("enterprise_id", existing_type=sa.String(), nullable=False)
            batch_op.drop_column("scope_id")
            batch_op.drop_column("scope_kind")

        constraints = _constraint_names(sa.inspect(bind), "integration_accounts")
        if "uq_intaccount_ent_conn" not in constraints:
            with op.batch_alter_table("integration_accounts") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_intaccount_ent_conn",
                    ["enterprise_id", "connector_id"],
                )

    if bind.dialect.name == "postgresql":
        postgresql.ENUM(
            name="connectorscopepolicy",
            create_type=False,
        ).drop(bind, checkfirst=True)
        postgresql.ENUM(
            name="integrationscopekind",
            create_type=False,
        ).drop(bind, checkfirst=True)
