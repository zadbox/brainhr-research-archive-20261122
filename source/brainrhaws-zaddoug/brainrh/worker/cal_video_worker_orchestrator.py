"""Background orchestrator for scheduled Cal Video AI workers."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import os
from typing import Any

from sqlmodel import select

from brainrh.database import get_session
from brainrh.models.interview_appointment import (
    InterviewAppointmentDB,
    InterviewAppointmentStatus,
    InterviewMode,
    utc_now,
)
from brainrh.services.cal_video_worker_launcher import CalVideoWorkerLauncher
from brainrh.settings import get_cal_video_worker_mode


logger = logging.getLogger(__name__)


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def should_enable_cal_video_worker_orchestrator() -> bool:
    return _env_flag("CAL_VIDEO_WORKER_AUTOSTART") and get_cal_video_worker_mode() == "embedded"


def cal_video_worker_poll_interval_seconds() -> int:
    return max(5, _read_int("CAL_VIDEO_WORKER_POLL_INTERVAL_SECONDS", 15))


async def cal_video_worker_orchestrator_loop(interval_seconds: int | None = None) -> None:
    interval = interval_seconds or cal_video_worker_poll_interval_seconds()
    logger.info("Démarrage de l'orchestrateur Cal Video worker (interval: %ss)", interval)

    while True:
        try:
            results = await asyncio.to_thread(launch_due_cal_video_workers)
            launched = [result for result in results if result.get("status") == "started"]
            if launched:
                logger.info("Cal Video worker lancé pour %s appointment(s)", len(launched))
        except asyncio.CancelledError:
            logger.info("Orchestrateur Cal Video worker annulé / arrêté.")
            break
        except Exception as exc:
            logger.error("Erreur inattendue dans l'orchestrateur Cal Video worker: %s", exc, exc_info=True)

        await asyncio.sleep(interval)


def launch_due_cal_video_workers(limit: int = 20) -> list[dict[str, Any]]:
    if not should_enable_cal_video_worker_orchestrator():
        return []

    now = utc_now()
    launch_before = now + timedelta(seconds=CalVideoWorkerLauncher._lead_seconds())

    with get_session() as session:
        stmt = (
            select(InterviewAppointmentDB)
            .where(InterviewAppointmentDB.status == InterviewAppointmentStatus.scheduled.value)
            # Un entretien recruteur n'a pas d'agent IA à lancer.
            .where(InterviewAppointmentDB.interview_mode == InterviewMode.ai.value)
            .where(InterviewAppointmentDB.start_at <= launch_before)
            .where(InterviewAppointmentDB.end_at > now)
            .order_by(InterviewAppointmentDB.start_at.asc())
            .limit(limit)
        )
        appointments = [
            {
                "id": record.id,
                "start_at": record.start_at,
                "end_at": record.end_at,
                "calcom_video_url": record.calcom_video_url,
            }
            for record in session.exec(stmt).all()
        ]

    results: list[dict[str, Any]] = []
    for appointment in appointments:
        if not appointment.get("calcom_video_url"):
            result = CalVideoWorkerLauncher.mark_skipped(
                appointment["id"],
                reason="No joinable Cal Video URL",
            )
        else:
            result = CalVideoWorkerLauncher.schedule_or_launch(
                appointment["id"],
                start_at=appointment["start_at"],
                end_at=appointment["end_at"],
                now=now,
            )
        results.append({"appointment_id": appointment["id"], **result})
    return results
