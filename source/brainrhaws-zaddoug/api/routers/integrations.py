"""API REST pour le système d'intégrations (INTEG-005).

Routes :
- GET /api/v1/integrations/connectors  — liste tous les connecteurs du registry
- PATCH /api/v1/integrations/connectors/{id}/scope-policy — règle la portée autorisée
- GET /api/v1/integrations/accounts    — liste les comptes configurés
- POST /api/v1/integrations/accounts   — crée un compte de connecteur
- GET /api/v1/integrations/events      — liste les événements outbox

RBAC :
- platform_admin : règle les politiques de portée et peut gérer toute instance.
- client_admin : gère les instances de son client.
- les routes historiques d'événements restent scoped par enterprise.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from api.dependencies import get_current_user, get_tenant_context, require_tenant_roles
from brainrh.integrations.account_application import (
    IntegrationAccountAppError,
    IntegrationAccountApplication,
)
from brainrh.database import get_session_dependency
from brainrh.models.auth import AccessScopeKind, UserDB, UserRole
from brainrh.models.enterprise import EnterpriseDB
from brainrh.models.integration import (
    ConnectorStatus,
    ConnectorScopePolicy,
    ConnectorScopePolicyDB,
    ConnectorScopePolicyResponse,
    ConnectorScopePolicyUpdate,
    DeliveryResultResponse,
    EmitIntegrationEventRequest,
    EmitIntegrationEventResponse,
    IntegrationAccountCreate,
    IntegrationAccountDB,
    IntegrationAccountResponse,
    IntegrationScopeKind,
    OutboundEventDB,
    OutlookOAuthConfigurationResponse,
    OutlookOAuthStartRequest,
    ProcessPendingEventsRequest,
    ProcessPendingEventsResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)
from brainrh.models.project import ProjectDB
from brainrh.models.turnover_it import (
    TurnoverConfigurationResponse,
    TurnoverConfigurationUpdate,
    TurnoverConnectionTestResponse,
    TurnoverIngestionResponse,
    TurnoverJobPublicationDB,
    TurnoverPublicationCreate,
    TurnoverPublicationResponse,
    TurnoverSimulationRequest,
    TurnoverTenantRequest,
)
from brainrh.services.auth_service import (
    TenantContext,
    list_access_grants_for_user,
    require_tenant_trial_access,
    user_roles_satisfy,
)
from brainrh.services.enterprise_service import EnterpriseService
from brainrh.services.http_webhook_sender import (
    UnsafeWebhookTargetError,
    httpx_sender,
    validate_webhook_target_url,
)
from brainrh.services.integration_account_service import SqlIntegrationAccountStore
from brainrh.services.integration_event_service import IntegrationEventService
from brainrh.services.turnover_it_service import (
    TURNOVER_API_BASE_URL,
    TurnoverITError,
    configure_turnover_account,
    create_publication as create_turnover_publication_record,
    get_turnover_account,
    ingest_turnover_application,
    publication_response,
    resolve_turnover_token,
    simulate_payload,
    test_turnover_connection,
    turnover_offer_content,
)
from brainrh.settings import get_public_api_base_url
from brainrh.services.webhook_delivery_service import DeliveryResult, WebhookDeliveryService

# Force bootstrap du registry
import brainrh.integrations.providers  # noqa: F401
from brainrh.integrations.registry import registry
from brainrh.integrations.providers.outlook import (
    OutlookSetupState,
    get_outlook_oauth_configuration,
)

router = APIRouter(tags=["Intégrations"])


def _build_accounts_app(session: Session) -> IntegrationAccountApplication:
    return IntegrationAccountApplication(SqlIntegrationAccountStore(session))


def _require_integration_admin(tenant: TenantContext) -> TenantContext:
    return require_tenant_roles(tenant, {UserRole.enterprise_admin})


def _platform_context(user: UserDB, tenant_id: Optional[str] = None) -> TenantContext:
    return TenantContext(
        user_id=str(user.id),
        tenant_id=tenant_id,
        role=UserRole.platform_admin,
        roles=[UserRole.platform_admin],
        scopes=["*"],
    )


def _resolve_client_admin_context(user: UserDB, tenant_id: Optional[str]) -> TenantContext:
    resolved_tenant_id = str(tenant_id or user.tenant_id or "").strip()
    if user.role == UserRole.platform_admin:
        return _platform_context(user, resolved_tenant_id or None)
    if not resolved_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id requis pour gérer les intégrations client.",
        )
    require_tenant_trial_access(resolved_tenant_id)

    has_client_admin_grant = any(
        grant.scope_kind == AccessScopeKind.client
        and str(grant.scope_id) == resolved_tenant_id
        and user_roles_satisfy([grant.role], {UserRole.client_admin})
        for grant in list_access_grants_for_user(user)
    )
    legacy_user_scope = (
        user.role == UserRole.client_admin
        and str(user.tenant_id or "") == resolved_tenant_id
    )
    if not (has_client_admin_grant or legacy_user_scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Aucun accès client_admin actif pour le client {resolved_tenant_id}.",
        )

    return TenantContext(
        user_id=str(user.id),
        tenant_id=resolved_tenant_id,
        role=UserRole.client_admin,
        roles=[UserRole.client_admin],
        scope_kind=AccessScopeKind.client,
        scopes=[],
    )


def _resolve_outlook_client_context(user: UserDB, tenant_id: Optional[str]) -> TenantContext:
    tenant = _resolve_client_admin_context(user, tenant_id)
    if not tenant.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id requis pour connecter Outlook à un client.",
        )
    return tenant


def _resolve_turnover_client_context(user: UserDB, tenant_id: Optional[str]) -> TenantContext:
    tenant = _resolve_client_admin_context(user, tenant_id)
    if not tenant.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id requis pour gérer Turnover IT.",
        )
    return tenant


def _legacy_enterprise_ids(tenant_id: Optional[str]) -> list[str]:
    if not tenant_id:
        return []
    return [
        str(enterprise["id"])
        for enterprise in EnterpriseService.list_enterprises_by_tenant(tenant_id)
    ]


def _policy_response(
    connector_id: str,
    policy: Optional[ConnectorScopePolicyDB],
) -> ConnectorScopePolicyResponse:
    if policy is None:
        return ConnectorScopePolicyResponse(
            connector_id=connector_id,
            scope_policy=ConnectorScopePolicy.client_only,
            source="default",
        )
    return ConnectorScopePolicyResponse(
        connector_id=connector_id,
        scope_policy=policy.scope_policy,
        source="database",
        updated_at=policy.updated_at,
    )


def _normalize_secret_ref(secret_ref: Optional[str]) -> Optional[str]:
    if secret_ref is None:
        return None
    normalized = secret_ref.strip()
    return normalized or None


def _validate_https_url(target_url: str, field_name: str = "target_url") -> str:
    try:
        return validate_webhook_target_url(target_url)
    except UnsafeWebhookTargetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} non autorisee comme URL webhook.",
        ) from exc


def _normalize_event_types(event_types: List[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for event_type in event_types:
        cleaned = event_type.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)

    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event_types doit contenir au moins un type d'événement.",
        )
    return normalized


def _serialize_subscription(subscription) -> WebhookSubscriptionResponse:
    event_types = json.loads(subscription.event_types_json or "[]")
    if not isinstance(event_types, list):
        event_types = []

    return WebhookSubscriptionResponse(
        id=subscription.id,
        enterprise_id=subscription.enterprise_id,
        target_url=subscription.target_url,
        event_types=[str(event_type) for event_type in event_types],
        secret_ref=subscription.secret_ref,
        is_active=subscription.is_active,
        created_at=subscription.created_at,
    )


def _serialize_delivery_result(result: DeliveryResult) -> DeliveryResultResponse:
    return DeliveryResultResponse(
        subscription_id=result.subscription_id,
        target_url=result.target_url,
        status=result.status,
        status_code=result.status_code,
        response_body=result.response_body,
    )


# ---------------------------------------------------------------------------
# GET /connectors — public (authentifié), pas besoin de tenant context
# ---------------------------------------------------------------------------

@router.get("/connectors")
def list_connectors(
    family: Optional[str] = Query(None, description="Filtrer par famille (ex: sirh_fr)"),
    available_only: bool = Query(False, description="Ne retourner que les connecteurs disponibles"),
    _user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    """Liste les connecteurs du registry."""
    if family:
        connectors = registry.list_by_family(family)
    elif available_only:
        connectors = registry.list_available()
    else:
        connectors = registry.list_all()

    # Appliquer le filtre available_only même après family
    if available_only and family:
        connectors = [c for c in connectors if c.is_available]

    policies = {
        policy.connector_id: policy
        for policy in session.exec(select(ConnectorScopePolicyDB)).all()
    }
    response = []
    for connector in connectors:
        policy = (
            ConnectorScopePolicyResponse(
                connector_id=connector.id,
                scope_policy=ConnectorScopePolicy.client_only,
                source="enforced",
            )
            if connector.id in {"outlook", "turnover_it"}
            else _policy_response(connector.id, policies.get(connector.id))
        )
        setup_state = None
        oauth_start_available = None
        if connector.id == "outlook":
            outlook_configuration = get_outlook_oauth_configuration()
            setup_state = outlook_configuration.setup_state.value
            oauth_start_available = outlook_configuration.oauth_start_available
        response.append(
            {
                "id": connector.id,
                "name": connector.name,
                "family": connector.family.value,
                "capabilities": [cap.value for cap in connector.capabilities],
                "description": connector.description,
                "is_available": connector.is_available,
                "scope_policy": policy.scope_policy.value,
                "policy_source": policy.source,
                "setup_state": setup_state,
                "oauth_start_available": oauth_start_available,
            }
        )
    return response


@router.patch(
    "/connectors/{connector_id}/scope-policy",
    response_model=ConnectorScopePolicyResponse,
)
def update_connector_scope_policy(
    connector_id: str,
    payload: ConnectorScopePolicyUpdate,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    """Définit les portées d'instance autorisées pour un connecteur global."""
    if user.role != UserRole.platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un platform_admin peut modifier la portée d'un connecteur.",
        )

    connector = registry.get(connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connecteur '{connector_id}' introuvable.",
        )
    canonical_connector_id = registry.canonicalize(connector.info().id)
    if (
        canonical_connector_id in {"outlook", "turnover_it"}
        and payload.scope_policy != ConnectorScopePolicy.client_only
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le connecteur {canonical_connector_id} est limité aux instances client.",
        )
    equivalent_ids = registry.equivalent_ids(canonical_connector_id)

    accounts = session.exec(
        select(IntegrationAccountDB).where(
            IntegrationAccountDB.connector_id.in_(equivalent_ids)
        )
    ).all()
    incompatible = []
    for account in accounts:
        effective_scope = (
            IntegrationScopeKind.client
            if account.scope_kind == IntegrationScopeKind.enterprise_legacy
            else account.scope_kind
        )
        allowed = {
            ConnectorScopePolicy.client_only: {IntegrationScopeKind.client},
            ConnectorScopePolicy.platform_only: {IntegrationScopeKind.platform},
            ConnectorScopePolicy.client_or_platform: {
                IntegrationScopeKind.client,
                IntegrationScopeKind.platform,
            },
        }[payload.scope_policy]
        if effective_scope not in allowed:
            incompatible.append(f"{account.scope_kind.value}:{account.scope_id}")
    if incompatible:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "La nouvelle politique exclut des instances existantes.",
                "incompatible_scopes": sorted(set(incompatible)),
            },
        )

    policy = session.get(ConnectorScopePolicyDB, canonical_connector_id)
    if policy is None:
        policy = ConnectorScopePolicyDB(
            connector_id=canonical_connector_id,
            updated_by_user_id=str(user.id),
        )
    policy.scope_policy = payload.scope_policy
    policy.updated_by_user_id = str(user.id)
    policy.updated_at = datetime.now(timezone.utc)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return _policy_response(canonical_connector_id, policy)


