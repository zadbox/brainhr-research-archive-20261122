"""Expand-only Google identities and ephemeral OAuth attempts."""
from alembic import op
import sqlalchemy as sa

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A legacy revision imports current models on clean installs.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("google_identities"):
        op.create_table(
            "google_identities",
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("subject", sa.String(255), nullable=False, unique=True),
            sa.Column("display_name", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("google_auth_attempts"):
        op.create_table(
            "google_auth_attempts",
            sa.Column("state_digest", sa.String(64), primary_key=True),
            sa.Column("browser_digest", sa.String(64), nullable=False),
            sa.Column("nonce_digest", sa.String(64), nullable=False),
            sa.Column("code_verifier", sa.String(128), nullable=False),
            sa.Column("purpose", sa.String(16), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("token_version", sa.Integer(), nullable=True),
            sa.Column("invitation_digest", sa.String(64), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_google_auth_attempts_expires_at", "google_auth_attempts", ["expires_at"])


def downgrade() -> None:
    # Recovery only; production rollback keeps the expanded schema.
    op.drop_table("google_auth_attempts")
    op.drop_table("google_identities")
