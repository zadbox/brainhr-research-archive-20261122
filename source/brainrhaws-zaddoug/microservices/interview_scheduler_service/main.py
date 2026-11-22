from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .calcom_client import CalcomAPIError, CalcomClient
from .config import Settings, get_settings
from .store import SchedulerStore


def as_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class GuestInput(BaseModel):
    email: str
    name: Optional[str] = None
    timeZone: Optional[str] = None


class AttendeeInput(BaseModel):
    name: str
    email: str
    timeZone: str
    language: str = "fr"
    phoneNumber: Optional[str] = None


class CreateBookingRequest(BaseModel):
    start: datetime
    attendee: AttendeeInput
    guests: list[str] = Field(default_factory=list)
    lengthInMinutes: Optional[int] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    bookingFieldsResponses: dict[str, Any] = Field(default_factory=dict)


class AddGuestsRequest(BaseModel):
    guests: list[GuestInput] = Field(default_factory=list)


class CancelBookingRequest(BaseModel):
    cancellationReason: str = "Cancelled from BrainRH"
    cancelSubsequentBookings: bool = False


class BookingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    booking: dict[str, Any]
    localRecord: Optional[dict[str, Any]] = None


def build_store(settings: Settings) -> SchedulerStore:
    return SchedulerStore(settings.database_path)


def get_store(settings: Settings = Depends(get_settings)) -> SchedulerStore:
    return build_store(settings)


def get_calcom_client(settings: Settings = Depends(get_settings)) -> CalcomClient:
    if not settings.calcom_api_key:
        raise HTTPException(status_code=503, detail="CALCOM_API_KEY manquante")
    return CalcomClient(settings)


def resolve_event_reference(settings: Settings) -> dict[str, Any]:
    if settings.calcom_event_type_id is not None:
        return {"eventTypeId": settings.calcom_event_type_id}

    if settings.calcom_event_type_slug and (settings.calcom_username or settings.calcom_team_slug):
        payload: dict[str, Any] = {"eventTypeSlug": settings.calcom_event_type_slug}
        if settings.calcom_username:
            payload["username"] = settings.calcom_username
        if settings.calcom_team_slug:
            payload["teamSlug"] = settings.calcom_team_slug
        if settings.calcom_organization_slug:
            payload["organizationSlug"] = settings.calcom_organization_slug
        return payload

    raise HTTPException(
        status_code=503,
        detail=(
            "Event type Cal.com non configuré. Fournir CALCOM_EVENT_TYPE_ID "
            "ou CALCOM_EVENT_TYPE_SLUG + CALCOM_USERNAME/CALCOM_TEAM_SLUG."
        ),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    build_store(get_settings())
    yield


app = FastAPI(
    title="BrainRH Interview Scheduler Service",
    version="0.1.0",
    description="Microservice autonome local pour réserver et inviter des entretiens via Cal.com.",
    lifespan=lifespan,
)


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "provider": "cal.com",
        "calcomConfigured": settings.calcom_configured,
        "eventTypeConfigured": bool(
            settings.calcom_event_type_id
            or settings.calcom_event_type_slug
        ),
        "organizerEmail": settings.organizer_email or None,
        "defaultTimezone": settings.default_timezone,
        "defaultDurationMinutes": settings.default_duration_minutes,
    }


