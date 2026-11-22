# -*- coding: utf-8 -*-
"""
Configuration SQLAlchemy et gestion des sessions.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import inspect
from sqlmodel import SQLModel, Session, create_engine

from brainrh.settings import (
    get_database_backend,
    get_database_connect_timeout_seconds,
    get_database_echo,
    get_database_max_overflow,
    get_database_pool_recycle_seconds,
    get_database_pool_size,
    get_database_pool_timeout_seconds,
    get_database_url,
    get_sqlite_database_path,
    is_sqlite_database_url,
    should_auto_create_schema,
)

DATABASE_URL = get_database_url()
SQLITE_DATABASE_PATH = get_sqlite_database_path(DATABASE_URL)

engine_kwargs = {
    "echo": get_database_echo(),
}

if is_sqlite_database_url(DATABASE_URL):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = get_database_pool_size()
    engine_kwargs["max_overflow"] = get_database_max_overflow()
    engine_kwargs["pool_timeout"] = get_database_pool_timeout_seconds()
    engine_kwargs["pool_recycle"] = get_database_pool_recycle_seconds()
    engine_kwargs["connect_args"] = {"connect_timeout": get_database_connect_timeout_seconds()}

engine = create_engine(DATABASE_URL, **engine_kwargs)


def init_db() -> None:
    """
    Initialise la base de données (crée toutes les tables)
    À appeler au démarrage de l'application
    """
    from .models import (
        CVMetaDB,
        EnterpriseDB,
        InterviewAppointmentDB,
        InterviewSheetDB,
        LLMProcessSettingDB,
        ProjectDB,
        RealtimeInterviewDB,
    )
    from .models.auth import TenantDB, UserDB, UserInvitationDB  # noqa: F401

    if not should_auto_create_schema():
        ensure_realtime_interview_schema()
        return

    SQLModel.metadata.create_all(engine)
    ensure_interview_appointment_schema()
    ensure_realtime_interview_schema()
    db_target = str(SQLITE_DATABASE_PATH) if SQLITE_DATABASE_PATH else get_database_backend(DATABASE_URL)
    print(f"[DB] Base de donnees initialisee: {db_target}")


def ensure_interview_appointment_schema() -> None:
    """Apply lightweight compatibility DDL for existing SQLite/Postgres DBs."""
    inspector = inspect(engine)
    if not inspector.has_table("interview_appointments"):
        return

    columns = {column["name"] for column in inspector.get_columns("interview_appointments")}
    with engine.begin() as connection:
        if "active_slot" not in columns:
            connection.exec_driver_sql("ALTER TABLE interview_appointments ADD COLUMN active_slot VARCHAR")
        if "interview_mode" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE interview_appointments ADD COLUMN interview_mode VARCHAR NOT NULL DEFAULT 'ai'"
            )
        for column_name, column_type in (
            ("title", "VARCHAR"),
            ("interviewer_name", "VARCHAR"),
            ("interviewer_email", "VARCHAR"),
            ("meeting_format", "VARCHAR"),
            ("meeting_url", "TEXT"),
            ("meeting_location", "TEXT"),
        ):
            if column_name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE interview_appointments ADD COLUMN {column_name} {column_type}"
                )

        connection.exec_driver_sql(
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
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_interview_appointments_active_slot "
            "ON interview_appointments(active_slot)"
        )


def ensure_realtime_interview_schema() -> None:
    """Fail clearly when an existing database missed the canonical-sheet migration."""
    inspector = inspect(engine)
    if not inspector.has_table("realtime_interviews"):
        return
    expected = {
        "interview_sheet_id",
        "project_id",
        "active_sheet_slot",
        "preparation_state",
        "preparation_lease_token",
        "preparation_lease_expires_at",
    }
    columns = {column["name"] for column in inspector.get_columns("realtime_interviews")}
    missing = sorted(expected - columns)
    if missing:
        raise RuntimeError(
            "Schéma realtime_interviews obsolète "
            f"(colonnes manquantes: {', '.join(missing)}). "
            "Exécutez `alembic upgrade head` avant de démarrer BrainRH."
        )


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager pour obtenir une session DB avec gestion des transactions

    Usage:
        with get_session() as session:
            enterprise = session.query(EnterpriseDB).first()
            session.commit()
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_direct() -> Session:
    """
    Retourne une session directe (pour les cas où context manager n'est pas adapté)
    IMPORTANT: L'appelant doit fermer la session manuellement
    """
    return Session(engine)


def get_session_dependency() -> Generator[Session, None, None]:
    """
    Dépendance FastAPI pour injecter une session SQLModel.

    `get_session()` est un context manager utilisable avec `with`, mais ne doit
    pas être passé directement à `Depends()`.
    """
    with get_session() as session:
        yield session


def database_healthcheck() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {
            "status": "ok",
            "backend": get_database_backend(DATABASE_URL),
        }
    except Exception as exc:
        return {
            "status": "error",
            "backend": get_database_backend(DATABASE_URL),
            "error": str(exc),
        }
