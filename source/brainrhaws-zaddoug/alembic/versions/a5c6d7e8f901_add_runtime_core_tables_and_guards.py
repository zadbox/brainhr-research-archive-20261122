"""add runtime core tables and guards

Revision ID: a5c6d7e8f901
Revises: 7e5f79ba4607
Create Date: 2026-04-29 04:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from brainrh.models.cv import CVMetaDB
from brainrh.models.enterprise import EnterpriseDB
from brainrh.models.integration import (
    DeliveryAttemptDB,
    IntegrationAccountDB,
    OutboundEventDB,
    WebhookSubscriptionDB,
)
from brainrh.models.interview_appointment import InterviewAppointmentDB
from brainrh.models.interview_sheet import InterviewSheetDB
from brainrh.models.project import ProjectDB
from brainrh.models.realtime_interview import RealtimeInterviewDB


# revision identifiers, used by Alembic.
revision: str = "a5c6d7e8f901"
down_revision: Union[str, Sequence[str], None] = "7e5f79ba4607"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_table_if_missing(bind, table) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table.name):
        table.create(bind=bind, checkfirst=True)
    for index in table.indexes:
        index.create(bind=bind, checkfirst=True)


def upgrade() -> None:
    bind = op.get_bind()

    for table in (
        EnterpriseDB.__table__,
        ProjectDB.__table__,
        CVMetaDB.__table__,
        InterviewSheetDB.__table__,
        RealtimeInterviewDB.__table__,
        InterviewAppointmentDB.__table__,
        IntegrationAccountDB.__table__,
        WebhookSubscriptionDB.__table__,
        OutboundEventDB.__table__,
        DeliveryAttemptDB.__table__,
    ):
        _create_table_if_missing(bind, table)

    inspector = sa.inspect(bind)

    if inspector.has_table("realtime_interviews"):
        columns = {column["name"] for column in inspector.get_columns("realtime_interviews")}
        if "owner_user_id" not in columns:
            op.add_column(
                "realtime_interviews",
                sa.Column("owner_user_id", sa.String(), nullable=True, server_default="system-migration"),
            )
            op.create_index(
                op.f("ix_realtime_interviews_owner_user_id"),
                "realtime_interviews",
                ["owner_user_id"],
                unique=False,
            )
            op.alter_column("realtime_interviews", "owner_user_id", server_default=None)

    inspector = sa.inspect(bind)
    if inspector.has_table("interview_appointments"):
        columns = {column["name"] for column in inspector.get_columns("interview_appointments")}
        if "active_slot" not in columns:
            op.add_column("interview_appointments", sa.Column("active_slot", sa.String(), nullable=True))

        bind.execute(
            sa.text(
                """
                UPDATE interview_appointments
                SET active_slot = interview_sheet_id
                WHERE active_slot IS NULL
                  AND status IN ('scheduled', 'waiting_candidate', 'in_progress', 'paused', 'wrapping_up')
                  AND interview_sheet_id IN (
                      SELECT interview_sheet_id
                      FROM interview_appointments
                      WHERE status IN ('scheduled', 'waiting_candidate', 'in_progress', 'paused', 'wrapping_up')
                      GROUP BY interview_sheet_id
                      HAVING COUNT(*) = 1
                  )
                """
            )
        )
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_interview_appointments_active_slot "
                "ON interview_appointments(active_slot)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("realtime_interviews"):
        columns = {column["name"] for column in inspector.get_columns("realtime_interviews")}
        if "owner_user_id" in columns:
            op.drop_index(op.f("ix_realtime_interviews_owner_user_id"), table_name="realtime_interviews")
            op.drop_column("realtime_interviews", "owner_user_id")
