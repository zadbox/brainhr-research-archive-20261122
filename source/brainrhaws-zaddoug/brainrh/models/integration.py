"""
Modèles SQLModel pour le système d'intégrations BrainRH.

Tables portables SQLite/PostgreSQL.
Aucun secret brut en clair — uniquement metadata/config non sensible
ou référence vers un vault externe (secret_ref).
Les comptes sont isolés par client ou plateforme; l'outbox historique reste
isolée par enterprise_id.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class ConnectorStatus(str, Enum):
    """Statut d'activation d'un compte d'intégration."""
    active = "active"
    inactive = "inactive"
    error = "error"


class EventStatus(str, Enum):
    """Statut d'un événement sortant dans l'outbox."""
    pending = "pending"
    delivered = "delivered"
    failed = "failed"
    retrying = "retrying"


class DeliveryStatus(str, Enum):
    """Statut d'une tentative de livraison."""
    success = "success"
    failure = "failure"
    timeout = "timeout"


class IntegrationScopeKind(str, Enum):
    """Portée d'une instance de connecteur.

    ``enterprise_legacy`` est réservé aux lignes antérieures au passage au
    scope client. L'API n'autorise jamais la création de nouvelles instances
    avec cette portée.
    """

    client = "client"
    platform = "platform"
    enterprise_legacy = "enterprise_legacy"


class ConnectorScopePolicy(str, Enum):
    """Portées que la plateforme autorise pour un connecteur."""

    client_only = "client_only"
    platform_only = "platform_only"
    client_or_platform = "client_or_platform"


# ---------------------------------------------------------------------------
# IntegrationAccount — configuration non-sensible d'un connecteur par tenant
# ---------------------------------------------------------------------------

