from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, List, Union
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status
import json
import logging
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from brainrh.database import get_session_direct
from brainrh.models.audit_log import AuditLogDB
from brainrh.models.auth import AccessGrantDB, AccessScopeKind, UserDB, UserRole, MembershipDB, TenantDB
from brainrh.settings import get_secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
TOKEN_VERSION_CLAIM = "token_version"
TOKEN_REVOCATION_ACTION = "auth.tokens.revoked"
TOKEN_REVOCATION_RESOURCE_TYPE = "user"
CLIENT_TRIAL_EXPIRED = "CLIENT_TRIAL_EXPIRED"
CLIENT_TRIAL_PENDING = "CLIENT_TRIAL_PENDING"

import bcrypt
_original_hashpw = bcrypt.hashpw


def _patched_hashpw(password, salt):
    if len(password) > 72:
        password = password[:72]
    return _original_hashpw(password, salt)


bcrypt.hashpw = _patched_hashpw

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_PRECEDENCE: dict[UserRole, int] = {
    UserRole.platform_admin: 60,
    UserRole.client_admin: 50,
    UserRole.enterprise_admin: 40,
    UserRole.project_manager: 30,
    UserRole.recruiter: 20,
    UserRole.viewer: 10,
}

ROLE_IMPLICATIONS: dict[UserRole, set[UserRole]] = {
    UserRole.platform_admin: {
        UserRole.platform_admin,
        UserRole.client_admin,
        UserRole.enterprise_admin,
        UserRole.project_manager,
        UserRole.recruiter,
        UserRole.viewer,
    },
    UserRole.client_admin: {
        UserRole.client_admin,
        UserRole.enterprise_admin,
        UserRole.project_manager,
        UserRole.recruiter,
        UserRole.viewer,
    },
    UserRole.enterprise_admin: {
        UserRole.enterprise_admin,
        UserRole.project_manager,
        UserRole.recruiter,
        UserRole.viewer,
    },
    UserRole.project_manager: {
        UserRole.project_manager,
        UserRole.recruiter,
        UserRole.viewer,
    },
    UserRole.recruiter: {
        UserRole.recruiter,
        UserRole.viewer,
    },
    UserRole.viewer: {
        UserRole.viewer,
    },
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_user_token_version(session: Session, user_id: str) -> int:
    # Use the existing audit log primary key as a durable per-user revocation marker.
    latest_revocation_id = session.exec(
        select(AuditLogDB.id)
        .where(
            AuditLogDB.action == TOKEN_REVOCATION_ACTION,
            AuditLogDB.resource_type == TOKEN_REVOCATION_RESOURCE_TYPE,
            AuditLogDB.resource_id == str(user_id),
        )
        .order_by(AuditLogDB.id.desc())
        .limit(1)
    ).first()
    return int(latest_revocation_id or 0)


def revoke_user_tokens(
    session: Session,
    user_id: str,
    *,
    reason: str,
    actor_user_id: Optional[str] = None,
) -> int:
    # Serialize revocation with identity linking/session issuance for this user.
    session.exec(select(UserDB).where(UserDB.id == str(user_id)).with_for_update()).first()
    revocation = AuditLogDB(
        enterprise_id="SYSTEM",
        actor_user_id=str(actor_user_id) if actor_user_id is not None else None,
        action=TOKEN_REVOCATION_ACTION,
        resource_type=TOKEN_REVOCATION_RESOURCE_TYPE,
        resource_id=str(user_id),
        metadata_json=json.dumps({"reason": reason}),
    )
    session.add(revocation)
    session.commit()
    session.refresh(revocation)
    return int(revocation.id or 0)


def _token_version_for_subject(user_id: str) -> int:
    with get_session_direct() as session:
        return get_user_token_version(session, str(user_id))


def _decode_token_version(payload: dict) -> int:
    token_version = payload.get(TOKEN_VERSION_CLAIM)
    if token_version is None:
        return 0
    try:
        decoded_version = int(token_version)
    except (TypeError, ValueError):
        raise _credentials_exception()
    if decoded_version < 0:
        raise _credentials_exception()
    return decoded_version


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    user_id = to_encode.get("sub")
    if user_id is not None and TOKEN_VERSION_CLAIM not in to_encode:
        to_encode[TOKEN_VERSION_CLAIM] = _token_version_for_subject(str(user_id))
    expire_delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + expire_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user_from_token(token: str) -> UserDB:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise _credentials_exception()
        token_version = _decode_token_version(payload)
    except JWTError:
        raise _credentials_exception()

    with get_session_direct() as session:
        user = session.exec(select(UserDB).where(UserDB.id == user_id)).first()
        if user is None:
            raise _credentials_exception()
        if not user.is_active:
            raise _credentials_exception("Utilisateur inactif")
        if token_version != get_user_token_version(session, str(user.id)):
            raise _credentials_exception()
        return user


class TenantContext(BaseModel):
    """Contexte d'accès résolu pour un scope enterprise ou project."""

    user_id: str
    tenant_id: Optional[str] = None
    enterprise_id: Optional[str] = None
    project_id: Optional[str] = None
    role: UserRole
    roles: List[UserRole] = Field(default_factory=list)
    scope_kind: Optional[AccessScopeKind] = None
    scopes: List[str] = Field(default_factory=list)


def parse_scopes(scopes_json: Optional[str]) -> List[str]:
    """Parse une chaîne JSON représentant une liste de scopes en liste Python."""
    if not scopes_json:
        return []
    try:
        parsed = json.loads(scopes_json)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        logging.warning("scopes_json n'est pas une liste JSON, fallback vers []")
        return []
    except json.JSONDecodeError as exc:
        logging.error(f"Erreur de parsing scopes_json: {exc}")
        return []


def _sorted_roles(roles: Iterable[UserRole]) -> List[UserRole]:
    return sorted(
        {UserRole(role) for role in roles},
        key=lambda role: (-ROLE_PRECEDENCE.get(role, 0), role.value),
    )


def _primary_role(roles: Iterable[UserRole]) -> UserRole:
    ordered_roles = _sorted_roles(roles)
    if not ordered_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aucun rôle effectif actif pour ce contexte.",
        )
    return ordered_roles[0]


