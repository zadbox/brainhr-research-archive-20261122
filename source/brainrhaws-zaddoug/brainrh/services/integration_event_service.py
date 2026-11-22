"""Service d'événements d'intégration (outbox pattern) — INTEG-004.

Ce service s'occupe de :
- Enregistrer des événements sortants dans l'outbox.
- Enregistrer des souscriptions webhook.
- Résoudre les destinations pour un événement donné.
- Simuler une livraison (sans appel réseau réel).
- Préparer la signature HMAC des payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from brainrh.models.integration import (
    DeliveryAttemptDB,
    DeliveryStatus,
    EventStatus,
    OutboundEventDB,
    WebhookSubscriptionDB,
)


class IntegrationEventService:
    """Service stateless opérant sur la session fournie."""

    # ---- Outbox ----

    @staticmethod
    def emit_event(
        session: Session,
        enterprise_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> OutboundEventDB:
        """Enregistre un événement dans l'outbox (status=pending)."""
        evt = OutboundEventDB(
            enterprise_id=enterprise_id,
            event_type=event_type,
            payload_json=json.dumps(payload, default=str),
            status=EventStatus.pending,
        )
        session.add(evt)
        session.flush()
        return evt

    @staticmethod
    def list_pending_events(
        session: Session,
        enterprise_id: Optional[str] = None,
        limit: int = 100,
        excluded_event_types: Optional[set[str]] = None,
    ) -> List[OutboundEventDB]:
        """Retourne les événements en attente de livraison."""
        stmt = select(OutboundEventDB).where(
            OutboundEventDB.status.in_([EventStatus.pending, EventStatus.retrying])
        )
        if enterprise_id:
            stmt = stmt.where(OutboundEventDB.enterprise_id == enterprise_id)
        if excluded_event_types:
            stmt = stmt.where(OutboundEventDB.event_type.notin_(excluded_event_types))
        stmt = stmt.order_by(OutboundEventDB.created_at).limit(limit)
        return list(session.exec(stmt).all())

    # ---- Webhook subscriptions ----

    @staticmethod
    def create_subscription(
        session: Session,
        enterprise_id: str,
        target_url: str,
        event_types: List[str],
        secret_ref: Optional[str] = None,
    ) -> WebhookSubscriptionDB:
        """Crée une souscription webhook pour un tenant."""
        sub = WebhookSubscriptionDB(
            enterprise_id=enterprise_id,
            target_url=target_url,
            event_types_json=json.dumps(event_types),
            secret_ref=secret_ref,
        )
        session.add(sub)
        session.flush()
        return sub

    @staticmethod
    def list_subscriptions(
        session: Session,
        enterprise_id: Optional[str] = None,
        active_only: Optional[bool] = None,
    ) -> List[WebhookSubscriptionDB]:
        """Liste les souscriptions webhook d'une enterprise."""
        stmt = select(WebhookSubscriptionDB)
        if enterprise_id:
            stmt = stmt.where(WebhookSubscriptionDB.enterprise_id == enterprise_id)
        if active_only is True:
            stmt = stmt.where(WebhookSubscriptionDB.is_active == True)  # noqa: E712
        elif active_only is False:
            stmt = stmt.where(WebhookSubscriptionDB.is_active == False)  # noqa: E712

        stmt = stmt.order_by(WebhookSubscriptionDB.created_at.desc())
        return list(session.exec(stmt).all())

    @staticmethod
    def get_subscription(
        session: Session,
        enterprise_id: str,
        subscription_id: str,
    ) -> Optional[WebhookSubscriptionDB]:
        """Retourne une souscription donnée pour une enterprise."""
        stmt = select(WebhookSubscriptionDB).where(
            WebhookSubscriptionDB.id == subscription_id,
            WebhookSubscriptionDB.enterprise_id == enterprise_id,
        )
        return session.exec(stmt).first()

    @staticmethod
    def update_subscription(
        session: Session,
        subscription: WebhookSubscriptionDB,
        *,
        target_url: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        secret_ref: Optional[str] = None,
        secret_ref_was_set: bool = False,
        is_active: Optional[bool] = None,
    ) -> WebhookSubscriptionDB:
        """Met à jour une souscription webhook."""
        if target_url is not None:
            subscription.target_url = target_url
        if event_types is not None:
            subscription.event_types_json = json.dumps(event_types)
        if secret_ref_was_set:
            subscription.secret_ref = secret_ref
        if is_active is not None:
            subscription.is_active = is_active

        session.add(subscription)
        session.flush()
        return subscription

    @staticmethod
    def deactivate_subscription(
        session: Session,
        subscription: WebhookSubscriptionDB,
    ) -> WebhookSubscriptionDB:
        """Désactive une souscription sans supprimer l'historique associé."""
        subscription.is_active = False
        session.add(subscription)
        session.flush()
        return subscription

    @staticmethod
    def find_subscriptions_for_event(
        session: Session,
        enterprise_id: str,
        event_type: str,
    ) -> List[WebhookSubscriptionDB]:
        """Trouve les souscriptions actives correspondant à un type d'événement."""
        stmt = select(WebhookSubscriptionDB).where(
            WebhookSubscriptionDB.enterprise_id == enterprise_id,
            WebhookSubscriptionDB.is_active == True,  # noqa: E712
        )
        results = list(session.exec(stmt).all())
        matched: List[WebhookSubscriptionDB] = []
        for sub in results:
            types = json.loads(sub.event_types_json)
            if event_type in types or "*" in types:
                matched.append(sub)
        return matched

    # ---- Delivery ----

    @staticmethod
    def record_delivery_attempt(
        session: Session,
        event: OutboundEventDB,
        subscription: WebhookSubscriptionDB,
        status: DeliveryStatus,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> DeliveryAttemptDB:
        """Enregistre une tentative de livraison."""
        attempt = DeliveryAttemptDB(
            event_id=event.id,
            subscription_id=subscription.id,
            status=status,
            status_code=status_code,
            response_body=response_body,
        )
        session.add(attempt)

        # Met à jour le statut de l'événement
        if status == DeliveryStatus.success:
            event.status = EventStatus.delivered
        else:
            event.retry_count += 1
            if event.retry_count >= 5:
                event.status = EventStatus.failed
            else:
                event.status = EventStatus.retrying

        session.add(event)
        session.flush()
        return attempt

    # ---- HMAC signature ----

    @staticmethod
    def sign_payload(payload_json: str, secret: str) -> str:
        """Calcule une signature HMAC-SHA256 pour un payload."""
        return hmac.new(
            secret.encode("utf-8"),
            payload_json.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def verify_signature(payload_json: str, secret: str, signature: str) -> bool:
        """Vérifie une signature HMAC-SHA256."""
        expected = IntegrationEventService.sign_payload(payload_json, secret)
        return hmac.compare_digest(expected, signature)
