"""
Admin User Service — ADMIN-FIX-001

Règles strictes:
- platform_admin → rôle global sur UserDB.role
- client_admin → AccessGrantDB scope client/tenant
- enterprise_admin / recruiter / viewer → rôles EXCLUSIVEMENT de MembershipDB
- Un enterprise_admin peut avoir UserDB.role = viewer (rôle global minimal)
- platform_admin ne doit JAMAIS être attribué comme rôle de membership
- enterprise_id="platform" est interdit

Contrat de réponse: AdminUserResponse (distinct de UserResponse)
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Literal, Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from pydantic import BaseModel

from brainrh.database import get_session_direct
from brainrh.models.audit_log import AuditLogDB
from brainrh.models.auth import (
    AccessGrantDB,
    AccessScopeKind,
    InvitationScopeKind,
    InvitationStatus,
    MembershipDB,
    TenantDB,
    UserDB,
    UserInvitationDB,
    UserRole,
)
from brainrh.services.auth_service import (
    list_accessible_enterprise_ids,
    revoke_user_tokens,
    tenant_trial_metadata,
)
from brainrh.services.invitation_service import GLOBAL_SCOPE_ID, InvitationOutcome, InvitationService
from brainrh.settings import get_invitation_resend_cooldown_seconds


# ---------------------------------------------------------------------------
# Contrat de réponse dédié admin (distinct de UserResponse)
# ---------------------------------------------------------------------------

class AdminUserResponse(BaseModel):
    id: str
    email: str
    global_role: str
    membership_role: Optional[str] = None
    enterprise_id: Optional[str] = None
    membership_id: Optional[str] = None
    access_role: Optional[str] = None
    access_scope_kind: Optional[str] = None
    access_scope_id: Optional[str] = None
    is_access_grant_active: Optional[bool] = None
    is_user_active: bool
    is_membership_active: Optional[bool] = None
    invitation_id: Optional[str] = None
    invitation_status: Optional[str] = None
    invitation_expires_at: Optional[datetime] = None
    invitation_retry_after_seconds: Optional[int] = None
    invitation_first_name: Optional[str] = None
    invitation_last_name: Optional[str] = None


class AdminClientResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    trial_duration_days: Optional[int] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    trial_status: Optional[Literal["pending", "active", "expired"]] = None


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# enterprise_id réservé interdit
FORBIDDEN_ENTERPRISE_IDS = {"platform"}
ADMIN_USER_SCOPE_GLOBAL = "global"
ADMIN_USER_SCOPE_MEMBERSHIP = "membership"
ALLOWED_ADMIN_USER_SCOPES = {ADMIN_USER_SCOPE_GLOBAL, ADMIN_USER_SCOPE_MEMBERSHIP}
MEMBERSHIP_ROLES = {UserRole.enterprise_admin, UserRole.recruiter, UserRole.viewer}


# ---------------------------------------------------------------------------
# Helpers de validation
# ---------------------------------------------------------------------------

def _validate_membership_role(role: UserRole) -> None:
    """Lève une 400 si le rôle ne peut pas être stocké comme membership enterprise."""
    if role not in MEMBERSHIP_ROLES:
        allowed = ", ".join(sorted(role.value for role in MEMBERSHIP_ROLES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le rôle {role.value} ne peut pas être attribué via un membership. Valeurs valides: {allowed}.",
        )


def _validate_enterprise_id(enterprise_id: str) -> None:
    """Lève une 400 si enterprise_id est une valeur réservée interdite."""
    if enterprise_id in FORBIDDEN_ENTERPRISE_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"enterprise_id '{enterprise_id}' est réservé et interdit.",
        )


def _validate_admin_user_scope(admin_user_scope: Optional[str]) -> Optional[str]:
    """Valide le scope explicite des mutations admin user si fourni."""
    if admin_user_scope is None:
        return None

    normalized_scope = admin_user_scope.strip().lower()
    if normalized_scope not in ALLOWED_ADMIN_USER_SCOPES:
        allowed = ", ".join(sorted(ALLOWED_ADMIN_USER_SCOPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scope admin user inconnu: '{admin_user_scope}'. Valeurs valides: {allowed}.",
        )
    return normalized_scope


# ---------------------------------------------------------------------------
# Helpers de rôle (séparation global vs membership)
# ---------------------------------------------------------------------------

def _is_platform_admin(user: UserDB) -> bool:
    """Retourne True si l'user est un platform_admin (rôle global UserDB.role)."""
    return user.role == UserRole.platform_admin