def expand_role(role: UserRole) -> set[UserRole]:
    return set(ROLE_IMPLICATIONS.get(role, {role}))


def user_roles_satisfy(
    roles: Iterable[UserRole],
    required_roles: Iterable[UserRole],
) -> bool:
    expanded_roles: set[UserRole] = set()
    for role in roles:
        expanded_roles.update(expand_role(UserRole(role)))
    return any(required_role in expanded_roles for required_role in required_roles)


def tenant_has_any_role(tenant: TenantContext, required_roles: Iterable[UserRole]) -> bool:
    direct_roles = tenant.roles or [tenant.role]
    return user_roles_satisfy(direct_roles, required_roles)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def tenant_trial_status(
    tenant: TenantDB,
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Return the computed trial status; ``None`` means unlimited access."""
    if tenant.trial_duration_days is None:
        return None
    started_at = _as_utc(tenant.trial_started_at)
    expires_at = _as_utc(tenant.trial_expires_at)
    if started_at is None:
        return "pending"
    current_time = _as_utc(now) or datetime.now(timezone.utc)
    if expires_at is None or current_time >= expires_at:
        return "expired"
    return "active"


def tenant_trial_metadata(tenant: TenantDB) -> dict:
    return {
        "trial_duration_days": tenant.trial_duration_days,
        "trial_started_at": _as_utc(tenant.trial_started_at),
        "trial_expires_at": _as_utc(tenant.trial_expires_at),
        "trial_status": tenant_trial_status(tenant),
    }


def get_tenant_trial_metadata(tenant_id: Optional[str]) -> dict:
    if not tenant_id:
        return {
            "trial_duration_days": None,
            "trial_started_at": None,
            "trial_expires_at": None,
            "trial_status": None,
        }
    with get_session_direct() as session:
        tenant = session.get(TenantDB, str(tenant_id))
        if tenant is None:
            return {
                "trial_duration_days": None,
                "trial_started_at": None,
                "trial_expires_at": None,
                "trial_status": None,
            }
        return tenant_trial_metadata(tenant)


def require_tenant_trial_access(tenant_id: Optional[str]) -> None:
    """Fail closed for a configured trial that has not started or has expired."""
    if not tenant_id:
        return
    with get_session_direct() as session:
        tenant = session.get(TenantDB, str(tenant_id))
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "CLIENT_ACCESS_DENIED", "message": "Client introuvable."},
            )
        trial_status = tenant_trial_status(tenant)
        if trial_status == "pending":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": CLIENT_TRIAL_PENDING,
                    "message": "L'essai client n'a pas encore démarré.",
                },
            )
        if trial_status == "expired":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": CLIENT_TRIAL_EXPIRED,
                    "message": "L'essai client est arrivé à expiration.",
                    "trial_expires_at": _as_utc(tenant.trial_expires_at).isoformat()
                    if tenant.trial_expires_at
                    else None,
                },
            )


def tenant_trial_accessible(tenant_id: Optional[str]) -> bool:
    try:
        require_tenant_trial_access(tenant_id)
    except HTTPException:
        return False
    return True


def _grant_applies_to_target(
    grant: AccessGrantDB,
    *,
    tenant_id: Optional[str],
    enterprise_id: Optional[str],
    project_id: Optional[str],
) -> bool:
    if grant.scope_kind == AccessScopeKind.client:
        return bool(tenant_id) and str(grant.scope_id) == str(tenant_id)
    if grant.scope_kind == AccessScopeKind.enterprise:
        return bool(enterprise_id) and str(grant.scope_id) == str(enterprise_id)
    if grant.scope_kind == AccessScopeKind.project:
        return bool(project_id) and str(grant.scope_id) == str(project_id)
    return False


def _normalize_user_id(user_or_id: Union[UserDB, str]) -> str:
    if isinstance(user_or_id, UserDB):
        return str(user_or_id.id)
    return str(user_or_id)


def get_membership_for_user(user_id: str, enterprise_id: str) -> Optional[MembershipDB]:
    """Retourne le membership actif d'un user pour une enterprise donnée, ou None."""
    with get_session_direct() as session:
        membership = session.exec(
            select(MembershipDB).where(
                MembershipDB.user_id == user_id,
                MembershipDB.enterprise_id == enterprise_id,
                MembershipDB.is_active == True,  # noqa: E712
            )
        ).first()
        return membership


def list_memberships_for_user(user_id: str) -> List[MembershipDB]:
    """Retourne tous les memberships actifs d'un utilisateur."""
    with get_session_direct() as session:
        memberships = session.exec(
            select(MembershipDB).where(
                MembershipDB.user_id == user_id,
                MembershipDB.is_active == True,  # noqa: E712
            )
        ).all()
        return list(memberships)


def list_access_grants_for_user(user_or_id: Union[UserDB, str]) -> List[AccessGrantDB]:
    user_id = _normalize_user_id(user_or_id)
    with get_session_direct() as session:
        grants = session.exec(
            select(AccessGrantDB).where(
                AccessGrantDB.user_id == user_id,
                AccessGrantDB.is_active == True,  # noqa: E712
            )
        ).all()
        return list(grants)


def list_direct_project_grant_ids(
    user_or_id: Union[UserDB, str],
    *,
    required_roles: Optional[set[UserRole]] = None,
    access_grants: Optional[Iterable[AccessGrantDB]] = None,
) -> List[str]:
    project_ids: set[str] = set()
    resolved_access_grants = (
        list_access_grants_for_user(user_or_id)
        if access_grants is None
        else access_grants
    )
    for grant in resolved_access_grants:
        if grant.scope_kind != AccessScopeKind.project:
            continue
        if required_roles and not user_roles_satisfy([grant.role], required_roles):
            continue
        from brainrh.services.enterprise_service import EnterpriseService
        from brainrh.services.project_service import ProjectService

        project = ProjectService.get_project(str(grant.scope_id))
        enterprise_id = str(project.get("enterprise_id")) if project and project.get("enterprise_id") else None
        tenant_id = EnterpriseService.get_enterprise_tenant_id(enterprise_id) if enterprise_id else None
        if not tenant_trial_accessible(tenant_id):
            continue
        project_ids.add(str(grant.scope_id))
    return sorted(project_ids)


def list_accessible_enterprise_ids(
    user_or_id: Union[UserDB, str],
    *,
    required_roles: Optional[set[UserRole]] = None,
    include_project_scope: bool = False,
    access_grants: Optional[Iterable[AccessGrantDB]] = None,
) -> List[str]:
    from brainrh.services.enterprise_service import EnterpriseService
    from brainrh.services.project_service import ProjectService

    enterprise_ids: set[str] = set()
    user_id = _normalize_user_id(user_or_id)

    for membership in list_memberships_for_user(user_id):
        if required_roles and not user_roles_satisfy([membership.role], required_roles):
            continue
        enterprise_ids.add(str(membership.enterprise_id))

    resolved_access_grants = (
        list_access_grants_for_user(user_id)
        if access_grants is None
        else access_grants
    )
    for grant in resolved_access_grants:
        if required_roles and not user_roles_satisfy([grant.role], required_roles):
            continue

        if grant.scope_kind == AccessScopeKind.enterprise:
            enterprise_ids.add(str(grant.scope_id))
            continue

        if grant.scope_kind == AccessScopeKind.client:
            for enterprise in EnterpriseService.list_enterprises_by_tenant(str(grant.scope_id)):
                enterprise_ids.add(str(enterprise["id"]))
            continue

        if include_project_scope and grant.scope_kind == AccessScopeKind.project:
            project = ProjectService.get_project(str(grant.scope_id))
            if project and project.get("enterprise_id"):
                enterprise_ids.add(str(project["enterprise_id"]))

    return sorted(
        enterprise_id
        for enterprise_id in enterprise_ids
        if tenant_trial_accessible(EnterpriseService.get_enterprise_tenant_id(enterprise_id))
    )


def resolve_access_context_for_user(
    user: UserDB,
    *,
    enterprise_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> TenantContext:
    from brainrh.services.enterprise_service import EnterpriseService
    from brainrh.services.project_service import ProjectService

    scope_kind = AccessScopeKind.project if project_id else AccessScopeKind.enterprise
    resolved_project_id = str(project_id) if project_id else None
    resolved_enterprise_id = str(enterprise_id) if enterprise_id else None

    if resolved_project_id:
        project = ProjectService.get_project(resolved_project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Projet {resolved_project_id} introuvable",
            )
        project_enterprise_id = project.get("enterprise_id")
        if not project_enterprise_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Projet {resolved_project_id} sans enterprise_id.",
            )
        resolved_enterprise_id = str(project_enterprise_id)

    if not resolved_enterprise_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enterprise_id ou project_id requis.",
        )

    tenant_id = EnterpriseService.get_enterprise_tenant_id(resolved_enterprise_id)

    if user.role == UserRole.platform_admin:
        return TenantContext(
            user_id=str(user.id),
            tenant_id=tenant_id,
            enterprise_id=resolved_enterprise_id,
            project_id=resolved_project_id,
            role=UserRole.platform_admin,
            roles=[UserRole.platform_admin],
            scope_kind=scope_kind,
            scopes=["*"],
        )

    require_tenant_trial_access(tenant_id)

    effective_roles: set[UserRole] = set()
    effective_scopes: set[str] = set()

    membership = get_membership_for_user(str(user.id), resolved_enterprise_id)
    if membership:
        effective_roles.add(UserRole(membership.role))
        effective_scopes.update(parse_scopes(membership.scopes_json))

    for grant in list_access_grants_for_user(str(user.id)):
        if _grant_applies_to_target(
            grant,
            tenant_id=tenant_id,
            enterprise_id=resolved_enterprise_id,
            project_id=resolved_project_id,
        ):
            effective_roles.add(UserRole(grant.role))

    if not effective_roles:
        target_scope = resolved_project_id or resolved_enterprise_id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Aucun accès actif pour le scope {target_scope}.",
        )

    ordered_roles = _sorted_roles(effective_roles)
    return TenantContext(
        user_id=str(user.id),
        tenant_id=tenant_id,
        enterprise_id=resolved_enterprise_id,
        project_id=resolved_project_id,
        role=_primary_role(ordered_roles),
        roles=ordered_roles,
        scope_kind=scope_kind,
        scopes=sorted(effective_scopes),
    )
