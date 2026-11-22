from datetime import datetime, timezone
import uuid
from typing import Optional, List
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint
from enum import Enum

class UserRole(str, Enum):
    platform_admin = "platform_admin"
    client_admin = "client_admin"
    enterprise_admin = "enterprise_admin"
    project_manager = "project_manager"
    recruiter = "recruiter"
    viewer = "viewer"


class AccessScopeKind(str, Enum):
    client = "client"
    enterprise = "enterprise"
    project = "project"


class InvitationScopeKind(str, Enum):
    global_scope = "global"
    client = "client"
    enterprise = "enterprise"


class InvitationStatus(str, Enum):
    pending_delivery = "pending_delivery"
    sent = "sent"
    delivery_failed = "delivery_failed"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"

class TenantDB(SQLModel, table=True):
    __tablename__ = "tenants"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    trial_duration_days: Optional[int] = Field(default=None)
    trial_started_at: Optional[datetime] = Field(default=None)
    trial_expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserDB(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    # Null pendant l'invitation et pour un compte actif Google-only. Aucun mot
    # de passe temporaire (clair ou haché) n'est généré pour un nouvel invité.
    hashed_password: Optional[str] = Field(default=None)
    role: UserRole = Field(default=UserRole.viewer)
    tenant_id: Optional[str] = Field(default=None, foreign_key="tenants.id")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MembershipDB(SQLModel, table=True):
    """Relation entre un utilisateur authentifié et une entreprise cliente.

    Permet au futur RBAC de résoudre le contexte enterprise sans variable globale.
    Compatible avec le login existant : aucune route ne le rend obligatoire pour l'instant.
    """
    __tablename__ = "memberships"
    # Aligné avec la migration 1ef8b8e5bc29 (uq_memberships_user_enterprise).
    # Sans ce __table_args__, alembic autogenerate comparerait la DB avec
    # SQLModel.metadata et produirait un remove_constraint indésirable
    # lors de la prochaine révision.
    __table_args__ = (
        UniqueConstraint("user_id", "enterprise_id", name="uq_memberships_user_enterprise"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    enterprise_id: str = Field(index=True)
    role: UserRole = Field(default=UserRole.viewer)
    scopes_json: str = Field(default="[]")   # JSON list de scopes fins pour usage futur
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccessGrantDB(SQLModel, table=True):
    __tablename__ = "access_grants"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scope_kind",
            "scope_id",
            "role",
            name="uq_access_grants_user_scope_role",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    scope_kind: AccessScopeKind = Field(index=True)
    scope_id: str = Field(index=True)
    role: UserRole = Field(default=UserRole.viewer)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserInvitationDB(SQLModel, table=True):
    __tablename__ = "user_invitations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scope_kind",
            "scope_id",
            name="uq_user_invitations_user_scope",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    email: str = Field(index=True)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    scope_kind: InvitationScopeKind = Field(index=True)
    scope_id: str = Field(index=True)
    role: UserRole
    token_digest: str = Field(unique=True, index=True)
    status: InvitationStatus = Field(default=InvitationStatus.pending_delivery, index=True)
    language: str = Field(default="en")
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    membership_id: Optional[str] = Field(default=None, foreign_key="memberships.id")
    access_grant_id: Optional[str] = Field(default=None, foreign_key="access_grants.id")
    user_was_existing: bool = Field(default=False)
    send_attempts: int = Field(default=0)
    last_attempt_at: Optional[datetime] = Field(default=None)
    last_sent_at: Optional[datetime] = Field(default=None)
    expires_at: datetime
    accepted_at: Optional[datetime] = Field(default=None)
    failed_at: Optional[datetime] = Field(default=None)
    failure_code: Optional[str] = Field(default=None)
    provider_message_id: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Pydantic schemas for API representation
class UserLogin(SQLModel):
    email: str
    password: str

class UserResponse(SQLModel):
    id: str
    email: str
    role: UserRole
    tenant_id: Optional[str]
    is_active: bool
    can_manage_users: bool = False
    display_name: Optional[str] = None
    google_linked: bool = False
    google_auth_enabled: bool = False
    trial_tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    trial_duration_days: Optional[int] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    trial_status: Optional[str] = None


class GoogleIdentityDB(SQLModel, table=True):
    __tablename__ = "google_identities"
    user_id: str = Field(primary_key=True, foreign_key="users.id")
    subject: str = Field(unique=True, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GoogleAuthAttemptDB(SQLModel, table=True):
    """Short-lived, browser-bound OAuth attempts; never stores Google tokens."""
    __tablename__ = "google_auth_attempts"
    state_digest: str = Field(primary_key=True, max_length=64)
    browser_digest: str = Field(max_length=64)
    nonce_digest: str = Field(max_length=64)
    code_verifier: str = Field(max_length=128)
    purpose: str = Field(max_length=16)
    user_id: Optional[str] = Field(default=None, foreign_key="users.id")
    token_version: Optional[int] = None
    invitation_digest: Optional[str] = Field(default=None, max_length=64)
    expires_at: datetime = Field(index=True)
