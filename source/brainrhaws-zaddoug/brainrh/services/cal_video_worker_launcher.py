from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from brainrh.database import get_session
from brainrh.models.interview_appointment import InterviewAppointmentDB, utc_now
from brainrh.paths import PROJECT_ROOT
from brainrh.settings import get_cal_video_worker_mode


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CalVideoWorkerLauncher:
    RUNNING_STATUSES = {"started"}

    @staticmethod
    def schedule_or_launch(
        appointment_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or utc_now()
        launch_after = CalVideoWorkerLauncher._as_utc(start_at) - timedelta(
            seconds=CalVideoWorkerLauncher._lead_seconds()
        )
        if now < launch_after:
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "scheduled",
                    "launch_after": launch_after.isoformat(),
                    "appointment_start_at": CalVideoWorkerLauncher._as_utc(start_at).isoformat(),
                },
            )
        if now >= CalVideoWorkerLauncher._as_utc(end_at):
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "skipped",
                    "reason": "Appointment window already ended",
                },
            )
        if get_cal_video_worker_mode() == "service":
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "scheduled_for_service",
                    "appointment_start_at": CalVideoWorkerLauncher._as_utc(start_at).isoformat(),
                },
            )
        return CalVideoWorkerLauncher.launch(appointment_id)

    @staticmethod
    def launch(appointment_id: str) -> dict[str, Any]:
        existing = CalVideoWorkerLauncher._read_launch_state(appointment_id)
        if existing.get("status") in CalVideoWorkerLauncher.RUNNING_STATUSES:
            pid = existing.get("pid")
            if isinstance(pid, int) and CalVideoWorkerLauncher._pid_is_running(pid):
                return existing

        if get_cal_video_worker_mode() == "service":
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "delegated_to_service",
                },
            )

        if not _env_flag("CAL_VIDEO_WORKER_AUTOSTART"):
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "skipped",
                    "reason": "CAL_VIDEO_WORKER_AUTOSTART disabled",
                },
            )

        missing = [
            name
            for name in ("BRAINRH_WORKER_EVENT_SECRET", "OPENAI_API_KEY")
            if not os.getenv(name, "").strip()
        ]
        if missing:
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "skipped",
                    "reason": f"Missing required env: {', '.join(missing)}",
                },
            )

        command = CalVideoWorkerLauncher._build_command(appointment_id)
        if not os.getenv("CAL_VIDEO_WORKER_COMMAND", "").strip():
            missing_runtime = CalVideoWorkerLauncher._missing_default_runtime()
            if missing_runtime:
                return CalVideoWorkerLauncher._record_launch_state(
                    appointment_id,
                    {
                        "status": "skipped",
                        "reason": f"Missing local worker runtime: {', '.join(missing_runtime)}",
                    },
                )

        log_path = CalVideoWorkerLauncher._log_path(appointment_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "BRAINRH_APPOINTMENT_ID": appointment_id,
            "BRAINRH_BACKEND_URL": os.getenv("BRAINRH_BACKEND_URL", "http://localhost:8000"),
            "PYTHONUNBUFFERED": "1",
        }

        try:
            with log_path.open("ab") as output:
                process = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception as exc:
            return CalVideoWorkerLauncher._record_launch_state(
                appointment_id,
                {
                    "status": "failed_to_start",
                    "error": str(exc),
                    "log_path": str(log_path),
                },
            )

        return CalVideoWorkerLauncher._record_launch_state(
            appointment_id,
            {
                "status": "started",
                "pid": process.pid,
                "command": command,
                "log_path": str(log_path),
            },
        )

    @staticmethod
    def mark_skipped(appointment_id: str, *, reason: str) -> dict[str, Any]:
        return CalVideoWorkerLauncher._record_launch_state(
            appointment_id,
            {
                "status": "skipped",
                "reason": reason,
            },
        )

    @staticmethod
    def _build_command(appointment_id: str) -> list[str]:
        raw_command = os.getenv("CAL_VIDEO_WORKER_COMMAND", "").strip()
        if raw_command:
            return [
                part.format(appointment_id=appointment_id)
                for part in shlex.split(raw_command)
            ]
        return [
            sys.executable,
            "-m",
            "microservices.cal_video_ai_worker.main",
            appointment_id,
        ]

    @staticmethod
    def _missing_default_runtime() -> list[str]:
        missing: list[str] = []
        if platform.system().lower() != "linux":
            missing.append("Linux container runtime")
        if find_spec("playwright") is None:
            missing.append("python package playwright")
        for binary in ("pulseaudio", "pactl", "parec", "ffmpeg"):
            if shutil.which(binary) is None:
                missing.append(binary)
        return missing

    @staticmethod
    def _log_path(appointment_id: str) -> Path:
        raw_dir = os.getenv("CAL_VIDEO_WORKER_LOG_DIR", "").strip()
        log_dir = Path(raw_dir) if raw_dir else PROJECT_ROOT / "logs" / "cal_video_workers"
        return log_dir / f"{appointment_id}.log"

    @staticmethod
    def _record_launch_state(appointment_id: str, state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **state,
            "requested_at": utc_now().isoformat(),
        }
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                return payload
            record.worker_state = {
                **(record.worker_state or {}),
                "launcher": payload,
            }
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
        return payload

    @staticmethod
    def _read_launch_state(appointment_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                return {}
            state = record.worker_state or {}
            launcher = state.get("launcher") if isinstance(state, dict) else {}
            return launcher if isinstance(launcher, dict) else {}

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        if os.name != "nt":
            try:
                status = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "stat="],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except OSError:
                return True
            if status.returncode != 0:
                return False
            if status.stdout.strip().startswith("Z"):
                return False
        return True

    @staticmethod
    def _lead_seconds() -> int:
        raw_value = os.getenv("CAL_VIDEO_WORKER_LEAD_SECONDS", "300").strip()
        try:
            return max(0, int(raw_value))
        except ValueError:
            return 300

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