@router.get(
    "/connectors/outlook/oauth/configuration",
    response_model=OutlookOAuthConfigurationResponse,
)
def get_outlook_oauth_setup(
    tenant_id: Optional[str] = Query(None, description="Client ciblé"),
    user: UserDB = Depends(get_current_user),
):
    """Expose un état de configuration sans valeur de credential."""
    _resolve_outlook_client_context(user, tenant_id)
    configuration = get_outlook_oauth_configuration()
    return OutlookOAuthConfigurationResponse(
        setup_state=configuration.setup_state.value,
        oauth_start_available=configuration.oauth_start_available,
    )


@router.post(
    "/connectors/outlook/oauth/start",
    response_model=OutlookOAuthConfigurationResponse,
)
def start_outlook_oauth(
    payload: OutlookOAuthStartRequest,
    user: UserDB = Depends(get_current_user),
):
    """Point d'entrée fail-closed du futur parcours OAuth Microsoft."""
    _resolve_outlook_client_context(user, payload.tenant_id)
    configuration = get_outlook_oauth_configuration()
    if configuration.setup_state == OutlookSetupState.configuration_required:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "setup_state": configuration.setup_state.value,
            },
        )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "setup_state": OutlookSetupState.authorization_unavailable.value,
            "message": "Le callback OAuth avec état et PKCE n'est pas encore activé.",
        },
    )


