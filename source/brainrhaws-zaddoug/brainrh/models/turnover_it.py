"""Persistence and API contracts for the Turnover IT JobConnect integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
import uuid

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class TurnoverJobPublicationDB(SQLModel, table=True):
    __tablename__ = "turnover_job_publications"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    tenant_id: str = Field(index=True, nullable=False)
    enterprise_id: str = Field(index=True, nullable=False)
    project_id: str = Field(index=True, nullable=False)
    contract: str = Field(nullable=False)
    remote: str = Field(default="NONE", nullable=False)
    country: str = Field(nullable=False)
    region: Optional[str] = Field(default=None)
    postal_code: Optional[str] = Field(default=None)
    requested_status: str = Field(default="Draft", nullable=False)
    callback_url: str = Field(nullable=False)
    status: str = Field(default="pending", index=True, nullable=False)
    remote_job_id: Optional[str] = Field(default=None)
    remote_public_url: Optional[str] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TurnoverApplicationInboxDB(SQLModel, table=True):
    __tablename__ = "turnover_application_inbox"
    __table_args__ = (
        UniqueConstraint("publication_id", "payload_hash", name="uq_turnover_inbox_publication_hash"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    publication_id: str = Field(
        foreign_key="turnover_job_publications.id", index=True, nullable=False
    )
    tenant_id: str = Field(index=True, nullable=False)
    payload_hash: str = Field(nullable=False)
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    application_id: Optional[int] = Field(default=None, foreign_key="applications.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TurnoverConfigurationUpdate(SQLModel):
    tenant_id: Optional[str] = None
    token: str = Field(min_length=1)


class TurnoverConfigurationResponse(SQLModel):
    connector_id: str = "turnover_it"
    tenant_id: str
    configured: bool
    status: str
    api_base_url: str
    updated_at: Optional[datetime] = None


class TurnoverTenantRequest(SQLModel):
    tenant_id: Optional[str] = None


class TurnoverConnectionTestResponse(SQLModel):
    connected: bool
    status_code: Optional[int] = None
    message: str


class TurnoverPublicationCreate(SQLModel):
    project_id: str = Field(min_length=1)
    contract: Literal[
        "PERMANENT",
        "TEMPORARY",
        "FREELANCE",
        "INTERNSHIP",
        "APPRENTICESHIP",
        "INTERCONTRACT",
    ]
    remote: Literal["NONE", "PARTIAL", "FULL"] = "NONE"
    country: str = Field(min_length=2, max_length=2)
    region: Optional[str] = None
    postal_code: Optional[str] = None
    requested_status: Literal["Draft", "Published"] = "Draft"


class TurnoverPublicationResponse(SQLModel):
    id: str
    tenant_id: str
    project_id: str
    contract: str
    remote: str
    country: str
    region: Optional[str] = None
    postal_code: Optional[str] = None
    requested_status: str
    callback_url: str
    status: str
    remote_public_url: Optional[str] = None
    remote_job_id: Optional[str] = None
    last_error: Optional[str] = None
    application_count: int = 0
    created_at: datetime
    updated_at: datetime


class TurnoverSimulationRequest(SQLModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    phone: Optional[str] = None


class TurnoverIngestionResponse(SQLModel):
    accepted: bool
    duplicate: bool
    application_id: Optional[int] = None
