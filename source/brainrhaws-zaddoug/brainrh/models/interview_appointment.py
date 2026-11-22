from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
import uuid

from sqlalchemy import CheckConstraint, Index, String, Text
from pydantic import ConfigDict
from sqlmodel import SQLModel, Column, Field, JSON

from brainrh.models.realtime_interview import InterviewLanguage


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InterviewAppointmentStatus(str, Enum):
    scheduled = "scheduled"
    waiting_candidate = "waiting_candidate"
    in_progress = "in_progress"
    paused = "paused"
    wrapping_up = "wrapping_up"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"
    failed = "failed"


class InterviewMode(str, Enum):
    """Qui conduit l'entretien : l'agent IA (Cal Video) ou un recruteur."""

    ai = "ai"
    human = "human"


class HumanMeetingFormat(str, Enum):
    video = "video"
    phone = "phone"
    on_site = "on_site"


class InterviewAppointmentCreateRequest(SQLModel):
    model_config = ConfigDict(populate_by_name=True)

    start_at: datetime
    end_at: Optional[datetime] = None
    duration_minutes: int = Field(default=45, ge=5, le=240)
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    candidate_timezone: str = "Africa/Casablanca"
    language_hint: InterviewLanguage = InterviewLanguage.auto
    scheduler_notes: Optional[str] = None
    booking_fields_responses: dict[str, Any] = Field(default_factory=dict)
    extra_metadata: dict[str, str] = Field(default_factory=dict, alias="metadata")


class HumanInterviewAppointmentCreateRequest(SQLModel):
    """Entretien mené par un recruteur : aucune session IA, aucun enregistrement."""

    start_at: datetime
    end_at: Optional[datetime] = None
    duration_minutes: int = Field(default=45, ge=5, le=240)
    title: Optional[str] = Field(default=None, max_length=120)
    candidate_name: Optional[str] = Field(default=None, max_length=200)
    candidate_email: Optional[str] = Field(default=None, max_length=320)
    candidate_timezone: str = Field(default="Africa/Casablanca", max_length=64)
    interviewer_name: Optional[str] = Field(default=None, max_length=200)
    interviewer_email: Optional[str] = Field(default=None, max_length=320)
    meeting_format: HumanMeetingFormat = HumanMeetingFormat.video
    meeting_url: Optional[str] = Field(default=None, max_length=2048)
    meeting_location: Optional[str] = Field(default=None, max_length=500)
    scheduler_notes: Optional[str] = Field(default=None, max_length=4000)
    send_invitation: bool = True
    invitation_language: Literal["fr", "en"] = "fr"


class InterviewAppointmentOutcomeRequest(SQLModel):
    outcome: Literal["completed", "no_show"]


class InterviewAppointmentCancelRequest(SQLModel):
    reason: Optional[str] = None


class WorkerEventRequest(SQLModel):
    event: str
    occurred_at: Optional[datetime] = None
    details: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class InterviewAppointmentDB(SQLModel, table=True):
    __tablename__ = "interview_appointments"
    __table_args__ = (
        Index("uq_interview_appointments_active_slot", "active_slot", unique=True),
        CheckConstraint(
            "interview_mode IN ('ai', 'human')",
            name="ck_interview_appointments_mode",
        ),
        CheckConstraint(
            "interview_mode = 'human' OR realtime_interview_id IS NOT NULL",
            name="ck_interview_appointments_ai_realtime",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    interview_sheet_id: str = Field(foreign_key="interview_sheets.id", index=True)
    # Renseigné uniquement pour un entretien IA ; un entretien recruteur n'a pas de session IA.
    realtime_interview_id: Optional[str] = Field(default=None, foreign_key="realtime_interviews.id", index=True)
    interview_mode: str = Field(
        default=InterviewMode.ai.value,
        index=True,
        sa_column_kwargs={"server_default": InterviewMode.ai.value},
    )
    # cal.com pour l'IA ; manual pour un lien saisi par le recruteur (ms_teams à venir).
    provider: str = Field(default="cal.com", index=True)
    active_slot: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))

    status: str = Field(default=InterviewAppointmentStatus.scheduled.value, index=True)
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)
    joined_at: Optional[datetime] = Field(default=None)
    candidate_detected_at: Optional[datetime] = Field(default=None)
    candidate_left_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    cancelled_at: Optional[datetime] = Field(default=None)

    candidate_name: str = Field(index=True)
    candidate_email: str = Field(index=True)
    candidate_timezone: str = Field(default="Africa/Casablanca")
    ai_interviewer_name: str = Field(default="BrainRH AI Interviewer")
    # Intitulé libre d'un entretien recruteur (« Entretien technique », « Entretien client »…).
    title: Optional[str] = Field(default=None)
    interviewer_name: Optional[str] = Field(default=None)
    interviewer_email: Optional[str] = Field(default=None)
    meeting_format: Optional[str] = Field(default=None)
    meeting_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    meeting_location: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    calcom_booking_uid: Optional[str] = Field(default=None, index=True)
    calcom_booking_id: Optional[str] = Field(default=None, index=True)
    calcom_event_type_id: Optional[int] = Field(default=None, index=True)
    calcom_event_type_slug: Optional[str] = Field(default=None, index=True)
    calcom_video_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    booking_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    booking_references: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    conferencing_sessions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    recordings: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transcripts: list[Any] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    worker_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    artifact_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