# ---------------------------------------------------------------------------
# GET /accounts — scoped par enterprise
# ---------------------------------------------------------------------------

@router.get("/accounts")
def list_accounts(
    tenant_id: Optional[str] = Query(None, description="Client ciblé"),
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    """Liste les comptes d'intégration configurés.

    - platform_admin : voit tout, ou filtre un client.
    - client_admin : voit son client et les instances plateforme.
    """
    tenant = _resolve_client_admin_context(user, tenant_id)
    resolved_tenant_id = tenant.tenant_id
    app = _build_accounts_app(session)
    try:
        accounts = app.list_accounts(
            tenant,
            tenant_id=resolved_tenant_id,
            legacy_enterprise_ids=_legacy_enterprise_ids(resolved_tenant_id),
        )
    except IntegrationAccountAppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return [account.model_dump(mode="json") for account in accounts]


@router.post("/accounts", response_model=IntegrationAccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: IntegrationAccountCreate,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    """Crée une instance client ou, pour la plateforme, une instance globale."""
    requested_tenant_id = (
        payload.tenant_id
        if payload.scope_kind == IntegrationScopeKind.client
        else None
    )
    tenant = _resolve_client_admin_context(user, requested_tenant_id)
    app = _build_accounts_app(session)
    try:
        account = app.create_account(
            tenant,
            payload,
            legacy_scope_ids=_legacy_enterprise_ids(tenant.tenant_id),
        )
    except IntegrationAccountAppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    session.commit()
    return account


# ---------------------------------------------------------------------------
# Turnover IT JobConnect — client-scoped specialized integration
# ---------------------------------------------------------------------------

@router.get("/turnover-it/configuration", response_model=TurnoverConfigurationResponse)
def get_turnover_configuration(
    tenant_id: Optional[str] = Query(None),
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    tenant = _resolve_turnover_client_context(user, tenant_id)
    account = get_turnover_account(session, str(tenant.tenant_id))
    return TurnoverConfigurationResponse(
        tenant_id=str(tenant.tenant_id),
        configured=bool(account and account.secret_ref),
        status=(account.status.value if account else "inactive"),
        api_base_url=TURNOVER_API_BASE_URL,
        updated_at=account.updated_at if account else None,
    )


@router.put("/turnover-it/configuration", response_model=TurnoverConfigurationResponse)
def put_turnover_configuration(
    payload: TurnoverConfigurationUpdate,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    tenant = _resolve_turnover_client_context(user, payload.tenant_id)
    try:
        account = configure_turnover_account(
            session, str(tenant.tenant_id), payload.token
        )
    except TurnoverITError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(account)
    return TurnoverConfigurationResponse(
        tenant_id=str(tenant.tenant_id),
        configured=True,
        status=account.status.value,
        api_base_url=TURNOVER_API_BASE_URL,
        updated_at=account.updated_at,
    )


@router.post("/turnover-it/test-connection", response_model=TurnoverConnectionTestResponse)
def post_turnover_test_connection(
    payload: TurnoverTenantRequest,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    tenant = _resolve_turnover_client_context(user, payload.tenant_id)
    try:
        connected, status_code, message = test_turnover_connection(
            session, str(tenant.tenant_id)
        )
    except TurnoverITError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TurnoverConnectionTestResponse(
        connected=connected, status_code=status_code, message=message
    )


def _turnover_project_and_context(
    session: Session, project_id: str, user: UserDB
) -> tuple[ProjectDB, TenantContext]:
    project = session.get(ProjectDB, project_id)
    enterprise = session.get(EnterpriseDB, project.enterprise_id) if project else None
    if project is None or enterprise is None or not enterprise.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable.")
    tenant = _resolve_turnover_client_context(user, str(enterprise.tenant_id))
    return project, tenant


@router.post(
    "/turnover-it/publications",
    response_model=TurnoverPublicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_turnover_publication(
    payload: TurnoverPublicationCreate,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    project, tenant = _turnover_project_and_context(session, payload.project_id, user)
    tenant_id = str(tenant.tenant_id)
    account = get_turnover_account(session, tenant_id)
    if account is None or account.status != ConnectorStatus.active or not account.secret_ref:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Intégration Turnover IT non configurée pour ce client.",
        )
    if not payload.region and not payload.postal_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Une région ou un code postal est requis pour Turnover IT.",
        )
    try:
        turnover_offer_content(project)
    except TurnoverITError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    public_api_base_url = get_public_api_base_url()
    if not public_api_base_url or not public_api_base_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PUBLIC_API_BASE_URL HTTPS requis pour publier sur Turnover IT.",
        )
    publication_id = str(uuid.uuid4())
    callback_url = (
        f"{public_api_base_url}/api/v1/integrations/turnover-it/webhooks/{publication_id}"
    )
    publication = create_turnover_publication_record(
        session,
        tenant_id=tenant_id,
        project=project,
        contract=payload.contract,
        remote=payload.remote,
        country=payload.country,
        region=payload.region,
        postal_code=payload.postal_code,
        requested_status=payload.requested_status,
        callback_url=callback_url,
        publication_id=publication_id,
    )
    session.commit()
    session.refresh(publication)
    return publication_response(session, publication)


@router.get(
    "/turnover-it/publications/project/{project_id}",
    response_model=List[TurnoverPublicationResponse],
)
def list_turnover_publications(
    project_id: str,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    _, tenant = _turnover_project_and_context(session, project_id, user)
    publications = session.exec(
        select(TurnoverJobPublicationDB)
        .where(
            TurnoverJobPublicationDB.tenant_id == str(tenant.tenant_id),
            TurnoverJobPublicationDB.project_id == project_id,
        )
        .order_by(TurnoverJobPublicationDB.created_at.desc())
    ).all()
    return [publication_response(session, publication) for publication in publications]


@router.post(
    "/turnover-it/publications/{publication_id}/simulate-application",
    response_model=TurnoverIngestionResponse,
)
def simulate_turnover_application(
    publication_id: str,
    payload: TurnoverSimulationRequest,
    user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    publication = session.get(TurnoverJobPublicationDB, publication_id)
    tenant_id = publication.tenant_id if publication else None
    tenant = _resolve_turnover_client_context(user, tenant_id)
    if publication is None or publication.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication introuvable.")
    try:
        token = resolve_turnover_token(session, publication.tenant_id)
        if not token.startswith("test-"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Simulation réservée aux tokens Turnover IT de test.",
            )
        result = ingest_turnover_application(
            session,
            publication,
            simulate_payload(publication, payload.model_dump(), token),
            expected_token=token,
        )
    except TurnoverITError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return result


@router.post(
    "/turnover-it/webhooks/{publication_id}",
    response_model=TurnoverIngestionResponse,
)
def receive_turnover_application(
    publication_id: str,
    payload: Dict[str, Any],
    session: Session = Depends(get_session_dependency),
):
    publication = session.get(TurnoverJobPublicationDB, publication_id)
    if publication is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication introuvable.")
    try:
        token = resolve_turnover_token(session, publication.tenant_id)
        result = ingest_turnover_application(
            session, publication, payload, expected_token=token
        )
    except TurnoverITError as exc:
        http_status = (
            status.HTTP_401_UNAUTHORIZED
            if "Token de callback" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=http_status, detail=str(exc)) from exc
    session.commit()
    return result


@router.get("/subscriptions", response_model=List[WebhookSubscriptionResponse])
def list_subscriptions(
    active_only: Optional[bool] = Query(None, description="Filtrer les souscriptions actives"),
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Liste les souscriptions webhook de l'enterprise courante."""
    admin_tenant = _require_integration_admin(tenant)
    subscriptions = IntegrationEventService.list_subscriptions(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        active_only=active_only,
    )
    return [_serialize_subscription(subscription) for subscription in subscriptions]


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    payload: WebhookSubscriptionCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Crée une souscription webhook pour l'enterprise courante."""
    admin_tenant = _require_integration_admin(tenant)
    subscription = IntegrationEventService.create_subscription(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        target_url=_validate_https_url(payload.target_url),
        event_types=_normalize_event_types(payload.event_types),
        secret_ref=_normalize_secret_ref(payload.secret_ref),
    )
    subscription.is_active = payload.is_active
    session.add(subscription)
    session.commit()
    session.refresh(subscription)
    return _serialize_subscription(subscription)


@router.patch("/subscriptions/{subscription_id}", response_model=WebhookSubscriptionResponse)
def update_subscription(
    subscription_id: str,
    payload: WebhookSubscriptionUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Met à jour une souscription webhook existante."""
    admin_tenant = _require_integration_admin(tenant)
    subscription = IntegrationEventService.get_subscription(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        subscription_id=subscription_id,
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Souscription {subscription_id} introuvable.",
        )

    provided_fields = payload.model_dump(exclude_unset=True)
    updated = IntegrationEventService.update_subscription(
        session,
        subscription,
        target_url=_validate_https_url(payload.target_url) if "target_url" in provided_fields else None,
        event_types=_normalize_event_types(payload.event_types) if "event_types" in provided_fields else None,
        secret_ref=_normalize_secret_ref(payload.secret_ref) if "secret_ref" in provided_fields else None,
        secret_ref_was_set="secret_ref" in provided_fields,
        is_active=payload.is_active if "is_active" in provided_fields else None,
    )
    session.commit()
    session.refresh(updated)
    return _serialize_subscription(updated)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    subscription_id: str,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Désactive une souscription webhook sans supprimer l'historique."""
    admin_tenant = _require_integration_admin(tenant)
    subscription = IntegrationEventService.get_subscription(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        subscription_id=subscription_id,
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Souscription {subscription_id} introuvable.",
        )

    IntegrationEventService.deactivate_subscription(session, subscription)
    session.commit()
    return None


@router.post("/events/emit", response_model=EmitIntegrationEventResponse)
def emit_event(
    payload: EmitIntegrationEventRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Émet un événement d'intégration pour l'enterprise courante."""
    admin_tenant = _require_integration_admin(tenant)
    normalized_event_type = payload.event_type.strip()
    if not normalized_event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event_type est requis.",
        )
    event = IntegrationEventService.emit_event(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        event_type=normalized_event_type,
        payload=payload.payload,
    )

    deliveries: List[DeliveryResult] = []
    if payload.process_now:
        deliveries = WebhookDeliveryService.deliver_event(
            session,
            event,
            http_sender=httpx_sender,
        )

    session.commit()
    session.refresh(event)

    return EmitIntegrationEventResponse(
        id=event.id,
        enterprise_id=event.enterprise_id,
        event_type=event.event_type,
        status=event.status,
        retry_count=event.retry_count,
        created_at=event.created_at,
        processed_now=payload.process_now,
        deliveries=[_serialize_delivery_result(result) for result in deliveries],
    )


@router.post("/events/process-pending", response_model=ProcessPendingEventsResponse)
def process_pending_events(
    payload: ProcessPendingEventsRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Traite les événements pending/retrying pour l'enterprise courante."""
    admin_tenant = _require_integration_admin(tenant)
    summary = WebhookDeliveryService.process_pending_events(
        session,
        enterprise_id=admin_tenant.enterprise_id,
        http_sender=httpx_sender,
        limit=payload.limit,
    )
    session.commit()
    return ProcessPendingEventsResponse(
        enterprise_id=admin_tenant.enterprise_id,
        events_processed=summary["events_processed"],
        total_deliveries=summary["total_deliveries"],
        success=summary["success"],
        failures=summary["failures"],
    )


# ---------------------------------------------------------------------------
# GET /events — scoped par enterprise
# ---------------------------------------------------------------------------

@router.get("/events")
def list_events(
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session_dependency),
    limit: int = Query(50, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """Liste les événements de l'outbox.

    - platform_admin : voit tout.
    - Autres rôles : filtrés par enterprise_id.
    """
    stmt = select(OutboundEventDB)

    if tenant.role != UserRole.platform_admin:
        stmt = stmt.where(OutboundEventDB.enterprise_id == tenant.enterprise_id)

    if status_filter:
        stmt = stmt.where(OutboundEventDB.status == status_filter)

    stmt = stmt.order_by(OutboundEventDB.created_at.desc()).limit(limit)
    events = session.exec(stmt).all()

    return [
        {
            "id": e.id,
            "enterprise_id": e.enterprise_id,
            "event_type": e.event_type,
            "status": e.status.value if hasattr(e.status, "value") else e.status,
            "retry_count": e.retry_count,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
