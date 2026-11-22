"""Service de livraison webhook Zapier/Make (INTEG-006).

Orchestre le flux complet :
1. Un événement est émis dans l'outbox.
2. Les souscriptions correspondantes sont trouvées.
3. Pour chaque souscription, le payload est signé (HMAC) et envoyé.
4. La tentative de livraison est enregistrée.

Le transport HTTP est injecté via ``http_sender`` pour permettre
le mock en test sans aucun appel réseau réel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlmodel import Session

from brainrh.models.integration import (
    DeliveryStatus,
    OutboundEventDB,
    WebhookSubscriptionDB,
)
from brainrh.services.integration_event_service import IntegrationEventService


@dataclass
class DeliveryResult:
    """Résultat d'une tentative de livraison."""
    subscription_id: str
    target_url: str
    status: DeliveryStatus
    status_code: Optional[int]
    response_body: Optional[str]


# Type du sender HTTP injectable
HttpSender = Callable[[str, Dict[str, str], str], Tuple[int, str]]
"""(url, headers, body) -> (status_code, response_body)"""


def default_http_sender(url: str, headers: Dict[str, str], body: str) -> Tuple[int, str]:
    """Sender par défaut - ne fait rien (dev/test sécurité).

    En production, ce sender sera remplacé par un vrai client HTTP (httpx/requests).
    """
    raise NotImplementedError(
        "default_http_sender ne fait pas d'appels réseau. "
        "Injectez un vrai sender ou un mock."
    )


class WebhookDeliveryService:
    """Service de livraison de webhooks pour Zapier/Make.

    Utilise l'injection du sender HTTP pour être testable sans réseau.
    """

    @staticmethod
    def deliver_event(
        session: Session,
        event: OutboundEventDB,
        http_sender: HttpSender = default_http_sender,
    ) -> List[DeliveryResult]:
        """Livre un événement à toutes les souscriptions correspondantes.

        Returns:
            Liste des résultats de livraison (un par souscription).
        """
        subscriptions = IntegrationEventService.find_subscriptions_for_event(
            session, event.enterprise_id, event.event_type,
        )

        results: List[DeliveryResult] = []

        for sub in subscriptions:
            result = WebhookDeliveryService._deliver_to_subscription(
                session, event, sub, http_sender,
            )
            results.append(result)

        return results

    @staticmethod
    def _deliver_to_subscription(
        session: Session,
        event: OutboundEventDB,
        subscription: WebhookSubscriptionDB,
        http_sender: HttpSender,
    ) -> DeliveryResult:
        """Livre un événement à une souscription donnée."""

        # Construire le payload
        payload = {
            "event_id": event.id,
            "event_type": event.event_type,
            "enterprise_id": event.enterprise_id,
            "data": json.loads(event.payload_json),
            "created_at": event.created_at.isoformat(),
        }
        body = json.dumps(payload, default=str)

        # Construire les headers avec signature HMAC si available
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-BrainRH-Event": event.event_type,
        }
        if subscription.secret_ref:
            sig = IntegrationEventService.sign_payload(body, subscription.secret_ref)
            headers["X-BrainRH-Signature"] = sig

        # Envoyer
        try:
            status_code, response_body = http_sender(
                subscription.target_url, headers, body,
            )

            delivery_status = (
                DeliveryStatus.success if 200 <= status_code < 300
                else DeliveryStatus.failure
            )

        except Exception as exc:
            status_code = None
            response_body = str(exc)
            delivery_status = DeliveryStatus.failure

        # Enregistrer la tentative
        IntegrationEventService.record_delivery_attempt(
            session, event, subscription,
            status=delivery_status,
            status_code=status_code,
            response_body=response_body,
        )

        return DeliveryResult(
            subscription_id=subscription.id,
            target_url=subscription.target_url,
            status=delivery_status,
            status_code=status_code,
            response_body=response_body,
        )

    @staticmethod
    def process_pending_events(
        session: Session,
        enterprise_id: Optional[str] = None,
        http_sender: HttpSender = default_http_sender,
        limit: int = 50,
        excluded_event_types: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """Traite tous les événements pending pour un enterprise (ou tous).

        Returns:
            Résumé du traitement.
        """
        events = IntegrationEventService.list_pending_events(
            session,
            enterprise_id=enterprise_id,
            limit=limit,
            excluded_event_types=excluded_event_types,
        )

        total_deliveries = 0
        total_success = 0
        total_failures = 0

        for event in events:
            results = WebhookDeliveryService.deliver_event(
                session, event, http_sender,
            )
            for r in results:
                total_deliveries += 1
                if r.status == DeliveryStatus.success:
                    total_success += 1
                else:
                    total_failures += 1

        return {
            "events_processed": len(events),
            "total_deliveries": total_deliveries,
            "success": total_success,
            "failures": total_failures,
        }