class IntegrationAccountDB(SQLModel, table=True):
    """Instance configurée d'un connecteur externe.

    - ``connector_id`` : identifiant logique du connecteur (ex: ``zapier``, ``linkedin``).
    - ``config_json``  : JSON de configuration non-sensible (endpoint, options…).
    - ``secret_ref``   : référence externe vers un secret (vault path, env var name…).
    """
    __tablename__ = "integration_accounts"
    __table_args__ = (
        UniqueConstraint(
            "scope_kind",
            "scope_id",
            "connector_id",
            name="uq_intaccount_scope_conn",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    enterprise_id: Optional[str] = Field(default=None, index=True, nullable=True)
    scope_kind: IntegrationScopeKind = Field(index=True, nullable=False)
    scope_id: str = Field(index=True, nullable=False)
    connector_id: str = Field(index=True, nullable=False)
    status: ConnectorStatus = Field(default=ConnectorStatus.inactive)
    config_json: str = Field(default="{}")
    secret_ref: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConnectorScopePolicyDB(SQLModel, table=True):
    """Override de portée administré par la plateforme pour un connecteur."""

    __tablename__ = "connector_scope_policies"

    connector_id: str = Field(primary_key=True)
    scope_policy: ConnectorScopePolicy = Field(
        default=ConnectorScopePolicy.client_only,
        index=True,
    )
    updated_by_user_id: str = Field(index=True, nullable=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# WebhookSubscription — URL de callback sortant par enterprise
# ---------------------------------------------------------------------------

class WebhookSubscriptionDB(SQLModel, table=True):
    """URL de destination pour des catégories d'événements.

    - ``event_types_json`` : JSON list des types d'événements souscrits
      (ex: ``["application.created","candidate.status_changed"]``).
    - ``secret_ref``       : clé HMAC ou référence pour signer les payloads.
    """
    __tablename__ = "webhook_subscriptions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    target_url: str = Field(nullable=False)
    event_types_json: str = Field(default="[]")
    secret_ref: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# OutboundEvent — événement métier en attente de livraison (outbox pattern)
# ---------------------------------------------------------------------------

class OutboundEventDB(SQLModel, table=True):
    """Événement émis par le core BrainRH et stocké dans l'outbox.

    - ``event_type``   : identifiant du type (ex: ``candidate.created``).
    - ``payload_json`` : contenu sérialisé de l'événement.
    - ``retry_count``  : nombre de tentatives déjà effectuées.
    """
    __tablename__ = "outbound_events"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    event_type: str = Field(index=True, nullable=False)
    payload_json: str = Field(default="{}")
    status: EventStatus = Field(default=EventStatus.pending, index=True)
    retry_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# DeliveryAttempt — trace de livraison d'un événement vers une destination
# ---------------------------------------------------------------------------

class DeliveryAttemptDB(SQLModel, table=True):
    """Historise chaque tentative de livraison d'un OutboundEvent.

    - ``status_code`` : code HTTP de la réponse.
    - ``response_body`` : corps de la réponse (tronqué si nécessaire).
    """
    __tablename__ = "delivery_attempts"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    event_id: str = Field(foreign_key="outbound_events.id", index=True, nullable=False)
    subscription_id: Optional[str] = Field(
        default=None, foreign_key="webhook_subscriptions.id", index=True
    )
    status: DeliveryStatus = Field(default=DeliveryStatus.failure)
    status_code: Optional[int] = Field(default=None)
    response_body: Optional[str] = Field(default=None)
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntegrationAccountCreate(SQLModel):
    connector_id: str = Field(min_length=1)
    scope_kind: IntegrationScopeKind = Field(default=IntegrationScopeKind.client)
    tenant_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    secret_ref: Optional[str] = None
    status: ConnectorStatus = Field(default=ConnectorStatus.active)


class IntegrationAccountUpdate(SQLModel):
    config: Optional[Dict[str, Any]] = None
    secret_ref: Optional[str] = None
    status: Optional[ConnectorStatus] = None


class IntegrationAccountResponse(SQLModel):
    id: str
    enterprise_id: Optional[str] = None
    tenant_id: Optional[str] = None
    scope_kind: IntegrationScopeKind
    scope_id: str
    connector_id: str
    status: ConnectorStatus
    config_json: str
    created_at: datetime
    updated_at: datetime


class ConnectorScopePolicyUpdate(SQLModel):
    scope_policy: ConnectorScopePolicy


class ConnectorScopePolicyResponse(SQLModel):
    connector_id: str
    scope_policy: ConnectorScopePolicy
    source: str
    updated_at: Optional[datetime] = None


class OutlookOAuthStartRequest(SQLModel):
    tenant_id: Optional[str] = None


class OutlookOAuthConfigurationResponse(SQLModel):
    connector_id: str = "outlook"
    scope_policy: ConnectorScopePolicy = ConnectorScopePolicy.client_only
    setup_state: str
    oauth_start_available: bool = False


class WebhookSubscriptionCreate(SQLModel):
    target_url: str = Field(min_length=1)
    event_types: List[str] = Field(default_factory=list)
    secret_ref: Optional[str] = None
    is_active: bool = True


class WebhookSubscriptionUpdate(SQLModel):
    target_url: Optional[str] = None
    event_types: Optional[List[str]] = None
    secret_ref: Optional[str] = None
    is_active: Optional[bool] = None


class WebhookSubscriptionResponse(SQLModel):
    id: str
    enterprise_id: str
    target_url: str
    event_types: List[str]
    secret_ref: Optional[str] = None
    is_active: bool
    created_at: datetime


class EmitIntegrationEventRequest(SQLModel):
    event_type: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    process_now: bool = False


class DeliveryResultResponse(SQLModel):
    subscription_id: str
    target_url: str
    status: DeliveryStatus
    status_code: Optional[int] = None
    response_body: Optional[str] = None


class EmitIntegrationEventResponse(SQLModel):
    id: str
    enterprise_id: str
    event_type: str
    status: EventStatus
    retry_count: int
    created_at: datetime
    processed_now: bool = False
    deliveries: List[DeliveryResultResponse] = Field(default_factory=list)


class ProcessPendingEventsRequest(SQLModel):
    limit: int = Field(default=50, ge=1, le=200)


class ProcessPendingEventsResponse(SQLModel):
    enterprise_id: str
    events_processed: int
    total_deliveries: int
    success: int
    failures: int
