"""
Router Admin Users — ADMIN-FIX-001

Endpoints:
- GET  /api/v1/admin/users              → liste des utilisateurs
- POST /api/v1/admin/users/invite       → inviter un utilisateur
- PATCH /api/v1/admin/users/{id}/role   → changer le rôle membership
- PATCH /api/v1/admin/users/{id}/status → activer/désactiver un membership

Règles d'accès:
- platform_admin: accès global
- enterprise_admin: accès limité à son entreprise
- recruiter / viewer: 403
"""

from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
from brainrh.models.auth import UserDB, UserRole
from brainrh.services.admin_user_service import (
    AdminClientResponse,
    AdminUserResponse,
    AdminUserService,
)
from brainrh.services.auth_service import list_accessible_enterprise_ids

router = APIRouter(prefix="/admin/users", tags=["Administration"])

_service = AdminUserService()

ADMIN_USER_SCOPE_HEADER = "X-Admin-User-Scope"


# ---------------------------------------------------------------------------
# Schémas de requête
# ---------------------------------------------------------------------------

class InviteUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(min_length=3, max_length=64)
    tenant_id: Optional[str] = None
    language: Literal["en", "fr"] = "en"
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)


class ResendInvitationRequest(BaseModel):
    language: Optional[Literal["en", "fr"]] = None


class UpdateRoleRequest(BaseModel):
    role: str


class UpdateStatusRequest(BaseModel):
    is_active: bool


class CreateClientRequest(BaseModel):
    name: str = Field(max_length=255)
    trial_duration_days: Optional[int] = Field(default=None, ge=1, le=365)


class ExtendClientTrialRequest(BaseModel):
    extend_days: int = Field(ge=1, le=365)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_role(role_str: str) -> UserRole:
    try:
        return UserRole(role_str)
    except ValueError:
        allowed = ", ".join(role.value for role in UserRole)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rôle inconnu: '{role_str}'. Valeurs valides: {allowed}.",
        )


def _get_enterprise_id(request: Request, current_user: UserDB) -> Optional[str]:
    """Extrait X-Enterprise-ID depuis le header de la requête."""
    enterprise_id = request.headers.get("X-Enterprise-ID")
    if not enterprise_id:
        return None
    return enterprise_id.strip() or None


def _get_admin_user_scope(request: Request) -> Optional[str]:
    """Extrait le scope explicite des mutations admin user."""
    scope = request.headers.get(ADMIN_USER_SCOPE_HEADER)
    return scope.strip().lower() if scope else None


def _require_min_role(current_user: UserDB) -> None:
    """Refuse recruiter et viewer sans membership enterprise_admin actif.

    Un enterprise_admin peut avoir UserDB.role = viewer (rôle global minimal).
    Son rôle effectif est déterminé par ses memberships.
    """
    if current_user.role == UserRole.platform_admin:
        return  # accès total

    if list_accessible_enterprise_ids(current_user, required_roles={UserRole.enterprise_admin}):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Accès refusé : rôle insuffisant. Seuls platform_admin et les rôles admin enterprise compatibles peuvent accéder à l'administration.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/clients", response_model=List[AdminClientResponse])
def list_clients(
    current_user: UserDB = Depends(get_current_user),
) -> List[AdminClientResponse]:
    return _service.list_clients(actor=current_user)


@router.post(
    "/clients",
    response_model=AdminClientResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_client(
    body: CreateClientRequest,
    current_user: UserDB = Depends(get_current_user),
) -> AdminClientResponse:
    return _service.create_client(
        actor=current_user,
        name=body.name,
        trial_duration_days=body.trial_duration_days,
    )


@router.patch("/clients/{tenant_id}/trial", response_model=AdminClientResponse)
def extend_client_trial(
    tenant_id: str,
    body: ExtendClientTrialRequest,
    current_user: UserDB = Depends(get_current_user),
) -> AdminClientResponse:
    return _service.extend_client_trial(
        actor=current_user,
        tenant_id=tenant_id,
        extend_days=body.extend_days,
    )


@router.get("", response_model=List[AdminUserResponse])
def list_admin_users(
    request: Request,
    current_user: UserDB = Depends(get_current_user),
) -> List[AdminUserResponse]:
    """Liste les utilisateurs.

    - platform_admin sans X-Enterprise-ID → tous les users
    - platform_admin avec X-Enterprise-ID → filtre par entreprise
    - enterprise_admin → uniquement son entreprise
    """
    _require_min_role(current_user)
    enterprise_id = _get_enterprise_id(request, current_user)
    return _service.list_users(actor=current_user, enterprise_id=enterprise_id)


@router.post("/invite", response_model=AdminUserResponse)
def invite_user(
    body: InviteUserRequest,
    request: Request,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
) -> AdminUserResponse:
    """Invite un utilisateur dans une entreprise.

    - platform_admin: rôle global, réservé au platform_admin
    - client_admin: grant client/tenant, réservé au platform_admin
    - enterprise_admin/recruiter/viewer: membership enterprise
    - enterprise_id='platform' interdit
    """
    _require_min_role(current_user)
    enterprise_id = _get_enterprise_id(request, current_user)
    role = _parse_role(body.role)
    if role == UserRole.platform_admin:
        result = _service.invite_platform_admin(
            actor=current_user,
            email=body.email,
            language=body.language,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    elif role == UserRole.client_admin:
        result = _service.invite_client_admin(
            actor=current_user,
            email=body.email,
            tenant_id=body.tenant_id,
            enterprise_id=enterprise_id,
            language=body.language,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    else:
        result = _service.invite_user(
            actor=current_user,
            email=body.email,
            role=role,
            enterprise_id=enterprise_id,
            language=body.language,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    if result.invitation_status == "delivery_failed":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=AdminUserResponse,
)
def resend_invitation(
    invitation_id: str,
    body: ResendInvitationRequest,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
) -> AdminUserResponse:
    _require_min_role(current_user)
    result = _service.resend_invitation(
        actor=current_user,
        invitation_id=invitation_id,
        language=body.language,
    )
    if result.invitation_status == "delivery_failed":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.patch("/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: str,
    body: UpdateRoleRequest,
    request: Request,
    current_user: UserDB = Depends(get_current_user),
) -> AdminUserResponse:
    """Change le rôle de membership d'un utilisateur.

    - platform_admin interdit comme rôle cible
    """
    _require_min_role(current_user)
    enterprise_id = _get_enterprise_id(request, current_user)
    new_role = _parse_role(body.role)
    return _service.update_membership_role(
        actor=current_user,
        user_id=user_id,
        new_role=new_role,
        enterprise_id=enterprise_id,
    )


@router.patch("/{user_id}/status", response_model=AdminUserResponse)
def update_user_status(
    user_id: str,
    body: UpdateStatusRequest,
    request: Request,
    current_user: UserDB = Depends(get_current_user),
) -> AdminUserResponse:
    """Active ou désactive un membership (ou globalement si platform_admin sans enterprise).

    - Désactivation membership ne touche jamais UserDB.is_active sauf platform_admin sans enterprise_id.
    """
    _require_min_role(current_user)
    enterprise_id = _get_enterprise_id(request, current_user)
    admin_user_scope = _get_admin_user_scope(request)
    return _service.toggle_membership_status(
        actor=current_user,
        user_id=user_id,
        is_active=body.is_active,
        enterprise_id=enterprise_id,
        admin_user_scope=admin_user_scope,
    )
