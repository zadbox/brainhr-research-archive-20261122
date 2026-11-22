from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, Numeric, Text, UniqueConstraint, false
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CrustdataCriteriaDB(SQLModel, table=True):
    __tablename__ = "crustdata_criteria"
    __table_args__ = (
        UniqueConstraint("tenant_id", "enterprise_id", "project_id", name="uq_crustdata_criteria_scope"),
        Index("ix_crustdata_criteria_tenant", "tenant_id", "enterprise_id", "project_id"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str
    enterprise_id: str
    project_id: str = Field(foreign_key="projects.id")
    offer_derived_json: str = Field(sa_column=Column(Text, nullable=False))
    current_json: str = Field(sa_column=Column(Text, nullable=False))
    stale: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=false()))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CrustdataSearchSessionDB(SQLModel, table=True):
    __tablename__ = "crustdata_search_sessions"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_crustdata_search_session_operation"),
        Index("ix_crustdata_search_session_scope", "tenant_id", "enterprise_id", "project_id"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str
    enterprise_id: str
    project_id: str = Field(foreign_key="projects.id")
    user_id: str
    operation_id: str
    compiled_query_json: str = Field(sa_column=Column(Text, nullable=False))
    next_cursor: Optional[str] = Field(default=None)
    requested_count: int
    returned_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    total_count: Optional[int] = None
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CrustdataSearchResultDB(SQLModel, table=True):
    __tablename__ = "crustdata_search_results"
    __table_args__ = (
        UniqueConstraint("search_session_id", "provider_person_id", name="uq_crustdata_search_result_person"),
        Index("ix_crustdata_search_result_scope", "tenant_id", "enterprise_id", "project_id"),
        Index("ix_crustdata_search_result_url", "normalized_profile_url"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    search_session_id: str = Field(foreign_key="crustdata_search_sessions.id")
    tenant_id: str
    enterprise_id: str
    project_id: str
    provider_person_id: str
    normalized_profile_url: Optional[str] = None
    lightweight_json: str = Field(sa_column=Column(Text, nullable=False))
    provider_updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CrustdataWalletDB(SQLModel, table=True):
    __tablename__ = "crustdata_wallets"
    __table_args__ = (UniqueConstraint("scope_kind", "scope_id", name="uq_crustdata_wallet_scope"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    scope_kind: str
    scope_id: str
    balance: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(20, 6), nullable=False))
    reserved: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(20, 6), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    provider_last_synced_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class CrustdataCreditOperationDB(SQLModel, table=True):
    __tablename__ = "crustdata_credit_operations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_crustdata_credit_operation_operation"),
        Index("ix_crustdata_credit_operation_tenant", "tenant_id", "created_at"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    operation_id: str
    request_fingerprint: str
    tenant_id: str
    user_id: str
    project_id: Optional[str] = None
    operation_type: str
    requested_count: int
    returned_or_matched_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    estimated_credits: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    reported_credits_exact: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(20, 6)))
    settled_credits: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(20, 6)))
    provider_balance_before_or_last_known: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(20, 6)))
    provider_balance_after_or_next_sync: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(20, 6)))
    status: str = "reserved"
    error_code: Optional[str] = Field(default=None)
    response_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class CrustdataIdentityDB(SQLModel, table=True):
    __tablename__ = "crustdata_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_person_id", name="uq_crustdata_identity_person"),
        UniqueConstraint("tenant_id", "normalized_profile_url", name="uq_crustdata_identity_url"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str
    provider_person_id: str
    normalized_profile_url: str
    raw_snapshot_path: Optional[str] = Field(default=None)
    source_last_updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CrustdataIdentityEnterpriseDB(SQLModel, table=True):
    __tablename__ = "crustdata_identity_enterprises"
    __table_args__ = (
        UniqueConstraint("identity_id", "enterprise_id", name="uq_crustdata_identity_enterprise"),
        Index("ix_crustdata_identity_enterprise_talent", "enterprise_id", "talent_profile_id"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    identity_id: str = Field(foreign_key="crustdata_identities.id")
    enterprise_id: str
    talent_profile_id: int = Field(foreign_key="talent_profiles.id")
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
