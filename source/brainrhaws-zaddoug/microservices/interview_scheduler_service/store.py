from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchedulerStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        db_path = Path(database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_interviews (
                    booking_uid TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    candidate_email TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def upsert_booking(
        self,
        *,
        booking_uid: str,
        provider: str,
        candidate_name: str,
        candidate_email: str,
        start_at: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_interviews (
                    booking_uid,
                    provider,
                    candidate_name,
                    candidate_email,
                    start_at,
                    status,
                    payload_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(booking_uid) DO UPDATE SET
                    provider=excluded.provider,
                    candidate_name=excluded.candidate_name,
                    candidate_email=excluded.candidate_email,
                    start_at=excluded.start_at,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    booking_uid,
                    provider,
                    candidate_name,
                    candidate_email,
                    start_at,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()

    def get_booking(self, booking_uid: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT booking_uid, provider, candidate_name, candidate_email, start_at,
                       status, payload_json, created_at, updated_at
                FROM scheduled_interviews
                WHERE booking_uid = ?
                """,
                (booking_uid,),
            ).fetchone()

        if row is None:
            return None

        return {
            "booking_uid": row["booking_uid"],
            "provider": row["provider"],
            "candidate_name": row["candidate_name"],
            "candidate_email": row["candidate_email"],
            "start_at": row["start_at"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
