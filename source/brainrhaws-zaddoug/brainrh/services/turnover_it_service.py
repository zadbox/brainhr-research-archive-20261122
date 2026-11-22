"""Turnover IT JobConnect application service.

The raw provider token is only read from/written to SSM Parameter Store.  It is
never returned by this module and never included in persisted provider payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from brainrh.models.application import ApplicationDB
from brainrh.models.integration import (
    ConnectorStatus,
    EventStatus,
    IntegrationAccountDB,
    IntegrationScopeKind,
    OutboundEventDB,
)
from brainrh.models.project import ProjectDB
from brainrh.models.resume_version import ResumeVersionDB
from brainrh.models.talent_profile import TalentProfileDB
from brainrh.models.turnover_it import (
    TurnoverApplicationInboxDB,
    TurnoverIngestionResponse,
    TurnoverJobPublicationDB,
    TurnoverPublicationResponse,
)
from brainrh.services.project_file_service import ProjectFileService
from brainrh.settings import get_app_env


TURNOVER_CONNECTOR_ID = "turnover_it"
TURNOVER_API_BASE_URL = "https://api.turnover-it.com/jobconnect/v2"
TURNOVER_PUBLICATION_EVENT = "turnover_it.publication.requested"
BROKERED_AWS_DATA_PROFILE = "brainrh-backend-data"


class TurnoverITError(ValueError):
    pass


class SSMTokenStore:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            import boto3

            profile_name = os.getenv("BRAINRH_AWS_DATA_PROFILE", "").strip()
            if profile_name:
                if profile_name != BROKERED_AWS_DATA_PROFILE:
                    raise TurnoverITError("Profil AWS de données backend invalide.")
                client = boto3.Session(profile_name=profile_name).client("ssm")
            else:
                client = boto3.client("ssm")
        self._client = client

    @staticmethod
    def parameter_name(tenant_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", tenant_id):
            raise TurnoverITError("Identifiant client invalide pour le stockage du secret.")
        app_env = get_app_env()
        stage = "prod" if app_env in {"prod", "production"} else app_env
        return f"/brainrh/{stage}/integrations/turnover-it/{tenant_id}/token"

    def put(self, tenant_id: str, token: str) -> str:
        parameter_name = self.parameter_name(tenant_id)
        self._client.put_parameter(
            Name=parameter_name,
            Value=token,
            Type="SecureString",
            Overwrite=True,
        )
        return f"ssm:{parameter_name}"

    def get(self, secret_ref: str) -> str:
        if not secret_ref.startswith("ssm:/"):
            raise TurnoverITError("Référence de secret Turnover IT invalide.")
        parameter_name = secret_ref[len("ssm:") :]
        response = self._client.get_parameter(Name=parameter_name, WithDecryption=True)
        token = str(response.get("Parameter", {}).get("Value") or "")
        if not token:
            raise TurnoverITError("Token Turnover IT introuvable.")
        return token


def get_turnover_account(session: Session, tenant_id: str) -> Optional[IntegrationAccountDB]:
    return session.exec(
        select(IntegrationAccountDB).where(
            IntegrationAccountDB.scope_kind == IntegrationScopeKind.client,
            IntegrationAccountDB.scope_id == tenant_id,
            IntegrationAccountDB.connector_id == TURNOVER_CONNECTOR_ID,
        )
    ).first()


def configure_turnover_account(
    session: Session,
    tenant_id: str,
    token: str,
    *,
    token_store: Optional[SSMTokenStore] = None,
) -> IntegrationAccountDB:
    normalized_token = token.strip()
    if not normalized_token:
        raise TurnoverITError("token est requis.")
    secret_ref = (token_store or SSMTokenStore()).put(tenant_id, normalized_token)
    account = get_turnover_account(session, tenant_id)
    now = datetime.now(timezone.utc)
    if account is None:
        account = IntegrationAccountDB(
            scope_kind=IntegrationScopeKind.client,
            scope_id=tenant_id,
            connector_id=TURNOVER_CONNECTOR_ID,
            status=ConnectorStatus.active,
            config_json=json.dumps({"api_base_url": TURNOVER_API_BASE_URL}, sort_keys=True),
            secret_ref=secret_ref,
        )
    else:
        account.status = ConnectorStatus.active
        account.config_json = json.dumps({"api_base_url": TURNOVER_API_BASE_URL}, sort_keys=True)
        account.secret_ref = secret_ref
        account.updated_at = now
    session.add(account)
    session.flush()
    return account


def resolve_turnover_token(
    session: Session,
    tenant_id: str,
    *,
    token_store: Optional[SSMTokenStore] = None,
) -> str:
    account = get_turnover_account(session, tenant_id)
    if account is None or account.status != ConnectorStatus.active or not account.secret_ref:
        raise TurnoverITError("Intégration Turnover IT non configurée pour ce client.")
    expected_ref = f"ssm:{SSMTokenStore.parameter_name(tenant_id)}"
    if not hmac.compare_digest(account.secret_ref, expected_ref):
        raise TurnoverITError("Référence de secret Turnover IT invalide pour ce client.")
    return (token_store or SSMTokenStore()).get(account.secret_ref)


def test_turnover_connection(
    session: Session,
    tenant_id: str,
    *,
    token_store: Optional[SSMTokenStore] = None,
    requester: Optional[Callable[..., Any]] = None,
) -> tuple[bool, Optional[int], str]:
    token = resolve_turnover_token(session, tenant_id, token_store=token_store)
    sender = requester or httpx.get
    try:
        response = sender(
            f"{TURNOVER_API_BASE_URL}/jobs",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10.0,
            follow_redirects=False,
        )
        connected = 200 <= response.status_code < 300
        return connected, response.status_code, "Connexion réussie." if connected else "Connexion refusée par Turnover IT."
    except httpx.RequestError:
        return False, None, "Turnover IT est temporairement injoignable."


def create_publication(
    session: Session,
    *,
    tenant_id: str,
    project: ProjectDB,
    contract: str,
    remote: str,
    country: str,
    region: Optional[str],
    postal_code: Optional[str],
    requested_status: str,
    callback_url: str,
    publication_id: Optional[str] = None,
) -> TurnoverJobPublicationDB:
    publication_values = {
        "tenant_id": tenant_id,
        "enterprise_id": str(project.enterprise_id),
        "project_id": project.id,
        "contract": contract.strip(),
        "remote": remote,
        "country": country.strip(),
        "region": region.strip() if region else None,
        "postal_code": postal_code.strip() if postal_code else None,
        "requested_status": (requested_status or "Draft").strip(),
        "callback_url": callback_url,
    }
    if publication_id:
        publication_values["id"] = publication_id
    publication = TurnoverJobPublicationDB(**publication_values)
    session.add(publication)
    session.flush()
    event = OutboundEventDB(
        enterprise_id=str(project.enterprise_id),
        event_type=TURNOVER_PUBLICATION_EVENT,
        payload_json=json.dumps({"publication_id": publication.id}),
        status=EventStatus.pending,
    )
    session.add(event)
    session.flush()
    return publication


def _offer_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return [normalized] if normalized else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_offer_text_values(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_offer_text_values(item))
        return result
    return []


def turnover_offer_content(project: ProjectDB) -> tuple[str, str]:
    """Map a structured BrainRH offer into JobConnect title/description fields."""
    offer = ProjectFileService.load_offer(project.id, enterprise_id=project.enterprise_id)
    if not isinstance(offer, dict):
        raise TurnoverITError("Une offre BrainRH structurée est requise avant publication.")

    sections = offer.get("sections") if isinstance(offer.get("sections"), dict) else {}
    title = str(sections.get("titre") or project.nom or "").strip()
    if not 5 <= len(title) <= 100:
        raise TurnoverITError("Le titre Turnover IT doit contenir entre 5 et 100 caractères.")

    ordered_sources = [
        offer.get("source_text"),
        sections.get("description"),
        sections.get("resume_professionnel"),
        sections.get("responsabilites"),
        sections.get("projets"),
        sections.get("experiences_professionnelles"),
        sections.get("competences_techniques"),
        sections.get("competences_transversales"),
        sections.get("formations"),
        sections.get("certifications"),
        offer.get("must_have"),
        offer.get("nice_have"),
    ]
    parts: list[str] = []
    seen: set[str] = set()
    for source in ordered_sources:
        for part in _offer_text_values(source):
            if part not in seen:
                seen.add(part)
                parts.append(part)
    description = "\n\n".join(parts).strip()
    if len(description) < 500:
        raise TurnoverITError(
            "La description Turnover IT issue de l’offre doit contenir entre 500 et 8 000 caractères."
        )
    return title, description[:8000]


def publication_response(session: Session, publication: TurnoverJobPublicationDB) -> TurnoverPublicationResponse:
    count = session.exec(
        select(func.count(TurnoverApplicationInboxDB.id)).where(
            TurnoverApplicationInboxDB.publication_id == publication.id,
            TurnoverApplicationInboxDB.application_id.is_not(None),
        )
    ).one()
    return TurnoverPublicationResponse(
        **publication.model_dump(),
        application_count=int(count or 0),
    )


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("candidate", "application", "applicant"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


def sanitize_turnover_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    sanitized.pop("jobConnectToken", None)
    sanitized.pop("job_connect_token", None)
    return sanitized


def ingest_turnover_application(
    session: Session,
    publication: TurnoverJobPublicationDB,
    payload: dict[str, Any],
    *,
    expected_token: str,
) -> TurnoverIngestionResponse:
    supplied_token = str(_first_value(payload, "jobConnectToken", "job_connect_token") or "")
    if not hmac.compare_digest(supplied_token, expected_token):
        raise TurnoverITError("Token de callback invalide.")

    reference = str(
        _first_value(
            payload,
            "jobPostingReference",
            "job_posting_reference",
            "reference",
            "jobReference",
            "job_reference",
        )
        or ""
    )
    if reference != publication.id:
        raise TurnoverITError("Référence de publication invalide.")

    payload_tenant = _first_value(payload, "tenantId", "tenant_id")
    if payload_tenant is not None and str(payload_tenant) != publication.tenant_id:
        raise TurnoverITError("Client de callback invalide.")

    sanitized = sanitize_turnover_payload(payload)
    candidate = _candidate_payload(sanitized)
    first_name = str(_first_value(candidate, "firstName", "first_name", "firstname") or "").strip()
    last_name = str(_first_value(candidate, "lastName", "last_name", "lastname") or "").strip()
    email = str(_first_value(candidate, "email", "mail") or "").strip().lower()
    phone_value = _first_value(candidate, "phone", "phoneNumber", "phone_number")
    phone = str(phone_value).strip() if phone_value else None
    if not first_name or not last_name or not email:
        raise TurnoverITError("Prénom, nom et email candidat sont requis.")

    provider_application_id = _first_value(
        sanitized,
        "applicationId",
        "application_id",
        "applicationReference",
        "application_reference",
    ) or _first_value(
        candidate,
        "applicationId",
        "application_id",
        "applicationReference",
        "application_reference",
        "id",
    )
    idempotency_identity = (
        {"provider_application_id": str(provider_application_id).strip()}
        if provider_application_id
        else {
            "email": email,
            "first_name": first_name.casefold(),
            "last_name": last_name.casefold(),
            "phone": phone or "",
        }
    )
    canonical_identity = json.dumps(
        idempotency_identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_hash = hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()
    duplicate = session.exec(
        select(TurnoverApplicationInboxDB).where(
            TurnoverApplicationInboxDB.publication_id == publication.id,
            TurnoverApplicationInboxDB.payload_hash == payload_hash,
        )
    ).first()
    if duplicate is not None:
        return TurnoverIngestionResponse(
            accepted=True, duplicate=True, application_id=duplicate.application_id
        )

    canonical_payload = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    inbox = TurnoverApplicationInboxDB(
        publication_id=publication.id,
        tenant_id=publication.tenant_id,
        payload_hash=payload_hash,
        payload_json=canonical_payload,
    )
    try:
        with session.begin_nested():
            session.add(inbox)
            session.flush()
    except IntegrityError:
        concurrent_duplicate = session.exec(
            select(TurnoverApplicationInboxDB).where(
                TurnoverApplicationInboxDB.publication_id == publication.id,
                TurnoverApplicationInboxDB.payload_hash == payload_hash,
            )
        ).first()
        if concurrent_duplicate is None:
            raise
        return TurnoverIngestionResponse(
            accepted=True,
            duplicate=True,
            application_id=concurrent_duplicate.application_id,
        )

    profile = TalentProfileDB(
        enterprise_id=publication.enterprise_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    session.add(profile)
    session.flush()
    filename = f"turnover-it-{publication.id}-{profile.id}.json"
    parsed = {
        "cv": filename,
        "filename": filename,
        "nom_complet": f"{first_name} {last_name}".strip(),
        "informations_personnelles": {
            "prenom": first_name,
            "nom": last_name,
            "email": email,
            "telephone": phone or "",
        },
        "identite": {
            "prenom": first_name,
            "nom": last_name,
            "email": email,
            "telephone": phone or "",
        },
        "competences_techniques": [],
        "competences_transversales": [],
        "langues": [],
        "experiences_professionnelles": [],
        "formations": [],
        "certifications": [],
        "projets": [],
        "source": "turnover_it",
    }
    resume = ResumeVersionDB(
        enterprise_id=publication.enterprise_id,
        talent_profile_id=profile.id,
        parsed_json_str=json.dumps(parsed, ensure_ascii=False),
    )
    session.add(resume)
    session.flush()
    application = ApplicationDB(
        enterprise_id=publication.enterprise_id,
        talent_profile_id=profile.id,
        resume_version_id=resume.id,
        project_id=publication.project_id,
        status="new",
    )
    session.add(application)
    session.flush()
    inbox.application_id = application.id
    session.add(inbox)
    session.flush()
    return TurnoverIngestionResponse(accepted=True, duplicate=False, application_id=application.id)


def simulate_payload(publication: TurnoverJobPublicationDB, values: dict[str, Any], token: str) -> dict[str, Any]:
    return {
        "jobPostingReference": publication.id,
        "jobConnectToken": token,
        "candidate": {
            "firstName": values["first_name"],
            "lastName": values["last_name"],
            "email": values["email"],
            "phone": values.get("phone"),
        },
    }
