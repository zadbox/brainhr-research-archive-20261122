from __future__ import annotations

import logging
import time
from datetime import timedelta
from threading import Lock, Thread

from brainrh.database import get_session
from brainrh.models.interview_appointment import (
    InterviewAppointmentDB,
    InterviewAppointmentStatus,
    InterviewMode,
    utc_now,
)
from brainrh.services.calcom_client import CalcomAPIError
from brainrh.settings import get_cal_video_worker_mode
from brainrh.services.cal_video_worker_launcher import CalVideoWorkerLauncher
from microservices.cal_video_ai_worker.backend import BrainRHBackendClient
from microservices.cal_video_ai_worker.cal_video_room import PlaywrightCalVideoRoomAdapter
from microservices.cal_video_ai_worker.config import get_settings
from microservices.cal_video_ai_worker.realtime_bridge import OpenAIRealtimeAudioBridge
from microservices.cal_video_ai_worker.worker import CalVideoInterviewWorker
from sqlmodel import select

from .cal_video_worker_orchestrator import cal_video_worker_poll_interval_seconds, should_enable_cal_video_worker_orchestrator


logger = logging.getLogger(__name__)
_ACTIVE_APPOINTMENTS: set[str] = set()
_ACTIVE_LOCK = Lock()


def _track_start(appointment_id: str) -> bool:
    with _ACTIVE_LOCK:
        if _ACTIVE_APPOINTMENTS:
            logger.warning(
                "worker-video: appointment %s skipped because another Cal Video session is active: %s",
                appointment_id,
                sorted(_ACTIVE_APPOINTMENTS),
            )
            return False
        _ACTIVE_APPOINTMENTS.add(appointment_id)
        return True


def _track_stop(appointment_id: str) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_APPOINTMENTS.discard(appointment_id)


def _has_active_appointment() -> bool:
    with _ACTIVE_LOCK:
        return bool(_ACTIVE_APPOINTMENTS)


def _due_appointment_ids(limit: int = 1) -> list[str]:
    now = utc_now()
    launch_before = now + timedelta(seconds=CalVideoWorkerLauncher._lead_seconds())
    with get_session() as session:
        stmt = (
            select(InterviewAppointmentDB.id)
            .where(InterviewAppointmentDB.status == InterviewAppointmentStatus.scheduled.value)
            # Un entretien recruteur n'a pas d'agent IA à lancer.
            .where(InterviewAppointmentDB.interview_mode == InterviewMode.ai.value)
            .where(InterviewAppointmentDB.start_at <= launch_before)
            .where(InterviewAppointmentDB.end_at > now)
            .order_by(InterviewAppointmentDB.start_at.asc())
            .limit(limit)
        )
        return [str(appointment_id) for appointment_id in session.exec(stmt).all()]


def _build_worker() -> CalVideoInterviewWorker:
    settings = get_settings()
    backend = BrainRHBackendClient(
        settings.backend_base_url,
        worker_secret=settings.worker_event_secret,
    )
    return CalVideoInterviewWorker(
        settings=settings,
        backend=backend,
        room=PlaywrightCalVideoRoomAdapter(settings),
        bridge=OpenAIRealtimeAudioBridge(settings=settings, backend=backend),
    )


def _run_appointment(appointment_id: str) -> None:
    if not _track_start(appointment_id):
        return
    try:
        logger.info("worker-video: launching appointment %s", appointment_id)
        worker = _build_worker()
        worker.run(appointment_id)
    except CalcomAPIError:
        logger.exception("worker-video: Cal.com failure for %s", appointment_id)
    except Exception:
        logger.exception("worker-video: unexpected failure for %s", appointment_id)
    finally:
        _track_stop(appointment_id)


def worker_video_service_loop() -> None:
    if get_cal_video_worker_mode() != "service":
        raise SystemExit("CAL_VIDEO_WORKER_MODE doit valoir service pour lancer worker-video")

    interval = cal_video_worker_poll_interval_seconds()
    logger.info("worker-video service started (poll interval: %ss)", interval)

    while True:
        try:
            if should_enable_cal_video_worker_orchestrator():
                logger.warning("embedded orchestrator mode still enabled; skipping worker-video service iteration")
            else:
                if _has_active_appointment():
                    time.sleep(interval)
                    continue
                for appointment_id in _due_appointment_ids():
                    thread = Thread(
                        target=_run_appointment,
                        args=(appointment_id,),
                        name=f"brainrh-worker-video-{appointment_id}",
                        daemon=True,
                    )
                    thread.start()
        except Exception:
            logger.exception("worker-video service iteration failed")
        time.sleep(interval)


if __name__ == "__main__":
    worker_video_service_loop()
