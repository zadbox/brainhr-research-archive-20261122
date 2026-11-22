"""Provider-specific outbox delivery for Turnover IT publications."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from sqlmodel import Session

from brainrh.models.integration import EventStatus, OutboundEventDB
from brainrh.models.project import ProjectDB
from brainrh.models.turnover_it import TurnoverJobPublicationDB
from brainrh.services.turnover_it_service import (
    TURNOVER_API_BASE_URL,
    SSMTokenStore,
    TurnoverITError,
    resolve_turnover_token,
    turnover_offer_content,
)


ProviderRequester = Callable[..., Any]


def _response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_remote_public_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    allowed = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("turnover-it.com", "free-work.com")
    )
    return value if parsed.scheme == "https" and allowed else None


def deliver_turnover_publication_event(
    session: Session,
    event: OutboundEventDB,
    *,
    token_store: Optional[SSMTokenStore] = None,
    requester: Optional[ProviderRequester] = None,
) -> bool:
    """Deliver one provider event and update publication/event retry state."""
    try:
        event_payload = json.loads(event.payload_json)
    except (TypeError, ValueError):
        event_payload = {}
    if set(event_payload) != {"publication_id"}:
        event.status = EventStatus.failed
        event.retry_count += 1
        session.add(event)
        session.flush()
        return False

    publication = session.get(TurnoverJobPublicationDB, str(event_payload["publication_id"]))
    if publication is None or publication.enterprise_id != event.enterprise_id:
        event.status = EventStatus.failed
        event.retry_count += 1
        session.add(event)
        session.flush()
        return False

    project = session.get(ProjectDB, publication.project_id)
    if project is None or str(project.enterprise_id) != publication.enterprise_id:
        publication.status = "failed"
        publication.last_error = "Projet introuvable ou hors périmètre client."
        event.status = EventStatus.failed
        event.retry_count += 1
        session.add(publication)
        session.add(event)
        session.flush()
        return False

    try:
        token = resolve_turnover_token(session, publication.tenant_id, token_store=token_store)
        title, description = turnover_offer_content(project)
        location = {"country": publication.country}
        if publication.postal_code:
            location["postalCode"] = publication.postal_code
        elif publication.region:
            location["region"] = publication.region
        body = {
            "reference": publication.id,
            "title": title,
            "description": description,
            "contract": [publication.contract],
            "remote": publication.remote,
            "location": location,
            "status": publication.requested_status.upper(),
            "application": {"callbackUrl": publication.callback_url},
        }
        method = "PUT" if publication.remote_job_id else "POST"
        url = (
            f"{TURNOVER_API_BASE_URL}/jobs/{publication.remote_job_id}"
            if publication.remote_job_id
            else f"{TURNOVER_API_BASE_URL}/jobs"
        )
        if requester is None:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                response = client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    json=body,
                )
        else:
            response = requester(
                method,
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json=body,
                timeout=15.0,
                follow_redirects=False,
            )
        if not 200 <= response.status_code < 300:
            raise TurnoverITError(f"Turnover IT a répondu HTTP {response.status_code}.")

        provider_payload = _response_json(response)
        publication.remote_job_id = str(
            provider_payload.get("id") or provider_payload.get("jobId") or publication.remote_job_id or ""
        ) or None
        publication.remote_public_url = _safe_remote_public_url(
            provider_payload.get("url")
            or provider_payload.get("publicUrl")
            or provider_payload.get("public_url")
        )
        publication.status = "published"
        publication.last_error = None
        publication.updated_at = datetime.now(timezone.utc)
        event.status = EventStatus.delivered
        session.add(publication)
        session.add(event)
        session.flush()
        return True
    except Exception as exc:
        event.retry_count += 1
        terminal = event.retry_count >= 5
        event.status = EventStatus.failed if terminal else EventStatus.retrying
        publication.status = "failed" if terminal else "retrying"
        publication.last_error = (
            str(exc)
            if isinstance(exc, (TurnoverITError, httpx.RequestError))
            else "Échec interne de livraison Turnover IT."
        )
        publication.updated_at = datetime.now(timezone.utc)
        session.add(publication)
        session.add(event)
        session.flush()
        return False