def _list_admin_enterprise_ids(user: UserDB) -> List[str]:
    """Retourne les enterprises où l'user a un pouvoir admin effectif."""
    return list_accessible_enterprise_ids(user, required_roles={UserRole.enterprise_admin})


def _has_enterprise_admin_access(user: UserDB) -> bool:
    """Retourne True si l'user a au moins un accès admin enterprise-compatible."""
    return len(_list_admin_enterprise_ids(user)) > 0


# ---------------------------------------------------------------------------
# Résolution de l'enterprise depuis le contexte
# ---------------------------------------------------------------------------

def resolve_enterprise_for_admin(user: UserDB, enterprise_id: Optional[str]) -> str:
    """Résout l'enterprise_id pour un enterprise_admin.

    - platform_admin: enterprise_id obligatoire, retourné tel quel.
    - enterprise_admin: résolution par membership actif.
      - Si enterprise_id fourni: vérifie que l'user y est admin actif.
      - Sinon: résolution automatique si exactement un membership admin actif.
      - Si plusieurs: erreur claire exigeant X-Enterprise-ID.
    """
    if _is_platform_admin(user):
        if not enterprise_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="platform_admin doit fournir X-Enterprise-ID pour les opérations entreprise.",
            )
        _validate_enterprise_id(enterprise_id)
        return enterprise_id

    # Résolution admin via grants/memberships compatibles
    admin_enterprise_ids = _list_admin_enterprise_ids(user)

    if enterprise_id:
        _validate_enterprise_id(enterprise_id)
        has_access = enterprise_id in admin_enterprise_ids
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Aucun accès admin actif sur l'entreprise {enterprise_id}.",
            )
        return enterprise_id

    # Résolution automatique
    if len(admin_enterprise_ids) == 1:
        return admin_enterprise_ids[0]

    if len(admin_enterprise_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Plusieurs accès admin enterprise compatibles détectés. "
                "Fournissez X-Enterprise-ID pour préciser l'entreprise cible."
            ),
        )

    # Aucun membership admin actif
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Aucun accès admin enterprise compatible trouvé pour cet utilisateur.",
    )


# ---------------------------------------------------------------------------
# Service principal
# ---------------------------------------------------------------------------