@app.get("/v1/provider/status")
def provider_status(
    settings: Settings = Depends(get_settings),
    store: SchedulerStore = Depends(get_store),
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    del store  # dependency warms up storage
    try:
        calendars = client.get_calendars()
        conferencing = client.get_conferencing_apps()
        return {
            "provider": "cal.com",
            "configured": settings.calcom_configured,
            "calendars": calendars.get("data", {}),
            "conferencing": conferencing.get("data", []),
        }
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@app.post("/v1/bookings", response_model=BookingEnvelope, status_code=201)
def create_booking(
    payload: CreateBookingRequest,
    settings: Settings = Depends(get_settings),
    store: SchedulerStore = Depends(get_store),
    client: CalcomClient = Depends(get_calcom_client),
) -> BookingEnvelope:
    event_reference = resolve_event_reference(settings)
    booking_payload = {
        "start": as_utc_iso(payload.start),
        "attendee": payload.attendee.model_dump(exclude_none=True),
        "guests": [str(email) for email in payload.guests],
        "bookingFieldsResponses": payload.bookingFieldsResponses,
        "metadata": {
            **payload.metadata,
            "source": "brainrh-interview-scheduler",
        },
        **event_reference,
    }
    if payload.lengthInMinutes is not None:
        booking_payload["lengthInMinutes"] = payload.lengthInMinutes

    try:
        response = client.create_booking(booking_payload)
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()

    booking = response.get("data", {})
    booking_uid = booking.get("uid")
    if not booking_uid:
        raise HTTPException(status_code=502, detail="Réponse Cal.com invalide: booking uid manquant")

    store.upsert_booking(
        booking_uid=booking_uid,
        provider="cal.com",
        candidate_name=payload.attendee.name,
        candidate_email=str(payload.attendee.email),
        start_at=booking.get("start", booking_payload["start"]),
        status=str(booking.get("status", "accepted")),
        payload=booking,
    )
    local_record = store.get_booking(booking_uid)
    return BookingEnvelope(provider="cal.com", booking=booking, localRecord=local_record)


@app.get("/v1/bookings/{booking_uid}", response_model=BookingEnvelope)
def get_booking(
    booking_uid: str,
    store: SchedulerStore = Depends(get_store),
    client: CalcomClient = Depends(get_calcom_client),
) -> BookingEnvelope:
    try:
        response = client.get_booking(booking_uid)
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()

    booking = response.get("data", {})
    local_record = store.get_booking(booking_uid)
    return BookingEnvelope(provider="cal.com", booking=booking, localRecord=local_record)


@app.post("/v1/bookings/{booking_uid}/guests", response_model=BookingEnvelope)
def add_guests(
    booking_uid: str,
    payload: AddGuestsRequest,
    store: SchedulerStore = Depends(get_store),
    client: CalcomClient = Depends(get_calcom_client),
) -> BookingEnvelope:
    calcom_payload = {
        "guests": [guest.model_dump(exclude_none=True) for guest in payload.guests]
    }
    try:
        response = client.add_guests(booking_uid, calcom_payload)
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()

    booking = response.get("data", {})
    existing = store.get_booking(booking_uid)
    store.upsert_booking(
        booking_uid=booking_uid,
        provider="cal.com",
        candidate_name=(existing or {}).get("candidate_name", ""),
        candidate_email=(existing or {}).get("candidate_email", ""),
        start_at=booking.get("start", (existing or {}).get("start_at", "")),
        status=str(booking.get("status", (existing or {}).get("status", "accepted"))),
        payload=booking,
    )
    local_record = store.get_booking(booking_uid)
    return BookingEnvelope(provider="cal.com", booking=booking, localRecord=local_record)


@app.post("/v1/bookings/{booking_uid}/cancel", response_model=BookingEnvelope)
def cancel_booking(
    booking_uid: str,
    payload: CancelBookingRequest,
    store: SchedulerStore = Depends(get_store),
    client: CalcomClient = Depends(get_calcom_client),
) -> BookingEnvelope:
    try:
        response = client.cancel_booking(booking_uid, payload.model_dump())
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()

    booking = response.get("data", {})
    existing = store.get_booking(booking_uid)
    store.upsert_booking(
        booking_uid=booking_uid,
        provider="cal.com",
        candidate_name=(existing or {}).get("candidate_name", ""),
        candidate_email=(existing or {}).get("candidate_email", ""),
        start_at=booking.get("start", (existing or {}).get("start_at", "")),
        status="cancelled",
        payload=booking,
    )
    local_record = store.get_booking(booking_uid)
    return BookingEnvelope(provider="cal.com", booking=booking, localRecord=local_record)


@app.get("/v1/bookings/{booking_uid}/calendar-links")
def get_calendar_links(
    booking_uid: str,
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    try:
        links = client.get_calendar_links(booking_uid)
        return {"provider": "cal.com", "bookingUid": booking_uid, "links": links}
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@app.get("/v1/bookings/{booking_uid}/references")
def get_booking_references(
    booking_uid: str,
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    try:
        references = client.get_booking_references(booking_uid)
        return {"provider": "cal.com", "bookingUid": booking_uid, "references": references}
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@app.get("/v1/bookings/{booking_uid}/conferencing-sessions")
def get_conferencing_sessions(
    booking_uid: str,
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    try:
        sessions = client.get_conferencing_sessions(booking_uid)
        return {"provider": "cal.com", "bookingUid": booking_uid, "sessions": sessions}
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@app.get("/v1/bookings/{booking_uid}/recordings")
def get_recordings(
    booking_uid: str,
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    try:
        recordings = client.get_recordings(booking_uid)
        return {"provider": "cal.com", "bookingUid": booking_uid, "recordings": recordings}
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@app.get("/v1/bookings/{booking_uid}/transcripts")
def get_transcripts(
    booking_uid: str,
    client: CalcomClient = Depends(get_calcom_client),
) -> dict[str, Any]:
    try:
        transcripts = client.get_transcripts(booking_uid)
        return {"provider": "cal.com", "bookingUid": booking_uid, "transcripts": transcripts}
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()
