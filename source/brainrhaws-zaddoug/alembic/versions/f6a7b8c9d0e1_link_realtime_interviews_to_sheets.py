"""link realtime interviews to their canonical interview sheet

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-08-06 00:00:00.000000
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_realtime_interviews_interview_sheet_id_interview_sheets"
SHEET_INDEX = "ix_realtime_interviews_interview_sheet_id"
PROJECT_INDEX = "ix_realtime_interviews_project_id"
SLOT_INDEX = "uq_realtime_interviews_active_sheet_slot"
ACTIVE_APPOINTMENT_STATUSES = (
    "in_progress",
    "paused",
    "wrapping_up",
    "waiting_candidate",
    "scheduled",
)
EXPECTED_COLUMNS = {
    "interview_sheet_id",
    "project_id",
    "active_sheet_slot",
    "preparation_state",
    "preparation_lease_token",
    "preparation_lease_expires_at",
}


def expected_columns_present(columns: set[str]) -> bool:
    return EXPECTED_COLUMNS.issubset(columns)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _descending_key(value: Any) -> str:
    return "" if value is None else str(value)


def _backfill(bind) -> None:
    metadata = sa.MetaData()
    sheets_table = sa.Table("interview_sheets", metadata, autoload_with=bind)
    realtime_table = sa.Table("realtime_interviews", metadata, autoload_with=bind)
    appointments_table = sa.Table("interview_appointments", metadata, autoload_with=bind)

    sheets = {row["id"]: row for row in bind.execute(sa.select(sheets_table)).mappings()}
    realtime = {row["id"]: row for row in bind.execute(sa.select(realtime_table)).mappings()}
    appointments = list(bind.execute(sa.select(appointments_table)).mappings())

    appointments_by_realtime: dict[str, list[Any]] = {}
    appointments_by_sheet: dict[str, list[Any]] = {}
    sheet_by_realtime_pointer: dict[str, str] = {}
    for sheet_id, sheet in sheets.items():
        sheet_data = _json_object(sheet.get("data"))
        sheet_result = _json_object(sheet_data.get("realtime_interview"))
        pointed_id = sheet_result.get("interview_id") or sheet_result.get("interviewId")
        if pointed_id:
            sheet_by_realtime_pointer[pointed_id] = sheet_id
    for appointment in appointments:
        appointments_by_realtime.setdefault(appointment["realtime_interview_id"], []).append(appointment)
        appointments_by_sheet.setdefault(appointment["interview_sheet_id"], []).append(appointment)

    def latest_appointment(rows: list[Any]) -> Any:
        return max(
            rows,
            key=lambda row: (
                _descending_key(row.get("updated_at")),
                _descending_key(row.get("created_at")),
                _descending_key(row.get("id")),
            ),
        )

    linked_sheet_by_realtime: dict[str, str] = {}
    registry_by_realtime: dict[str, dict[str, Any]] = {}
    for realtime_id, record in realtime.items():
        plan = _json_object(record.get("plan_data"))
        registry = _json_object(plan.get("registryContext"))
        registry_by_realtime[realtime_id] = registry
        linked_sheet_id = None
        related_appointments = appointments_by_realtime.get(realtime_id, [])
        if related_appointments:
            linked_sheet_id = latest_appointment(related_appointments).get("interview_sheet_id")
        if not linked_sheet_id:
            linked_sheet_id = sheet_by_realtime_pointer.get(realtime_id)
        if not linked_sheet_id:
            candidate = registry.get("interviewSheetId")
            linked_sheet_id = candidate if candidate in sheets else None
        project_id = sheets.get(linked_sheet_id, {}).get("job_id") if linked_sheet_id else None
        if not project_id:
            project_id = registry.get("projectId")
        values = {
            "interview_sheet_id": linked_sheet_id,
            "project_id": project_id,
            "preparation_state": "ready",
        }
        bind.execute(
            realtime_table.update().where(realtime_table.c.id == realtime_id).values(**values)
        )
        if linked_sheet_id:
            linked_sheet_by_realtime[realtime_id] = linked_sheet_id

    winners: dict[str, str] = {}
    status_rank = {status: index for index, status in enumerate(ACTIVE_APPOINTMENT_STATUSES)}
    for sheet_id, sheet in sheets.items():
        sheet_appointments = appointments_by_sheet.get(sheet_id, [])

        active = [
            row
            for row in sheet_appointments
            if row.get("status") in status_rank
            and realtime.get(row.get("realtime_interview_id"), {}).get("status") != "completed"
        ]
        if active:
            newest_first = sorted(
                active,
                key=lambda row: (
                    _descending_key(row.get("updated_at")),
                    _descending_key(row.get("created_at")),
                    _descending_key(row.get("id")),
                ),
                reverse=True,
            )
            winner = min(newest_first, key=lambda row: status_rank[row.get("status")])
            winners[sheet_id] = winner["realtime_interview_id"]
            continue

        sheet_data = _json_object(sheet.get("data"))
        sheet_result = _json_object(sheet_data.get("realtime_interview"))
        sheet_realtime_id = sheet_result.get("interview_id") or sheet_result.get("interviewId")
        if sheet_realtime_id in realtime and realtime[sheet_realtime_id].get("status") != "completed":
            winners[sheet_id] = sheet_realtime_id
            continue

        non_completed_appointments = [
            row
            for row in sheet_appointments
            if realtime.get(row.get("realtime_interview_id"), {}).get("status") != "completed"
        ]
        if non_completed_appointments:
            winners[sheet_id] = latest_appointment(non_completed_appointments)["realtime_interview_id"]
            continue

        legacy_candidates = [
            record
            for realtime_id, record in realtime.items()
            if registry_by_realtime.get(realtime_id, {}).get("interviewSheetId") == sheet_id
            and record.get("status") != "completed"
        ]
        if legacy_candidates:
            legacy_rank = {"in_progress": 0, "ready": 1}
            newest_first = sorted(
                legacy_candidates,
                key=lambda row: (
                    _descending_key(row.get("updated_at")),
                    _descending_key(row.get("created_at")),
                    _descending_key(row.get("id")),
                ),
                reverse=True,
            )
            winner = min(newest_first, key=lambda row: legacy_rank.get(row.get("status"), 2))
            winners[sheet_id] = winner["id"]

    for sheet_id, realtime_id in winners.items():
        bind.execute(
            realtime_table.update()
            .where(realtime_table.c.id == realtime_id)
            .where(realtime_table.c.status != "completed")
            .values(
                interview_sheet_id=sheet_id,
                project_id=sheets[sheet_id].get("job_id"),
                active_sheet_slot=sheet_id,
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("realtime_interviews"):
        return

    columns = {column["name"] for column in inspector.get_columns("realtime_interviews")}
    foreign_keys = {foreign_key.get("name") for foreign_key in inspector.get_foreign_keys("realtime_interviews")}
    if not expected_columns_present(columns) or FK_NAME not in foreign_keys:
        with op.batch_alter_table("realtime_interviews") as batch_op:
            if "interview_sheet_id" not in columns:
                batch_op.add_column(sa.Column("interview_sheet_id", sa.String(), nullable=True))
            if "project_id" not in columns:
                batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
            if "active_sheet_slot" not in columns:
                batch_op.add_column(sa.Column("active_sheet_slot", sa.String(), nullable=True))
            if "preparation_state" not in columns:
                batch_op.add_column(
                    sa.Column("preparation_state", sa.String(), nullable=False, server_default="ready")
                )
            if "preparation_lease_token" not in columns:
                batch_op.add_column(sa.Column("preparation_lease_token", sa.String(), nullable=True))
            if "preparation_lease_expires_at" not in columns:
                batch_op.add_column(
                    sa.Column("preparation_lease_expires_at", sa.DateTime(timezone=True), nullable=True)
                )
            if FK_NAME not in foreign_keys:
                batch_op.create_foreign_key(
                    FK_NAME,
                    "interview_sheets",
                    ["interview_sheet_id"],
                    ["id"],
                )

    _backfill(bind)
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("realtime_interviews")}
    if SHEET_INDEX not in indexes:
        op.create_index(SHEET_INDEX, "realtime_interviews", ["interview_sheet_id"], unique=False)
    if PROJECT_INDEX not in indexes:
        op.create_index(PROJECT_INDEX, "realtime_interviews", ["project_id"], unique=False)
    if SLOT_INDEX not in indexes:
        op.create_index(SLOT_INDEX, "realtime_interviews", ["active_sheet_slot"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("realtime_interviews"):
        return

    op.drop_index(SLOT_INDEX, table_name="realtime_interviews")
    op.drop_index(SHEET_INDEX, table_name="realtime_interviews")
    op.drop_index(PROJECT_INDEX, table_name="realtime_interviews")

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("realtime_interviews") as batch_op:
            batch_op.drop_constraint(FK_NAME, type_="foreignkey")
            batch_op.drop_column("preparation_lease_expires_at")
            batch_op.drop_column("preparation_lease_token")
            batch_op.drop_column("preparation_state")
            batch_op.drop_column("active_sheet_slot")
            batch_op.drop_column("project_id")
            batch_op.drop_column("interview_sheet_id")
        return

    op.drop_constraint(FK_NAME, "realtime_interviews", type_="foreignkey")
    op.drop_column("realtime_interviews", "preparation_lease_expires_at")
    op.drop_column("realtime_interviews", "preparation_lease_token")
    op.drop_column("realtime_interviews", "preparation_state")
    op.drop_column("realtime_interviews", "active_sheet_slot")
    op.drop_column("realtime_interviews", "project_id")
    op.drop_column("realtime_interviews", "interview_sheet_id")
