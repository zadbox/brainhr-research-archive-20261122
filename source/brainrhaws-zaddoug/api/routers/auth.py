from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import Session, select

from brainrh.database import get_session_dependency
from brainrh.models.auth import MembershipDB, UserLogin, UserResponse, UserDB, UserRole
from brainrh.services.request_limiter import InMemoryRateLimiter
from brainrh.services.auth_service import (
    get_current_user_from_token,
    list_accessible_enterprise_ids,
    revoke_user_tokens,
    verify_password,
)
from brainrh.services.audit_service import AuditService
from brainrh.services.invitation_service import InvitationService
from brainrh.settings import (
    get_auth_cookie_domain,
    get_auth_cookie_samesite,
    get_auth_cookie_secure,
    get_login_rate_limit_attempts,
    get_login_rate_limit_window_seconds,
    get_google_auth_config,
)
from api.dependencies import get_current_user
from api.auth_session import set_session_cookie
from api.routers import google_auth, invitation_assets
from brainrh.models.auth import GoogleIdentityDB

router = APIRouter(prefix="/auth", tags=["Authentication"])
router.include_router(google_auth.router)
router.include_router(invitation_assets.router)
_invitation_service = InvitationService()


class InvitationTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


class AcceptInvitationRequest(InvitationTokenRequest):
    password: Optional[str] = Field(default=None, max_length=128)


class InvitationStateResponse(BaseModel):
    status: Literal[
        "ready",
        "accepted",
        "expired",
        "used",
        "invalid",
        "email_unavailable",
    ]
    requires_password: bool = False
    expires_at: Optional[datetime] = None
    tenant_name: Optional[str] = None
    trial_duration_days: Optional[int] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    trial_status: Optional[Literal["pending", "active", "expired"]] = None


def _user_can_manage_users(user: UserDB, session: Session) -> bool:
    if user.role == UserRole.platform_admin:
        return True
    if list_accessible_enterprise_ids(user, required_roles={UserRole.enterprise_admin}):
        return True
    return False


def _user_trial_metadata(user: UserDB, session: Session) -> dict:
    from brainrh.models.auth import AccessGrantDB, AccessScopeKind, TenantDB
    from brainrh.models.enterprise import EnterpriseDB
    from brainrh.services.auth_service import tenant_trial_metadata

    tenant_ids = {str(user.tenant_id)} if user.tenant_id else set()
    client_grants = session.exec(
        select(AccessGrantDB).where(
            AccessGrantDB.user_id == str(user.id),
            AccessGrantDB.scope_kind == AccessScopeKind.client,
            AccessGrantDB.is_active == True,  # noqa: E712
        )
    ).all()
    tenant_ids.update(str(grant.scope_id) for grant in client_grants)
    membership_enterprise_ids = session.exec(
        select(MembershipDB.enterprise_id).where(
            MembershipDB.user_id == str(user.id),
            MembershipDB.is_active == True,  # noqa: E712
        )
    ).all()
    if membership_enterprise_ids:
        enterprises = session.exec(
            select(EnterpriseDB).where(EnterpriseDB.id.in_(membership_enterprise_ids))
        ).all()
        tenant_ids.update(str(enterprise.tenant_id) for enterprise in enterprises if enterprise.tenant_id)

    if len(tenant_ids) != 1:
        return {
            "trial_tenant_id": None,
            "tenant_name": None,
            "trial_duration_days": None,
            "trial_started_at": None,
            "trial_expires_at": None,
            "trial_status": None,
        }
    tenant = session.get(TenantDB, next(iter(tenant_ids)))
    if tenant is None:
        return {
            "trial_tenant_id": None,
            "tenant_name": None,
            "trial_duration_days": None,
            "trial_started_at": None,
            "trial_expires_at": None,
            "trial_status": None,
        }
    return {
        "trial_tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        **tenant_trial_metadata(tenant),
    }


def _to_user_response(user: UserDB, session: Session) -> UserResponse:
    google_identity = session.get(GoogleIdentityDB, str(user.id))
    trial_metadata = _user_trial_metadata(user, session)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        is_active=user.is_active,
        can_manage_users=_user_can_manage_users(user, session),
        display_name=google_identity.display_name if google_identity else None,
        google_linked=google_identity is not None,
        google_auth_enabled=get_google_auth_config() is not None,
        **trial_metadata,
    )