class AdminUserService:
    def __init__(self) -> None:
        self._invitation_service = InvitationService()

    @staticmethod
    def _require_platform_admin(actor: UserDB) -> None:
        if not _is_platform_admin(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Action réservée au platform_admin.",
            )

    def list_clients(self, actor: UserDB) -> List[AdminClientResponse]:
        """Liste le registre des clients, réservé aux administrateurs plateforme."""
        self._require_platform_admin(actor)
        with get_session_direct() as session:
            tenants = session.exec(
                select(TenantDB).order_by(
                    func.lower(TenantDB.name),
                    TenantDB.created_at,
                    TenantDB.id,
                )
            ).all()
            return [
                self._client_response(tenant)
                for tenant in tenants
            ]

    @staticmethod
    def _client_response(tenant: TenantDB) -> AdminClientResponse:
        return AdminClientResponse(
            id=str(tenant.id),
            name=tenant.name,
            created_at=tenant.created_at,
            **tenant_trial_metadata(tenant),
        )

    def create_client(
        self,
        actor: UserDB,
        name: str,
        trial_duration_days: Optional[int] = None,
    ) -> AdminClientResponse:
        """Crée un client sans inviter de compte administrateur."""
        self._require_platform_admin(actor)
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le nom du client est requis.",
            )
        if trial_duration_days is not None and not 1 <= trial_duration_days <= 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trial_duration_days doit être compris entre 1 et 365.",
            )

        with get_session_direct() as session:
            duplicate = session.exec(
                select(TenantDB).where(
                    func.lower(func.trim(TenantDB.name)) == normalized_name.lower()
                )
            ).first()
            if duplicate is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Un client portant ce nom existe déjà.",
                )

            tenant = TenantDB(
                id=str(uuid.uuid4()),
                name=normalized_name,
                trial_duration_days=trial_duration_days,
            )
            session.add(tenant)
            session.add(
                AuditLogDB(
                    enterprise_id="SYSTEM",
                    actor_user_id=str(actor.id),
                    action="client.created",
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                    metadata_json=json.dumps(
                        {
                            "name": normalized_name,
                            "trial_duration_days": trial_duration_days,
                        }
                    ),
                )
            )
            session.commit()
            session.refresh(tenant)
            return self._client_response(tenant)

    def extend_client_trial(
        self,
        *,
        actor: UserDB,
        tenant_id: str,
        extend_days: int,
    ) -> AdminClientResponse:
        self._require_platform_admin(actor)
        if not 1 <= extend_days <= 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="extend_days doit être compris entre 1 et 365.",
            )

        now = datetime.now(timezone.utc)
        with get_session_direct() as session:
            tenant = session.exec(
                select(TenantDB).where(TenantDB.id == tenant_id).with_for_update()
            ).first()
            if tenant is None:
                raise HTTPException(status_code=404, detail="Client/tenant introuvable.")
            if tenant.trial_duration_days is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ce client ne possède pas d'essai à prolonger.",
                )

            previous_duration = tenant.trial_duration_days
            previous_expires_at = tenant.trial_expires_at
            if tenant.trial_started_at is None:
                if tenant.trial_duration_days + extend_days > 365:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La durée totale de l'essai pending ne peut pas dépasser 365 jours.",
                    )
                tenant.trial_duration_days += extend_days
            else:
                if tenant.trial_expires_at is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La fenêtre d'essai du client est incohérente.",
                    )
                expires_at = tenant.trial_expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                else:
                    expires_at = expires_at.astimezone(timezone.utc)
                tenant.trial_expires_at = max(now, expires_at) + timedelta(days=extend_days)

            session.add(tenant)
            session.add(
                AuditLogDB(
                    enterprise_id="SYSTEM",
                    actor_user_id=str(actor.id),
                    action="client.trial.extended",
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                    metadata_json=json.dumps(
                        {
                            "extend_days": extend_days,
                            "previous_duration_days": previous_duration,
                            "trial_duration_days": tenant.trial_duration_days,
                            "previous_expires_at": previous_expires_at.isoformat()
                            if previous_expires_at
                            else None,
                            "trial_expires_at": tenant.trial_expires_at.isoformat()
                            if tenant.trial_expires_at
                            else None,
                        }
                    ),
                )
            )
            session.commit()
            session.refresh(tenant)
            return self._client_response(tenant)

    def _first_active_access_grant(self, session, user_id: str) -> Optional[AccessGrantDB]:
        return session.exec(
            select(AccessGrantDB).where(
                AccessGrantDB.user_id == user_id,
                AccessGrantDB.is_active == True,  # noqa: E712
            )
            .order_by(AccessGrantDB.created_at, AccessGrantDB.id)
        ).first()

    def _first_active_memberships_by_user(
        self,
        session,
        user_ids: Iterable[str],
    ) -> Dict[str, MembershipDB]:
        normalized_user_ids = list(dict.fromkeys(str(user_id) for user_id in user_ids))
        if not normalized_user_ids:
            return {}

        memberships = session.exec(
            select(MembershipDB).where(
                MembershipDB.user_id.in_(normalized_user_ids),  # type: ignore[union-attr]
            )
            .order_by(
                MembershipDB.user_id,
                MembershipDB.is_active.desc(),
                MembershipDB.created_at,
                MembershipDB.id,
            )
        ).all()
        first_by_user: Dict[str, MembershipDB] = {}
        for membership in memberships:
            first_by_user.setdefault(str(membership.user_id), membership)
        return first_by_user

    def _first_active_access_grants_by_user(
        self,
        session,
        user_ids: Iterable[str],
    ) -> Dict[str, AccessGrantDB]:
        normalized_user_ids = list(dict.fromkeys(str(user_id) for user_id in user_ids))
        if not normalized_user_ids:
            return {}

        access_grants = session.exec(
            select(AccessGrantDB).where(
                AccessGrantDB.user_id.in_(normalized_user_ids),  # type: ignore[union-attr]
            )
            .order_by(
                AccessGrantDB.user_id,
                AccessGrantDB.is_active.desc(),
                AccessGrantDB.created_at,
                AccessGrantDB.id,
            )
        ).all()
        first_by_user: Dict[str, AccessGrantDB] = {}
        for access_grant in access_grants:
            first_by_user.setdefault(str(access_grant.user_id), access_grant)
        return first_by_user

    def _invitations_by_scope(
        self,
        session,
        user_ids: Iterable[str],
    ) -> Dict[tuple[str, str, str], UserInvitationDB]:
        normalized_user_ids = list(dict.fromkeys(str(user_id) for user_id in user_ids))
        if not normalized_user_ids:
            return {}
        invitations = session.exec(
            select(UserInvitationDB).where(
                UserInvitationDB.user_id.in_(normalized_user_ids)  # type: ignore[union-attr]
            )
        ).all()
        return {
            (
                str(invitation.user_id),
                invitation.scope_kind.value,
                str(invitation.scope_id),
            ): invitation
            for invitation in invitations
        }

    @staticmethod
    def _response_invitation(
        invitations_by_scope: Dict[tuple[str, str, str], UserInvitationDB],
        user: UserDB,
        membership: Optional[MembershipDB],
        access_grant: Optional[AccessGrantDB],
    ) -> Optional[UserInvitationDB]:
        user_id = str(user.id)
        if membership is not None:
            return invitations_by_scope.get(
                (user_id, InvitationScopeKind.enterprise.value, str(membership.enterprise_id))
            )
        if access_grant is not None and access_grant.scope_kind == AccessScopeKind.client:
            return invitations_by_scope.get(
                (user_id, InvitationScopeKind.client.value, str(access_grant.scope_id))
            )
        return invitations_by_scope.get(
            (user_id, InvitationScopeKind.global_scope.value, GLOBAL_SCOPE_ID)
        )

    def _resolve_client_tenant_id(
        self,
        actor: UserDB,
        *,
        tenant_id: Optional[str],
        enterprise_id: Optional[str],
    ) -> str:
        if not _is_platform_admin(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un platform_admin peut attribuer le rôle client_admin.",
            )

        resolved_tenant_id = (tenant_id or "").strip()
        if not resolved_tenant_id and enterprise_id:
            from brainrh.services.enterprise_service import EnterpriseService

            resolved_tenant_id = EnterpriseService.get_enterprise_tenant_id(enterprise_id) or ""

        if not resolved_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id requis pour attribuer le rôle client_admin.",
            )

        with get_session_direct() as session:
            if session.get(TenantDB, resolved_tenant_id) is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Client/tenant {resolved_tenant_id} introuvable.",
                )

        return resolved_tenant_id

    @staticmethod
    def _has_unaccepted_enterprise_invitation(
        session,
        *,
        user_id: str,
        enterprise_id: str,
    ) -> bool:
        invitation = session.exec(
            select(UserInvitationDB).where(
                UserInvitationDB.user_id == user_id,
                UserInvitationDB.scope_kind == InvitationScopeKind.enterprise,
                UserInvitationDB.scope_id == enterprise_id,
                UserInvitationDB.status.notin_(  # type: ignore[union-attr]
                    [InvitationStatus.accepted, InvitationStatus.revoked]
                ),
            )
        ).first()
        return invitation is not None

    # ------------------------------------------------------------------
    # List users
    # ------------------------------------------------------------------

    def list_users(
        self,
        actor: UserDB,
        enterprise_id: Optional[str] = None,
    ) -> List[AdminUserResponse]:
        """Liste les utilisateurs selon le rôle de l'acteur.

        - platform_admin sans enterprise_id → tous les users
        - platform_admin avec enterprise_id → filtré par enterprise
        - enterprise_admin (via membership) → uniquement son enterprise
        - recruiter / viewer → 403
        """
        if _is_platform_admin(actor):
            with get_session_direct() as session:
                if enterprise_id:
                    _validate_enterprise_id(enterprise_id)
                    return self._list_by_enterprise(session, enterprise_id)
                else:
                    return self._list_all(session)

        elif _has_enterprise_admin_access(actor):
            resolved_eid = resolve_enterprise_for_admin(actor, enterprise_id)
            with get_session_direct() as session:
                return self._list_by_enterprise(session, resolved_eid)

        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé : rôle insuffisant pour accéder à l'administration.",
            )

    def _list_all(self, session) -> List[AdminUserResponse]:
        """Liste tous les users avec leur premier membership actif (ou None)."""
        users = session.exec(select(UserDB)).all()
        user_ids = [str(user.id) for user in users]
        memberships_by_user = self._first_active_memberships_by_user(session, user_ids)
        access_grants_by_user = self._first_active_access_grants_by_user(session, user_ids)
        invitations_by_scope = self._invitations_by_scope(session, user_ids)
        return [
            self._build_response(
                user,
                memberships_by_user.get(str(user.id)),
                access_grants_by_user.get(str(user.id)),
                self._response_invitation(
                    invitations_by_scope,
                    user,
                    memberships_by_user.get(str(user.id)),
                    access_grants_by_user.get(str(user.id)),
                ),
            )
            for user in users
        ]

    def _list_by_enterprise(self, session, enterprise_id: str) -> List[AdminUserResponse]:
        """Liste les users membres d'une enterprise."""
        rows = session.exec(
            select(UserDB, MembershipDB)
            .join(MembershipDB, UserDB.id == MembershipDB.user_id)  # type: ignore[arg-type]
            .where(MembershipDB.enterprise_id == enterprise_id)
        ).all()
        access_grants_by_user = self._first_active_access_grants_by_user(
            session,
            (str(user.id) for user, _membership in rows),
        )
        invitations_by_scope = self._invitations_by_scope(
            session,
            (str(user.id) for user, _membership in rows),
        )
        return [
            self._build_response(
                user,
                membership,
                access_grants_by_user.get(str(user.id)),
                self._response_invitation(
                    invitations_by_scope,
                    user,
                    membership,
                    access_grants_by_user.get(str(user.id)),
                ),
            )
            for user, membership in rows
        ]

    # ------------------------------------------------------------------
    # Invite user
    # ------------------------------------------------------------------

    def invite_user(
        self,
        actor: UserDB,
        email: str,
        role: UserRole,
        enterprise_id: Optional[str] = None,
        language: str = "en",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> AdminUserResponse:
        """Invite un utilisateur dans une entreprise.

        - platform_admin doit fournir X-Enterprise-ID
        - enterprise_admin peut inviter dans son entreprise uniquement
        - Rôle platform_admin interdit
        - enterprise_id 'platform' interdit
        """
        if not (_is_platform_admin(actor) or _has_enterprise_admin_access(actor)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé.",
            )

        _validate_membership_role(role)

        resolved_eid = resolve_enterprise_for_admin(actor, enterprise_id)
        _validate_enterprise_id(resolved_eid)

        outcome = self._invitation_service.create_or_resend(
            actor=actor,
            email=email,
            role=role,
            scope_kind=InvitationScopeKind.enterprise,
            scope_id=resolved_eid,
            language=language,
            first_name=first_name,
            last_name=last_name,
        )
        return self._response_from_outcome(outcome)

    def invite_platform_admin(
        self,
        actor: UserDB,
        email: str,
        language: str = "en",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> AdminUserResponse:
        if not _is_platform_admin(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un platform_admin peut créer un platform_admin.",
            )

        outcome = self._invitation_service.create_or_resend(
            actor=actor,
            email=email,
            role=UserRole.platform_admin,
            scope_kind=InvitationScopeKind.global_scope,
            scope_id=GLOBAL_SCOPE_ID,
            language=language,
            first_name=first_name,
            last_name=last_name,
        )
        return self._response_from_outcome(outcome)

    def invite_client_admin(
        self,
        actor: UserDB,
        email: str,
        *,
        tenant_id: Optional[str] = None,
        enterprise_id: Optional[str] = None,
        language: str = "en",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> AdminUserResponse:
        resolved_tenant_id = self._resolve_client_tenant_id(
            actor,
            tenant_id=tenant_id,
            enterprise_id=enterprise_id,
        )

        outcome = self._invitation_service.create_or_resend(
            actor=actor,
            email=email,
            role=UserRole.client_admin,
            scope_kind=InvitationScopeKind.client,
            scope_id=resolved_tenant_id,
            language=language,
            first_name=first_name,
            last_name=last_name,
        )
        return self._response_from_outcome(outcome)

    def resend_invitation(
        self,
        *,
        actor: UserDB,
        invitation_id: str,
        language: Optional[str] = None,
    ) -> AdminUserResponse:
        with get_session_direct() as session:
            invitation = session.get(UserInvitationDB, invitation_id)
            if invitation is None:
                raise HTTPException(status_code=404, detail="Invitation introuvable.")
            if not _is_platform_admin(actor):
                allowed_enterprises = set(_list_admin_enterprise_ids(actor))
                if (
                    invitation.scope_kind != InvitationScopeKind.enterprise
                    or invitation.scope_id not in allowed_enterprises
                ):
                    # Ne pas reveler qu'une invitation d'un autre tenant existe.
                    raise HTTPException(status_code=404, detail="Invitation introuvable.")

        outcome = self._invitation_service.resend(
            actor=actor,
            invitation_id=invitation_id,
            language=language,
        )
        return self._response_from_outcome(outcome)

    def _response_from_outcome(self, outcome: InvitationOutcome) -> AdminUserResponse:
        with get_session_direct() as session:
            user = session.get(UserDB, outcome.user_id)
            if user is None:
                raise HTTPException(status_code=500, detail="Compte invite introuvable.")
            membership = (
                session.get(MembershipDB, outcome.membership_id)
                if outcome.membership_id
                else None
            )
            access_grant = (
                session.get(AccessGrantDB, outcome.access_grant_id)
                if outcome.access_grant_id
                else self._first_active_access_grant(session, str(user.id))
            )
            invitation = session.get(UserInvitationDB, outcome.invitation_id)
            return self._build_response(user, membership, access_grant, invitation)

    # ------------------------------------------------------------------
    # Update membership role
    # ------------------------------------------------------------------

    def update_membership_role(
        self,
        actor: UserDB,
        user_id: str,
        new_role: UserRole,
        enterprise_id: Optional[str] = None,
    ) -> AdminUserResponse:
        """Change le rôle de membership d'un utilisateur.

        - platform_admin interdit comme rôle cible
        """
        if not (_is_platform_admin(actor) or _has_enterprise_admin_access(actor)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé.",
            )

        _validate_membership_role(new_role)
        resolved_eid = resolve_enterprise_for_admin(actor, enterprise_id)

        with get_session_direct() as session:
            user = session.exec(
                select(UserDB).where(UserDB.id == user_id)
            ).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable.")

            membership = session.exec(
                select(MembershipDB).where(
                    MembershipDB.user_id == user_id,
                    MembershipDB.enterprise_id == resolved_eid,
                )
            ).first()

            if not membership:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Membership introuvable pour cet utilisateur.",
                )

            if self._has_unaccepted_enterprise_invitation(
                session,
                user_id=user_id,
                enterprise_id=resolved_eid,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Le role de cette invitation est fige. "
                        "Renvoyez l'invitation avec le role souhaite."
                    ),
                )

            membership.role = new_role
            session.add(membership)
            session.commit()
            session.refresh(membership)
            session.refresh(user)
            return self._build_response(user, membership)

    # ------------------------------------------------------------------
    # Toggle membership status (désactivation)
    # ------------------------------------------------------------------

    def toggle_membership_status(
        self,
        actor: UserDB,
        user_id: str,
        is_active: bool,
        enterprise_id: Optional[str] = None,
        admin_user_scope: Optional[str] = None,
    ) -> AdminUserResponse:
        """Active ou désactive un membership.

        Règle fondamentale:
        - Désactivation membership ne JAMAIS toucher UserDB.is_active.
        - Exception: platform_admin SANS enterprise_id et X-Admin-User-Scope=global
          → désactivation globale UserDB.is_active.
        """
        if not (_is_platform_admin(actor) or _has_enterprise_admin_access(actor)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé.",
            )

        resolved_admin_user_scope = _validate_admin_user_scope(admin_user_scope)
        if enterprise_id and resolved_admin_user_scope == ADMIN_USER_SCOPE_GLOBAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Admin-User-Scope=global ne peut pas être combiné avec X-Enterprise-ID.",
            )
        if resolved_admin_user_scope == ADMIN_USER_SCOPE_GLOBAL and not _is_platform_admin(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un platform_admin peut modifier le statut global d'un utilisateur.",
            )

        with get_session_direct() as session:
            user = session.exec(
                select(UserDB).where(UserDB.id == user_id)
            ).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable.")

            if _is_platform_admin(actor) and not enterprise_id:
                if resolved_admin_user_scope != ADMIN_USER_SCOPE_GLOBAL:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Scope global explicite requis pour modifier UserDB.is_active. "
                            "Envoyez X-Admin-User-Scope: global ou fournissez X-Enterprise-ID "
                            "pour modifier un membership."
                        ),
                    )
                # Désactivation globale du user (platform_admin sans enterprise)
                if is_active and not user.hashed_password:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Ce compte doit d'abord accepter son invitation.",
                    )
                user.is_active = is_active
                session.add(user)
                if is_active:
                    session.commit()
                else:
                    revoke_user_tokens(
                        session,
                        str(user.id),
                        reason="user_deactivated",
                        actor_user_id=str(actor.id),
                    )
                session.refresh(user)
                return self._build_response(user, None)

            # enterprise_admin ou platform_admin+enterprise_id: désactivation membership seulement
            if _has_enterprise_admin_access(actor) and not _is_platform_admin(actor):
                resolved_eid = resolve_enterprise_for_admin(actor, enterprise_id)
            elif enterprise_id:
                _validate_enterprise_id(enterprise_id)
                resolved_eid = enterprise_id
            else:
                resolved_eid = enterprise_id  # None pour platform_admin (cas traité ci-dessus)

            membership = session.exec(
                select(MembershipDB).where(
                    MembershipDB.user_id == user_id,
                    MembershipDB.enterprise_id == resolved_eid,
                )
            ).first()

            if not membership:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Membership introuvable.",
                )

            if is_active and self._has_unaccepted_enterprise_invitation(
                session,
                user_id=user_id,
                enterprise_id=str(resolved_eid),
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cet acces doit d'abord etre accepte depuis l'invitation.",
                )

            # Désactivation membership uniquement — UserDB.is_active non touché
            membership.is_active = is_active
            session.add(membership)
            session.commit()
            session.refresh(membership)
            session.refresh(user)
            return self._build_response(user, membership)

    # ------------------------------------------------------------------
    # Helper interne
    # ------------------------------------------------------------------

    def _build_response(
        self,
        user: UserDB,
        membership: Optional[MembershipDB],
        access_grant: Optional[AccessGrantDB] = None,
        invitation: Optional[UserInvitationDB] = None,
    ) -> AdminUserResponse:
        return AdminUserResponse(
            id=str(user.id),
            email=str(user.email),
            global_role=str(user.role.value if hasattr(user.role, "value") else user.role),
            membership_role=(
                str(membership.role.value if hasattr(membership.role, "value") else membership.role)
                if membership else None
            ),
            enterprise_id=str(membership.enterprise_id) if membership else None,
            membership_id=str(membership.id) if membership else None,
            access_role=(
                str(access_grant.role.value if hasattr(access_grant.role, "value") else access_grant.role)
                if access_grant else None
            ),
            access_scope_kind=(
                str(access_grant.scope_kind.value if hasattr(access_grant.scope_kind, "value") else access_grant.scope_kind)
                if access_grant else None
            ),
            access_scope_id=str(access_grant.scope_id) if access_grant else None,
            is_access_grant_active=bool(access_grant.is_active) if access_grant else None,
            is_user_active=bool(user.is_active),
            is_membership_active=bool(membership.is_active) if membership else None,
            invitation_id=str(invitation.id) if invitation else None,
            invitation_status=(self._display_invitation_status(invitation) if invitation else None),
            invitation_expires_at=invitation.expires_at if invitation else None,
            invitation_retry_after_seconds=(
                max(
                    0,
                    self._invitation_service_retry_after(invitation),
                )
                if invitation
                else None
            ),
            invitation_first_name=invitation.first_name if invitation else None,
            invitation_last_name=invitation.last_name if invitation else None,
        )

    @staticmethod
    def _invitation_service_retry_after(invitation: UserInvitationDB) -> int:
        if invitation.last_attempt_at is None:
            return 0

        last_attempt = invitation.last_attempt_at
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_attempt).total_seconds()
        return get_invitation_resend_cooldown_seconds() - int(elapsed)

    @staticmethod
    def _display_invitation_status(invitation: UserInvitationDB) -> str:
        expires_at = invitation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if invitation.status.value == "sent" and expires_at <= datetime.now(timezone.utc):
            return "expired"
        return invitation.status.value
