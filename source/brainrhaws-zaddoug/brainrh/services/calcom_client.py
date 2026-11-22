from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests


class CalcomConfigurationError(RuntimeError):
    pass


class CalcomAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class CalcomSettings:
    base_url: str
    api_key: str
    api_version: str
    event_type_api_version: str
    artifact_api_version: str
    transcript_api_version: str
    allow_conflicts: bool
    allow_booking_out_of_bounds: bool
    ensure_cal_video_recording: bool
    event_type_id: Optional[int]
    event_type_slug: str
    username: str
    team_slug: str
    organization_slug: str
    webhook_secret: str


def get_calcom_settings() -> CalcomSettings:
    event_type_id_raw = os.getenv("CALCOM_EVENT_TYPE_ID", "").strip()
    event_type_id = int(event_type_id_raw) if event_type_id_raw else None
    api_version = os.getenv("CALCOM_API_VERSION", "2026-02-25").strip()

    return CalcomSettings(
        base_url=os.getenv("CALCOM_BASE_URL", "https://api.cal.com/v2").strip().rstrip("/"),
        api_key=os.getenv("CALCOM_API_KEY", "").strip(),
        api_version=api_version,
        event_type_api_version=os.getenv("CALCOM_EVENT_TYPE_API_VERSION", "2024-06-14").strip(),
        artifact_api_version=os.getenv("CALCOM_ARTIFACT_API_VERSION", api_version).strip(),
        transcript_api_version=os.getenv("CALCOM_TRANSCRIPT_API_VERSION", api_version).strip(),
        allow_conflicts=_env_flag("CALCOM_ALLOW_CONFLICTS", default=True),
        allow_booking_out_of_bounds=_env_flag("CALCOM_ALLOW_BOOKING_OUT_OF_BOUNDS", default=True),
        ensure_cal_video_recording=_env_flag("CALCOM_ENSURE_CAL_VIDEO_RECORDING", default=True),
        event_type_id=event_type_id,
        event_type_slug=os.getenv("CALCOM_EVENT_TYPE_SLUG", "").strip(),
        username=os.getenv("CALCOM_USERNAME", "").strip(),
        team_slug=os.getenv("CALCOM_TEAM_SLUG", "").strip(),
        organization_slug=os.getenv("CALCOM_ORGANIZATION_SLUG", "").strip(),
        webhook_secret=os.getenv("CALCOM_WEBHOOK_SECRET", "").strip(),
    )


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CalcomClient:
    def __init__(self, settings: CalcomSettings | None = None):
        self.settings = settings or get_calcom_settings()

    def resolve_event_reference(self) -> dict[str, Any]:
        if self.settings.event_type_id is not None:
            return {"eventTypeId": self.settings.event_type_id}

        if self.settings.event_type_slug and (self.settings.username or self.settings.team_slug):
            payload: dict[str, Any] = {"eventTypeSlug": self.settings.event_type_slug}
            if self.settings.username:
                payload["username"] = self.settings.username
            if self.settings.team_slug:
                payload["teamSlug"] = self.settings.team_slug
            if self.settings.organization_slug:
                payload["organizationSlug"] = self.settings.organization_slug
            return payload

        raise CalcomConfigurationError(
            "Event type Cal.com non configuré. Fournir CALCOM_EVENT_TYPE_ID "
            "ou CALCOM_EVENT_TYPE_SLUG + CALCOM_USERNAME/CALCOM_TEAM_SLUG."
        )

    def ensure_configured(self) -> None:
        if not self.settings.api_key:
            raise CalcomConfigurationError("CALCOM_API_KEY manquante")
        self.resolve_event_reference()

    def ensure_api_key_configured(self) -> None:
        if not self.settings.api_key:
            raise CalcomConfigurationError("CALCOM_API_KEY manquante")

    def create_booking(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/bookings", json=payload)

    def ensure_cal_video_recording(self, event_reference: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.ensure_cal_video_recording:
            return {"requested": False, "reason": "disabled"}

        event_type_id = event_reference.get("eventTypeId") or self.settings.event_type_id
        if event_type_id is None:
            event_type_id = self._resolve_event_type_id_for_recording(event_reference)
        if event_type_id is None:
            return {
                "requested": False,
                "reason": "Cal.com event type id could not be resolved for recording setup",
            }

        payload = {
            "calVideoSettings": {
                "disableRecordingForOrganizer": False,
                "disableRecordingForGuests": True,
                "enableAutomaticRecordingForOrganizer": True,
                "enableAutomaticTranscription": True,
                "disableTranscriptionForGuests": True,
                "disableTranscriptionForOrganizer": False,
                "sendTranscriptionEmails": False,
            }
        }
        response = self._request(
            "PATCH",
            f"/event-types/{event_type_id}",
            json=payload,
            api_version=self.settings.event_type_api_version,
        )
        return {
            "requested": True,
            "eventTypeId": event_type_id,
            "calVideoSettings": payload["calVideoSettings"],
            "response": response,
        }

    def list_event_types(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "/event-types",
            api_version=self.settings.event_type_api_version,
            require_event_reference=False,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def _resolve_event_type_id_for_recording(self, event_reference: dict[str, Any]) -> int | None:
        slug = str(event_reference.get("eventTypeSlug") or self.settings.event_type_slug or "").strip()
        if not slug:
            return None

        username = str(event_reference.get("username") or self.settings.username or "").strip()
        team_slug = str(event_reference.get("teamSlug") or self.settings.team_slug or "").strip()
        organization_slug = str(event_reference.get("organizationSlug") or self.settings.organization_slug or "").strip()

        for event_type in self.list_event_types():
            if event_type.get("slug") != slug:
                continue
            booking_url = str(event_type.get("bookingUrl") or "")
            if username and f"/{username}/{slug}" not in booking_url:
                continue
            if team_slug and team_slug not in booking_url:
                continue
            if organization_slug and organization_slug not in booking_url:
                continue
            event_type_id = event_type.get("id")
            if isinstance(event_type_id, int):
                return event_type_id
            if isinstance(event_type_id, str) and event_type_id.isdigit():
                return int(event_type_id)

        return None

    def get_booking(self, booking_uid: str) -> dict[str, Any]:
        return self._request("GET", f"/bookings/{booking_uid}")

    def cancel_booking(
        self,
        booking_uid: str,
        *,
        cancellation_reason: str | None = None,
        cancel_subsequent_bookings: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "cancellationReason": cancellation_reason or "Cancelled from BrainRH",
        }
        if cancel_subsequent_bookings:
            payload["cancelSubsequentBookings"] = True
        return self._request("POST", f"/bookings/{booking_uid}/cancel", json=payload)

    def get_booking_references(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/references",
            api_version=self.settings.artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_conferencing_sessions(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/conferencing-sessions",
            api_version=self.settings.artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_recordings(self, booking_uid: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/recordings",
            api_version=self.settings.artifact_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def get_transcripts(self, booking_uid: str) -> list[Any]:
        response = self._request(
            "GET",
            f"/bookings/{booking_uid}/transcripts",
            api_version=self.settings.transcript_api_version,
        )
        data = response.get("data")
        return data if isinstance(data, list) else []

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        api_version: str | None = None,
        require_event_reference: bool = True,
    ) -> dict[str, Any]:
        if require_event_reference:
            self.ensure_configured()
        else:
            self.ensure_api_key_configured()
        url = f"{self.settings.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "cal-api-version": api_version or self.settings.api_version,
            "Content-Type": "application/json",
        }

        try:
            response = requests.request(method, url, headers=headers, json=json, timeout=30)
        except requests.RequestException as exc:
            raise CalcomAPIError(f"Erreur réseau Cal.com: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CalcomAPIError(f"Réponse Cal.com non JSON ({response.status_code})") from exc

        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error") or response.text
            raise CalcomAPIError(f"Cal.com a répondu {response.status_code}: {message}")

        if payload.get("status") not in {None, "success"}:
            raise CalcomAPIError(f"Cal.com a renvoyé une erreur métier: {payload}")

        return payload


def verify_calcom_webhook_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    if not secret:
        return False
    if not signature:
        return False

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, digest) or hmac.compare_digest(signature, f"sha256={digest}")


def extract_calcom_video_url(booking: dict[str, Any]) -> str | None:
    video_call_data = booking.get("videoCallData")
    if isinstance(video_call_data, dict) and isinstance(video_call_data.get("url"), str):
        return video_call_data["url"]

    metadata = booking.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("videoCallUrl"), str):
        return metadata["videoCallUrl"]

    for key in ("meetingUrl", "location"):
        value = booking.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, dict):
            nested = value.get("link") or value.get("url")
            if isinstance(nested, str) and nested.startswith(("http://", "https://")):
                return nested

    return None