@router.post("/login", response_model=UserResponse)
def login(
    user_login: UserLogin,
    request: Request,
    response: Response,
    session: Session = Depends(get_session_dependency),
):
    client_ip = request.client.host if request.client else "unknown"
    normalized_email = user_login.email.strip().lower()
    attempts_limit = get_login_rate_limit_attempts()
    attempts_window = get_login_rate_limit_window_seconds()

    allowed_by_ip, retry_after_ip = InMemoryRateLimiter.consume(
        bucket="auth-login-ip",
        key=client_ip,
        limit=attempts_limit,
        window_seconds=attempts_window,
    )
    allowed_by_email, retry_after_email = InMemoryRateLimiter.consume(
        bucket="auth-login-email",
        key=f"{normalized_email}:{client_ip}",
        limit=attempts_limit,
        window_seconds=attempts_window,
    )
    if not allowed_by_ip or not allowed_by_email:
        retry_after = max(retry_after_ip, retry_after_email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives de connexion. Réessayez plus tard.",
            headers={"Retry-After": str(retry_after)},
        )

    user = session.exec(
        select(UserDB).where(func.lower(UserDB.email) == normalized_email)
    ).first()
    if (
        not user
        or not user.hashed_password
        or not verify_password(user_login.password, user.hashed_password)
    ):
        AuditService.create_event(
            session=session,
            enterprise_id="SYSTEM",
            action="auth.login.failed",
            resource_type="system",
            resource_id="login",
            actor_user_id=str(user.id) if user else None,
            metadata={"email": user_login.email}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
        )

    if not user.is_active:
        AuditService.create_event(
            session=session,
            enterprise_id="SYSTEM",
            action="auth.login.failed",
            resource_type="system",
            resource_id="login",
            actor_user_id=str(user.id),
            metadata={"email": user_login.email, "reason": "inactive"}
        )
        raise HTTPException(status_code=400, detail="Utilisateur inactif")

    AuditService.create_event(
        session=session,
        enterprise_id="SYSTEM",
        action="auth.login.success",
        resource_type="system",
        resource_id="login",
        actor_user_id=str(user.id),
        metadata={"email": user.email}
    )

    InMemoryRateLimiter.reset(bucket="auth-login-ip", key=client_ip)
    InMemoryRateLimiter.reset(bucket="auth-login-email", key=f"{normalized_email}:{client_ip}")
    set_session_cookie(response, str(user.id))

    return _to_user_response(user, session)

@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session_dependency),
):
    # Note: On déconnecte le client quoi qu'il arrive
    # Un vrai audit logout impliquerait de vérifier le token actuel.
    # Pour respecter 'sans token ni paswword', on se contente du log générique.
    current_user = None
    token = request.cookies.get("access_token")
    if not token:
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1]

    if token:
        try:
            current_user = get_current_user_from_token(token)
        except HTTPException:
            current_user = None

    try:
        if current_user is not None:
            revoke_user_tokens(
                session,
                str(current_user.id),
                reason="logout",
                actor_user_id=str(current_user.id),
            )
        AuditService.create_event(
            session=session,
            enterprise_id="SYSTEM",
            action="auth.logout",
            resource_type="system",
            resource_id="logout",
            actor_user_id=str(current_user.id) if current_user is not None else None,
            metadata={"action": "Client requested logout"}
        )
    except Exception:
        pass

    cookie_secure = get_auth_cookie_secure()
    cookie_samesite = get_auth_cookie_samesite()
    cookie_domain = get_auth_cookie_domain()

    response.delete_cookie(
        "access_token",
        path="/",
        samesite=cookie_samesite,
        secure=cookie_secure,
        domain=cookie_domain,
    )
    return {"message": "Déconnexion réussie"}

@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    return _to_user_response(current_user, session)


@router.post(
    "/invitations/inspect",
    response_model=InvitationStateResponse,
    response_model_exclude_none=True,
)
def inspect_invitation(body: InvitationTokenRequest) -> InvitationStateResponse:
    result = _invitation_service.inspect(body.token)
    return InvitationStateResponse(
        status=result.status,
        requires_password=result.requires_password,
        expires_at=result.expires_at,
        tenant_name=result.tenant_name,
        trial_duration_days=result.trial_duration_days,
        trial_started_at=result.trial_started_at,
        trial_expires_at=result.trial_expires_at,
        trial_status=result.trial_status,
    )


@router.post(
    "/invitations/accept",
    response_model=InvitationStateResponse,
    response_model_exclude_none=True,
)
def accept_invitation(body: AcceptInvitationRequest) -> InvitationStateResponse:
    result = _invitation_service.accept(token=body.token, password=body.password)
    return InvitationStateResponse(
        status=result.status,
        requires_password=result.requires_password,
        expires_at=result.expires_at,
        tenant_name=result.tenant_name,
        trial_duration_days=result.trial_duration_days,
        trial_started_at=result.trial_started_at,
        trial_expires_at=result.trial_expires_at,
        trial_status=result.trial_status,
    )
