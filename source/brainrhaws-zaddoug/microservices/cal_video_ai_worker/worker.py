from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
import time

from .backend import BrainRHBackendClient
from .config import WorkerSettings


TERMINAL_APPOINTMENT_STATUSES = {"completed", "no_show", "cancelled", "failed"}


class CalVideoRoomAdapter(Protocol):
    def join(self, video_url: str, display_name: str) -> None:
        ...

    def wait_for_candidate(self, deadline: datetime) -> bool:
        ...

    def next_room_event(self, deadline: datetime) -> str:
        ...

    def leave(self) -> None:
        ...


class RealtimeAudioBridge(Protocol):
    def start(self, appointment: dict[str, Any]) -> None:
        ...

    def request_conclusion(self) -> None:
        ...

    def wait_until_idle(self, *, timeout: float) -> bool:
        ...

    def is_finalized(self) -> bool:
        ...

    def recording_artifact(self) -> dict[str, Any] | None:
        ...

    def stop(self) -> None:
        ...


class NullRealtimeAudioBridge:
    def start(self, appointment: dict[str, Any]) -> None:
        return None

    def request_conclusion(self) -> None:
        return None

    def wait_until_idle(self, *, timeout: float) -> bool:
        return True

    def is_finalized(self) -> bool:
        return False

    def recording_artifact(self) -> dict[str, Any] | None:
        return None

    def stop(self) -> None:
        return None


@dataclass
class WorkerResult:
    appointment_id: str
    status: str
    realtime_interview_id: str


class CalVideoInterviewWorker:
    def __init__(
        self,
        *,
        settings: WorkerSettings,
        backend: BrainRHBackendClient,
        room: CalVideoRoomAdapter,
        bridge: RealtimeAudioBridge | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.room = room
        self.bridge = bridge or NullRealtimeAudioBridge()

    def run(self, appointment_id: str) -> WorkerResult:
        appointment = self.backend.get_appointment(appointment_id)
        video_url = appointment.get("calcom_video_url")
        if not video_url:
            updated = self.backend.push_worker_event(
                appointment_id,
                "join_unavailable",
                details={"reason": "No joinable Cal Video URL"},
            )
            return self._result(updated)

        end_at = self._parse_datetime(appointment["end_at"])
        if datetime.now(timezone.utc) >= end_at:
            updated = self.backend.push_worker_event(appointment_id, "no_show")
            return self._result(updated)

        try:
            self.room.join(video_url, self.settings.ai_display_name)
            self.backend.push_worker_event(
                appointment_id,
                "joined",
                details={"video_url": video_url},
            )

            candidate_present = self.room.wait_for_candidate(end_at)
            if not candidate_present:
                updated = self.backend.push_worker_event(appointment_id, "no_show")
                return self._result(updated)

            self.backend.push_worker_event(appointment_id, "candidate_detected")
            stop_idle_audio = getattr(self.room, "stop_idle_audio", None)
            if callable(stop_idle_audio):
                stop_idle_audio()
            self.bridge.start(appointment)

            updated = self._run_until_deadline(appointment_id, end_at)
            return self._result(updated)
        except Exception as exc:
            self.bridge.stop()
            updated = self.backend.push_worker_event(
                appointment_id,
                "failed",
                details=self._details_with_recording({}),
                error=str(exc),
            )
            return self._result(updated)
        finally:
            self.bridge.stop()
            self.room.leave()

    def _run_until_deadline(self, appointment_id: str, end_at: datetime) -> dict[str, Any]:
        wrapping_sent = False
        last_update: dict[str, Any] | None = None
        candidate_absent_since: datetime | None = None

        while datetime.now(timezone.utc) < end_at:
            latest = self.backend.get_appointment(appointment_id)
            latest_status = str(latest.get("status") or "")
            if latest_status in TERMINAL_APPOINTMENT_STATUSES:
                return latest

            now = datetime.now(timezone.utc)
            if candidate_absent_since is not None:
                absent_for = (now - candidate_absent_since).total_seconds()
                if absent_for >= self.settings.candidate_absence_grace_seconds:
                    return self._complete_appointment(
                        appointment_id,
                        details={
                            **(last_update or {}),
                            "reason": "candidate_left_timeout",
                            "candidate_absence_grace_seconds": self.settings.candidate_absence_grace_seconds,
                        },
                    )

            remaining_seconds = (end_at - datetime.now(timezone.utc)).total_seconds()
            if not wrapping_sent and remaining_seconds <= self.settings.wrap_up_seconds:
                self.bridge.request_conclusion()
                last_update = self.backend.push_worker_event(appointment_id, "wrapping_up")
                wrapping_sent = True

            event = self.room.next_room_event(end_at)
            if event == "candidate_left":
                candidate_absent_since = datetime.now(timezone.utc)
                last_update = self.backend.push_worker_event(appointment_id, "candidate_left")
            elif event in {"candidate_joined", "candidate_rejoined"}:
                candidate_absent_since = None
                last_update = self.backend.push_worker_event(appointment_id, "resumed")
            elif event == "completed":
                return self._complete_appointment(appointment_id, details=last_update or {})
            elif event == "failed":
                self.bridge.stop()
                return self.backend.push_worker_event(
                    appointment_id,
                    "failed",
                    details=self._details_with_recording({}),
                    error="Erreur room Cal Video",
                )

            if self.bridge.is_finalized():
                return self._complete_appointment(
                    appointment_id,
                    details=last_update or {"reason": "realtime_finalized"},
                )

            time.sleep(self.settings.poll_interval_seconds)

        self.bridge.request_conclusion()
        self.bridge.wait_until_idle(timeout=35)
        return self._complete_appointment(appointment_id, details=last_update or {})

    def _complete_appointment(self, appointment_id: str, *, details: dict[str, Any]) -> dict[str, Any]:
        self.bridge.wait_until_idle(timeout=35)
        self.bridge.stop()
        details = self._details_with_recording(details)
        return self.backend.push_worker_event(appointment_id, "completed", details=details)

    def _details_with_recording(self, details: dict[str, Any]) -> dict[str, Any]:
        recording_artifact = self.bridge.recording_artifact()
        if not recording_artifact:
            return details
        return {**details, "local_recording": recording_artifact}

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    @staticmethod
    def _result(appointment: dict[str, Any]) -> WorkerResult:
        return WorkerResult(
            appointment_id=appointment["id"],
            status=appointment["status"],
            realtime_interview_id=appointment["realtime_interview_id"],
        )
