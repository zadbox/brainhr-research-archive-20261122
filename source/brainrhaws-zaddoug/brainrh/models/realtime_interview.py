from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlmodel import SQLModel, Column, Field, JSON


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InterviewLanguage(str, Enum):
    fr = "fr"
    en = "en"
    ar = "ar"
    auto = "auto"


class InterviewStatus(str, Enum):
    ready = "ready"
    in_progress = "in_progress"
    completed = "completed"


class RealtimeInterviewPreparationState(str, Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class InterviewContextMode(str, Enum):
    manual = "manual"
    registry = "registry"
    canonical = "canonical"


class NotableSignalType(str, Enum):
    strength = "strength"
    risk = "risk"
    clarification = "clarification"
    followup = "followup"


class TranscriptSpeaker(str, Enum):
    candidate = "candidate"
    assistant = "assistant"


class InterviewStage(SQLModel):
    id: str
    label: str
    objective: str
    mustCover: list[str] = Field(default_factory=list)
    sampleQuestions: list[str] = Field(default_factory=list)
    followupTriggers: list[str] = Field(default_factory=list)


class ScoringRubricItem(SQLModel):
    category: str
    criteria: list[str] = Field(default_factory=list)


class RealtimeInterviewRegistryContext(SQLModel):
    # Kept inside plan_data to avoid a live schema migration on the MVP table
    # while still persisting canonical linkage in RealtimeInterviewDB.
    projectId: Optional[str] = None
    candidateId: Optional[str] = None
    matchingId: Optional[str] = None
    interviewSheetId: Optional[str] = None
    applicationId: Optional[int] = None
    talentProfileId: Optional[int] = None
    resumeVersionId: Optional[int] = None
    source: Optional[str] = None
    candidateEmail: Optional[str] = None
    candidatePhone: Optional[str] = None


class InterviewPlan(SQLModel):
    languageHint: InterviewLanguage = Field(default=InterviewLanguage.auto)
    roleTitle: str
    candidateName: str
    jobSummary: str
    candidateSummary: str
    stages: list[InterviewStage] = Field(default_factory=list)
    scoringRubric: list[ScoringRubricItem] = Field(default_factory=list)
    registryContext: Optional[RealtimeInterviewRegistryContext] = None


class NotableSignal(SQLModel):
    type: NotableSignalType
    text: str
    createdAt: str


class TemporaryBranch(SQLModel):
    topic: str
    reason: str
    remainingQuestions: int = 2


class TranscriptTurn(SQLModel):
    speaker: TranscriptSpeaker
    text: str
    ts: str


class InterviewRuntimeState(SQLModel):
    interviewId: str
    currentStageId: str
    coveredItems: list[str] = Field(default_factory=list)
    notableSignals: list[NotableSignal] = Field(default_factory=list)
    temporaryBranch: Optional[TemporaryBranch] = None
    transcriptTurns: list[TranscriptTurn] = Field(default_factory=list)


class RealtimeInterviewSetupRequest(SQLModel):
    candidateName: Optional[str] = None
    cvText: Optional[str] = None
    jobDescriptionText: Optional[str] = None
    mode: Optional[InterviewContextMode] = None
    projectId: Optional[str] = None
    jobId: Optional[str] = None
    candidateId: Optional[str] = None
    matchingId: Optional[str] = None
    interviewSheetId: Optional[str] = None
    aiPlanInstructions: Optional[str] = Field(default=None, max_length=4000)
    languageHint: InterviewLanguage = Field(default=InterviewLanguage.auto)


class UpdateRealtimeInterviewPlanRequest(SQLModel):
    plan: InterviewPlan


class RealtimeToolCallRequest(SQLModel):
    callId: Optional[str] = None
    name: str
    arguments: Any = None


class RealtimeToolCallsPayload(SQLModel):
    appointmentId: Optional[str] = None
    calls: list[RealtimeToolCallRequest] = Field(default_factory=list)


class RealtimeInterviewDB(SQLModel, table=True):
    __tablename__ = "realtime_interviews"
    __table_args__ = (
        Index("uq_realtime_interviews_active_sheet_slot", "active_sheet_slot", unique=True),
        Index("ix_realtime_interviews_interview_sheet_id", "interview_sheet_id"),
        Index("ix_realtime_interviews_project_id", "project_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    owner_user_id: str = Field(index=True)
    interview_sheet_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(
                "interview_sheets.id",
                name="fk_realtime_interviews_interview_sheet_id_interview_sheets",
            ),
            nullable=True,
        ),
    )
    project_id: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    active_sheet_slot: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    preparation_state: str = Field(default=RealtimeInterviewPreparationState.ready.value)
    preparation_lease_token: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    preparation_lease_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    candidate_name: str = Field(index=True)
    language_hint: str = Field(default=InterviewLanguage.auto.value, index=True)
    status: str = Field(default=InterviewStatus.ready.value, index=True)
    cv_text: str = Field(sa_column=Column(Text, nullable=False))
    job_description_text: str = Field(sa_column=Column(Text, nullable=False))
    plan_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    runtime_state: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    summary_data: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = Field(default=None)
