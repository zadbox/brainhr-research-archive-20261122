"""add secure user invitations

Revision ID: e4f5a6b7c8d9
Revises: c7d8e9f0a1b2
Create Date: 2026-08-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_ROLES = (
    "platform_admin",
    "client_admin",
    "enterprise_admin",
    "project_manager",
    "recruiter",
    "viewer",
)
INVITATION_SCOPES = ("global", "client", "enterprise")
INVITATION_STATUSES = (
    "pending_delivery",
    "sent",
    "delivery_failed",
    "accepted",
    "revoked",
    "expired",
)


def _enum_type(bind, values: tuple[str, ...], name: str, *, existing: bool = False) -> sa.Enum:
    if bind.dialect.name != "postgresql":
        return sa.Enum(*values, name=name)
    enum_type = postgresql.ENUM(*values, name=name, create_type=False)
    if not existing:
        enum_type.create(bind, checkfirst=True)
    return enum_type


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("users"):
        columns = {column["name"]: column for column in inspector.get_columns("users")}
        hashed_password = columns.get("hashed_password")
        if hashed_password and not hashed_password.get("nullable"):
            with op.batch_alter_table("users") as batch_op:
                batch_op.alter_column(
                    "hashed_password",
                    existing_type=hashed_password["type"],
                    nullable=True,
                )

    inspector = sa.inspect(bind)
    if inspector.has_table("user_invitations"):
        return

    scope_type = _enum_type(bind, INVITATION_SCOPES, "invitationscopekind")
    status_type = _enum_type(bind, INVITATION_STATUSES, "invitationstatus")
    role_type = _enum_type(bind, USER_ROLES, "userrole", existing=True)

    op.create_table(
        "user_invitations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("scope_kind", scope_type, nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("role", role_type, nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("membership_id", sa.String(), nullable=True),
        sa.Column("access_grant_id", sa.String(), nullable=True),
        sa.Column("user_was_existing", sa.Boolean(), nullable=False),
        sa.Column("send_attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"]),
        sa.ForeignKeyConstraint(["access_grant_id"], ["access_grants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "scope_kind",
            "scope_id",
            name="uq_user_invitations_user_scope",
        ),
    )
    for column in ("user_id", "email", "scope_kind", "scope_id", "status", "created_by_user_id"):
        op.create_index(
            op.f(f"ix_user_invitations_{column}"),
            "user_invitations",
            [column],
            unique=False,
        )
    op.create_index(
        op.f("ix_user_invitations_token_digest"),
        "user_invitations",
        ["token_digest"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("user_invitations"):
        for column in (
            "token_digest",
            "created_by_user_id",
            "status",
            "scope_id",
            "scope_kind",
            "email",
            "user_id",
        ):
            index_name = op.f(f"ix_user_invitations_{column}")
            op.drop_index(index_name, table_name="user_invitations")
        op.drop_table("user_invitations")

    null_passwords = bind.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE hashed_password IS NULL")
    ).scalar_one()
    if null_passwords:
        raise RuntimeError(
            "Downgrade refuse: des comptes invites sans mot de passe existent encore."
        )

    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("users")}
    hashed_password = columns.get("hashed_password")
    if hashed_password and hashed_password.get("nullable"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "hashed_password",
                existing_type=hashed_password["type"],
                nullable=False,
            )

    if bind.dialect.name == "postgresql":
        sa.Enum(name="invitationstatus").drop(bind, checkfirst=True)
        sa.Enum(name="invitationscopekind").drop(bind, checkfirst=True)
