"""Let an interview appointment be led by the AI agent or by a recruiter.

Existing rows keep the AI mode. A recruiter-led appointment has no realtime AI
session, so ``realtime_interview_id`` becomes nullable and a check constraint
keeps it mandatory for AI appointments. Recruiter interviews never take the
sheet's active slot: several of them can be planned for the same candidate.

Revision ID: 3f7a9c2e1b64
Revises: f2a3b4c5d6e7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "3f7a9c2e1b64"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None

TABLE = "interview_appointments"
MODE_INDEX = "ix_interview_appointments_interview_mode"
MODE_CHECK = "ck_interview_appointments_mode"
AI_REALTIME_CHECK = "ck_interview_appointments_ai_realtime"
NEW_COLUMNS = (
    ("title", sa.String()),
    ("interviewer_name", sa.String()),
    ("interviewer_email", sa.String()),
    ("meeting_format", sa.String()),
    ("meeting_url", sa.Text()),
    ("meeting_location", sa.Text()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # La table est créée depuis le modèle courant par a5c6d7e8f901 sur une base
    # vierge : chaque étape reste donc idempotente.
    if not inspector.has_table(TABLE):
        return

    columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch_op:
        if "interview_mode" not in columns:
            batch_op.add_column(
                sa.Column("interview_mode", sa.String(), nullable=False, server_default="ai")
            )
        for name, column_type in NEW_COLUMNS:
            if name not in columns:
                batch_op.add_column(sa.Column(name, column_type, nullable=True))
        if not columns["realtime_interview_id"]["nullable"]:
            batch_op.alter_column("realtime_interview_id", existing_type=sa.String(), nullable=True)

    inspector = sa.inspect(bind)
    if MODE_INDEX not in {index["name"] for index in inspector.get_indexes(TABLE)}:
        op.create_index(MODE_INDEX, TABLE, ["interview_mode"], unique=False)

    checks = {check["name"] for check in inspector.get_check_constraints(TABLE)}
    with op.batch_alter_table(TABLE) as batch_op:
        if MODE_CHECK not in checks:
            batch_op.create_check_constraint(MODE_CHECK, "interview_mode IN ('ai', 'human')")
        if AI_REALTIME_CHECK not in checks:
            batch_op.create_check_constraint(
                AI_REALTIME_CHECK,
                "interview_mode = 'human' OR realtime_interview_id IS NOT NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return

    human_rows = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE interview_mode = 'human'")
    ).scalar_one()
    if human_rows:
        raise RuntimeError(
            "Downgrade refusé : des entretiens recruteur existent et n'ont pas de session IA."
        )

    checks = {check["name"] for check in inspector.get_check_constraints(TABLE)}
    with op.batch_alter_table(TABLE) as batch_op:
        for name in (AI_REALTIME_CHECK, MODE_CHECK):
            if name in checks:
                batch_op.drop_constraint(name, type_="check")

    if MODE_INDEX in {index["name"] for index in inspector.get_indexes(TABLE)}:
        op.drop_index(MODE_INDEX, table_name=TABLE)

    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.alter_column("realtime_interview_id", existing_type=sa.String(), nullable=False)
        for name, _column_type in reversed(NEW_COLUMNS):
            batch_op.drop_column(name)
        batch_op.drop_column("interview_mode")
