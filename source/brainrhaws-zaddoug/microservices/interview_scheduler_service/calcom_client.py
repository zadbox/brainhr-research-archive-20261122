from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class CalcomAPIError(RuntimeError):
    """Erreur de communication ou de contrat avec Cal.com."""


class CalcomClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(
            base_url=self.settings.calcom_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.settings.calcom_api_key}",
                "cal-api-version": self.settings.calcom_api_version,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def create_booking(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/bookings", json=payload)

    def get_booking(self, booking_uid: str) -> dict[str, Any]:
        return self._request("GET", f"/bookings/{booking_uid}")

    def add_guests(self, booking_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/bookings/{booking_uid}/guests", json=payload)

    def cancel_booking(self, booking_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/bookings/{booking_uid}/cancel", json=payload)

    def get_calendar_links(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/bookings/{booking_uid}/calendar-links")
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_booking_references(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/references",
            api_version=self.settings.calcom_artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_conferencing_sessions(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/conferencing-sessions",
            api_version=self.settings.calcom_artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_recordings(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/recordings",
            api_version=self.settings.calcom_artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_transcripts(self, booking_uid: str) -> list[Any]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/transcripts",
            api_version=self.settings.calcom_transcript_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_calendars(self) -> dict[str, Any]:
        return self._request("GET", "/calendars")

    def get_conferencing_apps(self) -> dict[str, Any]:
        return self._request("GET", "/conferencing")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        api_version: str | None = None,
    ) -> dict[str, Any]:
        headers = None
        if api_version:
            headers = {"cal-api-version": api_version}

        try:
            response = self._client.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise CalcomAPIError(f"Erreur réseau Cal.com: {exc}") from exc

        payload: dict[str, Any]
        try:
            payload = response.json()
        except ValueError as exc:
            raise CalcomAPIError(
                f"Réponse Cal.com non JSON ({response.status_code})"
            ) from exc

        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error") or response.text
            raise CalcomAPIError(
                f"Cal.com a répondu {response.status_code}: {message}"
            )

        if payload.get("status") not in {None, "success"}:
            raise CalcomAPIError(f"Cal.com a renvoyé une erreur métier: {payload}")

        return payload
