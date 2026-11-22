from __future__ import annotations

from typing import Any

import requests


class BrainRHBackendClient:
    def __init__(self, base_url: str, *, worker_secret: str = ""):
        self.base_url = base_url.rstrip("/")
        self.worker_secret = worker_secret

    def _worker_headers(self) -> dict[str, str]:
        return {"X-BrainRH-Worker-Secret": self.worker_secret} if self.worker_secret else {}

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/v1/interview-appointments/{appointment_id}",
            headers=self._worker_headers(),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_worker_realtime_config(self, appointment_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/v1/interview-appointments/{appointment_id}/worker-realtime-config",
            headers=self._worker_headers(),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def push_worker_event(
        self,
        appointment_id: str,
        event: str,
        *,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/v1/interview-appointments/{appointment_id}/worker-events",
            headers=self._worker_headers(),
            json={
                "event": event,
                "details": details or {},
                "error": error,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def submit_tool_call(
        self,
        interview_id: str,
        *,
        appointment_id: str,
        call_id: str,
        name: str,
        arguments: Any,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/v1/realtime-interviews/{interview_id}/tool-calls",
            headers=self._worker_headers(),
            json={
                "appointmentId": appointment_id,
                "calls": [
                    {
                        "callId": call_id,
                        "name": name,
                        "arguments": arguments,
                        "rawArguments": arguments if isinstance(arguments, str) else None,
                        "event": event or {},
                    }
                ]
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
