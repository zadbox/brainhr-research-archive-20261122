"""Cycle de vie persistant et securise des invitations utilisateur."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets
from typing import Optional
import unicodedata
from urllib.parse import quote, urlparse

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

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
    GoogleIdentityDB,
)
from brainrh.models.enterprise import EnterpriseDB
from brainrh.services.auth_service import get_password_hash, tenant_trial_metadata, tenant_trial_status
from brainrh.services.email_sender import (
    EmailConfigurationError,
    EmailDeliveryError,
    InvitationEmail,
    get_email_sender,
    validate_mailbox,
)
from brainrh.settings import (
    get_frontend_url,
    get_invitation_resend_cooldown_seconds,
    get_invitation_ttl_minutes,
    is_production,
)


TOKEN_BYTES = 32
GLOBAL_SCOPE_ID = "platform"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvitationOutcome:
    invitation_id: str
    user_id: str
    membership_id: Optional[str]
    access_grant_id: Optional[str]
    status: InvitationStatus
    expires_at: datetime
    retry_after_seconds: int


@dataclass(frozen=True)
class InvitationInspection:
    status: str
    requires_password: bool = False
    expires_at: Optional[datetime] = None
    tenant_name: Optional[str] = None
    trial_duration_days: Optional[int] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    trial_status: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    try:
        return validate_mailbox(email.strip().lower(), setting_name="email")
    except EmailConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adresse email invalide.",
        ) from exc


def _validate_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in {"en", "fr"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La langue d'invitation doit valoir en ou fr.",
        )
    return normalized


def _normalize_person_name(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if any(unicodedata.category(character) in {"Cc", "Zl", "Zp"} for character in value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} contient un caractere de controle interdit.",
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} ne peut pas etre vide.",
        )
    if len(normalized) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} ne peut pas depasser 100 caracteres.",
        )
    return normalized


def _build_activation_url(token: str) -> str:
    base_url = get_frontend_url()
    if not base_url:
        raise EmailConfigurationError("FRONTEND_URL est requis pour les invitations.")

    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise EmailConfigurationError("FRONTEND_URL doit etre une URL publique absolue sans identifiants.")
    if is_production() and parsed.scheme != "https":
        raise EmailConfigurationError("FRONTEND_URL doit utiliser HTTPS en production.")

    return f"{base_url.rstrip('/')}/activate-invitation#token={quote(token, safe='')}"


def _retry_after(invitation: UserInvitationDB, now: datetime) -> int:
    if invitation.last_attempt_at is None:
        return 0
    elapsed = (now - _as_utc(invitation.last_attempt_at)).total_seconds()
    return max(0, get_invitation_resend_cooldown_seconds() - int(elapsed))


def _audit(
    session,
    *,
    invitation: UserInvitationDB,
    action: str,
    actor_user_id: Optional[str],
    metadata: Optional[dict[str, object]] = None,
) -> None:
    safe_metadata = {
        "scope_kind": invitation.scope_kind.value,
        "scope_id": invitation.scope_id,
        "role": invitation.role.value,
        "status": invitation.status.value,
        "send_attempts": invitation.send_attempts,
    }
    if metadata:
        safe_metadata.update(metadata)
    session.add(
        AuditLogDB(
            enterprise_id=(
                invitation.scope_id
                if invitation.scope_kind == InvitationScopeKind.enterprise
                else "SYSTEM"
            ),
            actor_user_id=actor_user_id,
            action=action,
            resource_type="user_invitation",
            resource_id=str(invitation.id),
            metadata_json=json.dumps(safe_metadata),
        )
    )


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 12 caracteres.",
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe est trop long.",
        )


def _invitation_trial_metadata(session, invitation: UserInvitationDB) -> dict:
    tenant_id: Optional[str] = None
    if invitation.scope_kind == InvitationScopeKind.client:
        tenant_id = invitation.scope_id
    elif invitation.scope_kind == InvitationScopeKind.enterprise:
        enterprise = session.get(EnterpriseDB, invitation.scope_id)
        tenant_id = str(enterprise.tenant_id) if enterprise and enterprise.tenant_id else None

    tenant = session.get(TenantDB, tenant_id) if tenant_id else None
    if tenant is None:
        return {
            "tenant_name": None,
            "trial_duration_days": None,
            "trial_started_at": None,
            "trial_expires_at": None,
            "trial_status": None,
        }
    return {"tenant_name": tenant.name, **tenant_trial_metadata(tenant)}


def _ensure_invitation_scope_available(
    session,
    *,
    scope_kind: InvitationScopeKind,
    scope_id: str,
) -> None:
    tenant: Optional[TenantDB] = None
    if scope_kind == InvitationScopeKind.client:
        tenant = session.get(TenantDB, scope_id)
    elif scope_kind == InvitationScopeKind.enterprise:
        enterprise = session.get(EnterpriseDB, scope_id)
        if enterprise and enterprise.tenant_id:
            tenant = session.get(TenantDB, str(enterprise.tenant_id))
    if tenant is not None and tenant_trial_status(tenant) == "expired":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CLIENT_TRIAL_EXPIRED",
                "message": "Prolongez l'essai client avant d'envoyer une invitation.",
            },
        )


class InvitationService:
    def create_or_resend(
        self,
        *,
        actor: UserDB,
        email: str,
        role: UserRole,
        scope_kind: InvitationScopeKind,
        scope_id: str,
        language: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> InvitationOutcome:
        normalized_email = _normalize_email(email)
        normalized_language = _validate_language(language)
        normalized_first_name = _normalize_person_name(first_name, field_name="first_name")
        normalized_last_name = _normalize_person_name(last_name, field_name="last_name")
        now = _now()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        digest = _token_digest(token)

        with get_session_direct() as session:
            _ensure_invitation_scope_available(
                session,
                scope_kind=scope_kind,
                scope_id=scope_id,
            )
            user = session.exec(
                select(UserDB).where(func.lower(UserDB.email) == normalized_email)
            ).first()
            user_was_existing = user is not None
            if user is None:
                user = UserDB(
                    email=normalized_email,
                    hashed_password=None,
                    role=UserRole.viewer,
                    is_active=False,
                )
                session.add(user)
                try:
                    session.flush()
                except IntegrityError as exc:
                    session.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Une invitation concurrente est deja en cours. Reessayez.",
                    ) from exc
            elif not user.is_active and (user.hashed_password is not None or session.get(GoogleIdentityDB, user.id)):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Ce compte existe mais il est desactive. Reactivez-le explicitement "
                        "avant de renvoyer une invitation."
                    ),
                )

            invitation = session.exec(
                select(UserInvitationDB)
                .where(
                    UserInvitationDB.user_id == str(user.id),
                    UserInvitationDB.scope_kind == scope_kind,
                    UserInvitationDB.scope_id == scope_id,
                )
                .with_for_update()
            ).first()
            if invitation is not None:
                retry_after = _retry_after(invitation, now)
                if retry_after > 0:
                    _audit(
                        session,
                        invitation=invitation,
                        action="user_invitation.resend_rate_limited",
                        actor_user_id=str(actor.id),
                        metadata={"retry_after_seconds": retry_after},
                    )
                    session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Une invitation a deja ete tentee recemment. Reessayez plus tard.",
                        headers={"Retry-After": str(retry_after)},
                    )

            membership, access_grant = self._prepare_assignment(
                session,
                user=user,
                role=role,
                scope_kind=scope_kind,
                scope_id=scope_id,
            )
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Une invitation concurrente est deja en cours. Reessayez.",
                ) from exc

            if invitation is not None:
                invitation.email = normalized_email
                if normalized_first_name is not None:
                    invitation.first_name = normalized_first_name
                if normalized_last_name is not None:
                    invitation.last_name = normalized_last_name
                invitation.role = role
                invitation.token_digest = digest
                invitation.status = InvitationStatus.pending_delivery
                invitation.language = normalized_language
                invitation.created_by_user_id = str(actor.id)
                invitation.membership_id = str(membership.id) if membership else None
                invitation.access_grant_id = str(access_grant.id) if access_grant else None
                invitation.user_was_existing = user_was_existing
                invitation.send_attempts += 1
                invitation.last_attempt_at = now
                invitation.expires_at = now + timedelta(minutes=get_invitation_ttl_minutes())
                invitation.accepted_at = None
                invitation.failed_at = None
                invitation.failure_code = None
                invitation.provider_message_id = None
                invitation.updated_at = now
            else:
                invitation = UserInvitationDB(
                    user_id=str(user.id),
                    email=normalized_email,
                    first_name=normalized_first_name,
                    last_name=normalized_last_name,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    role=role,
                    token_digest=digest,
                    status=InvitationStatus.pending_delivery,
                    language=normalized_language,
                    created_by_user_id=str(actor.id),
                    membership_id=str(membership.id) if membership else None,
                    access_grant_id=str(access_grant.id) if access_grant else None,
                    user_was_existing=user_was_existing,
                    send_attempts=1,
                    last_attempt_at=now,
                    expires_at=now + timedelta(minutes=get_invitation_ttl_minutes()),
                    created_at=now,
                    updated_at=now,
                )
            session.add(invitation)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Une invitation concurrente est deja en cours. Reessayez.",
                ) from exc
            session.refresh(invitation)

            invitation_id = str(invitation.id)
            requires_password = user.hashed_password is None

        return self._deliver(
            invitation_id=invitation_id,
            expected_digest=digest,
            token=token,
            requires_password=requires_password,
            actor_user_id=str(actor.id),
        )

    def resend(
        self,
        *,
        actor: UserDB,
        invitation_id: str,
        language: Optional[str] = None,
    ) -> InvitationOutcome:
        now = _now()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        digest = _token_digest(token)

        with get_session_direct() as session:
            invitation = session.exec(
                select(UserInvitationDB)
                .where(UserInvitationDB.id == invitation_id)
                .with_for_update()
            ).first()
            if invitation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
            _ensure_invitation_scope_available(
                session,
                scope_kind=invitation.scope_kind,
                scope_id=invitation.scope_id,
            )
            retry_after = _retry_after(invitation, now)
            if retry_after > 0:
                _audit(
                    session,
                    invitation=invitation,
                    action="user_invitation.resend_rate_limited",
                    actor_user_id=str(actor.id),
                    metadata={"retry_after_seconds": retry_after},
                )
                session.commit()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Cette invitation a deja ete envoyee recemment. Reessayez plus tard.",
                    headers={"Retry-After": str(retry_after)},
                )

            user = session.get(UserDB, invitation.user_id)
            if user is None or not hmac.compare_digest(
                invitation.email.lower(), str(user.email).strip().lower()
            ):
                invitation.status = InvitationStatus.revoked
                invitation.updated_at = now
                session.add(invitation)
                session.commit()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
            if not user.is_active and (user.hashed_password is not None or session.get(GoogleIdentityDB, user.id)):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Le compte associe est desactive et doit etre reactive explicitement.",
                )

            invitation.token_digest = digest
            invitation.status = InvitationStatus.pending_delivery
            invitation.language = _validate_language(language or invitation.language)
            invitation.created_by_user_id = str(actor.id)
            invitation.send_attempts += 1
            invitation.last_attempt_at = now
            invitation.expires_at = now + timedelta(minutes=get_invitation_ttl_minutes())
            invitation.accepted_at = None
            invitation.failed_at = None
            invitation.failure_code = None
            invitation.provider_message_id = None
            invitation.updated_at = now
            session.add(invitation)
            session.commit()
            requires_password = user.hashed_password is None

        return self._deliver(
            invitation_id=invitation_id,
            expected_digest=digest,
            token=token,
            requires_password=requires_password,
            actor_user_id=str(actor.id),
        )

    def _prepare_assignment(
        self,
        session,
        *,
        user: UserDB,
        role: UserRole,
        scope_kind: InvitationScopeKind,
        scope_id: str,
    ) -> tuple[Optional[MembershipDB], Optional[AccessGrantDB]]:
        if scope_kind == InvitationScopeKind.global_scope:
            if scope_id != GLOBAL_SCOPE_ID or role != UserRole.platform_admin:
                raise HTTPException(status_code=400, detail="Scope global d'invitation invalide.")
            return None, None

        if scope_kind == InvitationScopeKind.client:
            if role != UserRole.client_admin:
                raise HTTPException(status_code=400, detail="Role client d'invitation invalide.")
            grant = session.exec(
                select(AccessGrantDB).where(
                    AccessGrantDB.user_id == str(user.id),
                    AccessGrantDB.scope_kind == AccessScopeKind.client,
                    AccessGrantDB.scope_id == scope_id,
                    AccessGrantDB.role == UserRole.client_admin,
                )
            ).first()
            if grant is None:
                grant = AccessGrantDB(
                    user_id=str(user.id),
                    scope_kind=AccessScopeKind.client,
                    scope_id=scope_id,
                    role=UserRole.client_admin,
                    is_active=False,
                )
                session.add(grant)
            return None, grant

        if scope_kind == InvitationScopeKind.enterprise:
            membership = session.exec(
                select(MembershipDB).where(
                    MembershipDB.user_id == str(user.id),
                    MembershipDB.enterprise_id == scope_id,
                )
            ).first()
            if membership is not None and membership.is_active and membership.role != role:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Un acces actif existe deja avec un autre role. "
                        "Utilisez la modification de role explicite."
                    ),
                )
            if membership is None:
                membership = MembershipDB(
                    user_id=str(user.id),
                    enterprise_id=scope_id,
                    role=role,
                    is_active=False,
                )
                session.add(membership)
            elif not membership.is_active:
                membership.role = role
                session.add(membership)
            return membership, None

        raise HTTPException(status_code=400, detail="Scope d'invitation invalide.")

    def _deliver(
        self,
        *,
        invitation_id: str,
        expected_digest: str,
        token: str,
        requires_password: bool,
        actor_user_id: str,
    ) -> InvitationOutcome:
        failure_code: Optional[str] = None
        provider_message_id: Optional[str] = None
        try:
            with get_session_direct() as session:
                invitation = session.get(UserInvitationDB, invitation_id)
                if invitation is None or invitation.token_digest != expected_digest:
                    raise EmailDeliveryError("L'invitation a ete remplacee avant son envoi.")
                message = InvitationEmail(
                    recipient=invitation.email,
                    first_name=invitation.first_name,
                    last_name=invitation.last_name,
                    activation_url=_build_activation_url(token),
                    language=invitation.language,
                    role=invitation.role,
                    requires_password=requires_password,
                    issued_at=_as_utc(invitation.last_attempt_at or invitation.created_at),
                    expires_at=_as_utc(invitation.expires_at),
                    **_invitation_trial_metadata(session, invitation),
                )
            sender = get_email_sender()
            provider_message_id = sender.send_invitation(message)
        except EmailConfigurationError:
            failure_code = "EMAIL_CONFIGURATION_UNAVAILABLE"
        except EmailDeliveryError:
            failure_code = "EMAIL_PROVIDER_UNAVAILABLE"

        now = _now()
        with get_session_direct() as session:
            invitation = session.exec(
                select(UserInvitationDB)
                .where(UserInvitationDB.id == invitation_id)
                .with_for_update()
            ).first()
            if invitation is None:
                raise HTTPException(status_code=404, detail="Invitation introuvable.")
            if not hmac.compare_digest(invitation.token_digest, expected_digest):
                raise HTTPException(status_code=409, detail="Cette invitation a ete remplacee.")

            if failure_code:
                invitation.status = InvitationStatus.delivery_failed
                invitation.failed_at = now
                invitation.failure_code = failure_code
                invitation.provider_message_id = None
                audit_action = "user_invitation.delivery_failed"
            else:
                invitation.status = InvitationStatus.sent
                invitation.last_sent_at = now
                invitation.failed_at = None
                invitation.failure_code = None
                invitation.provider_message_id = provider_message_id
                audit_action = "user_invitation.sent"
            invitation.updated_at = now
            session.add(invitation)
            _audit(
                session,
                invitation=invitation,
                action=audit_action,
                actor_user_id=actor_user_id,
                metadata={"failure_code": failure_code} if failure_code else None,
            )
            session.commit()
            session.refresh(invitation)

            return InvitationOutcome(
                invitation_id=str(invitation.id),
                user_id=str(invitation.user_id),
                membership_id=invitation.membership_id,
                access_grant_id=invitation.access_grant_id,
                status=invitation.status,
                expires_at=invitation.expires_at,
                retry_after_seconds=_retry_after(invitation, now),
            )

    def inspect(self, token: str) -> InvitationInspection:
        if not token or len(token) > 512:
            return InvitationInspection(status="invalid")
        digest = _token_digest(token)
        now = _now()
        with get_session_direct() as session:
            invitation = session.exec(
                select(UserInvitationDB).where(UserInvitationDB.token_digest == digest)
            ).first()
            if invitation is None:
                return InvitationInspection(status="invalid")
            if invitation.status == InvitationStatus.accepted:
                return InvitationInspection(status="used")
            if invitation.status in {
                InvitationStatus.delivery_failed,
                InvitationStatus.pending_delivery,
            }:
                return InvitationInspection(status="email_unavailable")
            if invitation.status == InvitationStatus.expired:
                return InvitationInspection(status="expired")
            if invitation.status == InvitationStatus.revoked:
                return InvitationInspection(status="invalid")
            if _as_utc(invitation.expires_at) <= now:
                invitation.status = InvitationStatus.expired
                invitation.updated_at = now
                session.add(invitation)
                session.commit()
                return InvitationInspection(status="expired")

            user = session.get(UserDB, invitation.user_id)
            if user is None or not hmac.compare_digest(
                invitation.email.lower(), str(user.email).strip().lower()
            ):
                return InvitationInspection(status="invalid")
            return InvitationInspection(
                status="ready",
                requires_password=user.hashed_password is None,
                expires_at=invitation.expires_at,
                **_invitation_trial_metadata(session, invitation),
            )

    def accept(self, *, token: str, password: Optional[str]) -> InvitationInspection:
        if not token or len(token) > 512:
            return InvitationInspection(status="invalid")
        digest = _token_digest(token)
        now = _now()

        with get_session_direct() as session:
            invitation = session.exec(
                select(UserInvitationDB)
                .where(UserInvitationDB.token_digest == digest)
                .with_for_update()
            ).first()
            if invitation is None:
                return InvitationInspection(status="invalid")
            if invitation.status == InvitationStatus.accepted:
                return InvitationInspection(status="used")
            if invitation.status != InvitationStatus.sent:
                return InvitationInspection(
                    status=(
                        "expired"
                        if invitation.status == InvitationStatus.expired
                        else "email_unavailable"
                        if invitation.status in {
                            InvitationStatus.delivery_failed,
                            InvitationStatus.pending_delivery,
                        }
                        else "invalid"
                    )
                )
            if _as_utc(invitation.expires_at) <= now:
                invitation.status = InvitationStatus.expired
                invitation.updated_at = now
                session.add(invitation)
                session.commit()
                return InvitationInspection(status="expired")

            user = session.get(UserDB, invitation.user_id)
            if user is None or not hmac.compare_digest(
                invitation.email.lower(), str(user.email).strip().lower()
            ):
                invitation.status = InvitationStatus.revoked
                invitation.updated_at = now
                session.add(invitation)
                session.commit()
                return InvitationInspection(status="invalid")

            if not user.is_active and session.get(GoogleIdentityDB, user.id):
                raise HTTPException(status_code=409, detail="Ce compte est desactive. Contactez un administrateur.")
            if not self._activate_assignment(session, invitation=invitation, user=user, now=now):
                invitation.status = InvitationStatus.revoked
                invitation.updated_at = now
                session.add(invitation)
                session.commit()
                return InvitationInspection(status="invalid")

            if user.hashed_password is None:
                if password is None:
                    raise HTTPException(status_code=400, detail="Un mot de passe est requis.")
                _validate_password(password)
                user.hashed_password = get_password_hash(password)
                user.is_active = True
                session.add(user)
            elif password is not None:
                # Un compte existant conserve son mot de passe par defaut. Le
                # proprietaire de l'adresse peut toutefois choisir explicitement
                # d'en definir un nouveau depuis ce lien a usage unique. Ce chemin
                # permet aussi de recuperer les comptes crees par l'ancien flux,
                # dont le mot de passe aleatoire n'avait jamais ete communique.
                _validate_password(password)
                user.hashed_password = get_password_hash(password)
                user.is_active = True
                session.add(user)
            elif not user.is_active:
                raise HTTPException(
                    status_code=409,
                    detail="Ce compte est desactive. Contactez un administrateur.",
                )

            invitation.status = InvitationStatus.accepted
            invitation.accepted_at = now
            invitation.updated_at = now
            session.add(invitation)
            session.add(
                AuditLogDB(
                    enterprise_id="SYSTEM",
                    actor_user_id=None,
                    action="auth.tokens.revoked",
                    resource_type="user",
                    resource_id=str(user.id),
                    metadata_json=json.dumps({"reason": "invitation_accepted"}),
                )
            )
            _audit(
                session,
                invitation=invitation,
                action="user_invitation.accepted",
                actor_user_id=str(user.id),
            )
            session.commit()
            return InvitationInspection(
                status="accepted",
                **_invitation_trial_metadata(session, invitation),
            )

    def accept_google(self, session, *, digest: str, verified_email: str) -> UserDB:
        """Accept the invitation in the caller's identity-linking transaction.

        The digest is captured only after proving possession of the raw invitation
        at OAuth start. Neither the Google email alone nor a pending record grants access.
        """
        now = _now()
        invitation = session.exec(
            select(UserInvitationDB)
            .where(UserInvitationDB.token_digest == digest)
            .with_for_update()
        ).first()
        if invitation is None:
            logger.warning("Google invitation rejected: missing")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        if invitation.status != InvitationStatus.sent:
            logger.warning("Google invitation rejected: status")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        if _as_utc(invitation.expires_at) <= now:
            logger.warning("Google invitation rejected: expired")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        if not hmac.compare_digest(invitation.email.lower().encode("utf-8"), verified_email.encode("utf-8")):
            logger.warning("Google invitation rejected: email_mismatch")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        user = session.exec(select(UserDB).where(UserDB.id == invitation.user_id).with_for_update()).first()
        if (
            user is None or not hmac.compare_digest(user.email.strip().lower().encode("utf-8"), verified_email.encode("utf-8"))
            or (not user.is_active and (user.hashed_password is not None or session.get(GoogleIdentityDB, user.id)))
        ):
            logger.warning("Google invitation rejected: account_mismatch")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        if not self._activate_assignment(session, invitation=invitation, user=user, now=now):
            logger.warning("Google invitation rejected: assignment_mismatch")
            raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
        user.is_active = True
        invitation.status = InvitationStatus.accepted
        invitation.accepted_at = now
        invitation.updated_at = now
        session.add(user)
        session.add(invitation)
        session.add(AuditLogDB(
            enterprise_id="SYSTEM", action="auth.tokens.revoked", resource_type="user",
            resource_id=str(user.id), metadata_json=json.dumps({"reason": "invitation_accepted"}),
        ))
        _audit(session, invitation=invitation, action="user_invitation.accepted", actor_user_id=str(user.id))
        return user

    def _activate_assignment(
        self,
        session,
        *,
        invitation: UserInvitationDB,
        user: UserDB,
        now: Optional[datetime] = None,
    ) -> bool:
        if invitation.scope_kind == InvitationScopeKind.global_scope:
            if invitation.scope_id != GLOBAL_SCOPE_ID or invitation.role != UserRole.platform_admin:
                return False
            user.role = UserRole.platform_admin
            session.add(user)
            return True

        if invitation.scope_kind == InvitationScopeKind.client:
            if not invitation.access_grant_id or invitation.role != UserRole.client_admin:
                return False
            grant = session.get(AccessGrantDB, invitation.access_grant_id)
            if (
                grant is None
                or str(grant.user_id) != str(user.id)
                or grant.scope_kind != AccessScopeKind.client
                or str(grant.scope_id) != invitation.scope_id
                or grant.role != invitation.role
            ):
                return False
            tenant = session.exec(
                select(TenantDB).where(TenantDB.id == invitation.scope_id).with_for_update()
            ).first()
            if tenant is None:
                return False
            activation_time = _as_utc(now or _now())
            if tenant.trial_duration_days is not None:
                if tenant.trial_started_at is None:
                    tenant.trial_started_at = activation_time
                    tenant.trial_expires_at = activation_time + timedelta(
                        days=tenant.trial_duration_days
                    )
                    session.add(tenant)
                    session.add(
                        AuditLogDB(
                            enterprise_id="SYSTEM",
                            actor_user_id=str(user.id),
                            action="client.trial.started",
                            resource_type="tenant",
                            resource_id=str(tenant.id),
                            metadata_json=json.dumps(
                                {
                                    "trial_duration_days": tenant.trial_duration_days,
                                    "trial_started_at": activation_time.isoformat(),
                                    "trial_expires_at": tenant.trial_expires_at.isoformat(),
                                }
                            ),
                        )
                    )
                elif tenant.trial_expires_at is None:
                    return False
            grant.is_active = True
            grant.updated_at = activation_time
            session.add(grant)
            return True

        if invitation.scope_kind == InvitationScopeKind.enterprise:
            if not invitation.membership_id:
                return False
            membership = session.get(MembershipDB, invitation.membership_id)
            if (
                membership is None
                or str(membership.user_id) != str(user.id)
                or str(membership.enterprise_id) != invitation.scope_id
                or membership.role != invitation.role
            ):
                return False
            membership.is_active = True
            session.add(membership)
            return True

        return False
