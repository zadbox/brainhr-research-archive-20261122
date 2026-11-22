"""Worker background asyncio pour traiter l'outbox des webhooks (INTEG-007)."""

import asyncio
import logging
from sqlmodel import Session, select

from brainrh.database import engine
from brainrh.models.integration import EventStatus, OutboundEventDB
from brainrh.services.turnover_it_delivery_service import deliver_turnover_publication_event
from brainrh.services.turnover_it_service import TURNOVER_PUBLICATION_EVENT
from brainrh.services.webhook_delivery_service import WebhookDeliveryService
from brainrh.services.http_webhook_sender import httpx_sender

logger = logging.getLogger(__name__)

async def outbox_worker_loop(
    interval_seconds: int = 15,
    *,
    process_generic: bool = True,
    process_turnover: bool = True,
):
    """Boucle infinie qui scrute l'outbox et envoie les événements.

    À utiliser comme tâche de fond dans FastAPI via lifespan.
    """
    logger.info(f"Démarrage de l'Outbox Worker (interval: {interval_seconds}s)")

    while True:
        try:
            # Exécution synchrone dans un thread pour ne pas bloquer l'Event Loop FastAPI
            result = await asyncio.to_thread(
                _process_batch,
                process_generic=process_generic,
                process_turnover=process_turnover,
            )

            if result and result.get("events_processed", 0) > 0:
                logger.info(
                    f"Outbox traitée: {result['events_processed']} evt(s), "
                    f"Livraisons: {result['total_deliveries']} "
                    f"(Succès: {result.get('success', 0)}, Échecs: {result.get('failures', 0)})"
                )

        except asyncio.CancelledError:
            logger.info("Outbox Worker annulé / arrêté.")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans l'Outbox Worker : {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)

def _process_batch(
    *,
    process_generic: bool = True,
    process_turnover: bool = True,
) -> dict:
    """Fonction synchrone interne pour process_pending_events."""
    with Session(engine) as session:
        provider_events = []
        if process_turnover:
            provider_events = list(
                session.exec(
                    select(OutboundEventDB)
                    .where(
                        OutboundEventDB.event_type == TURNOVER_PUBLICATION_EVENT,
                        OutboundEventDB.status.in_([EventStatus.pending, EventStatus.retrying]),
                    )
                    .order_by(OutboundEventDB.created_at)
                    .limit(50)
                ).all()
            )
        provider_success = 0
        for event in provider_events:
            if deliver_turnover_publication_event(session, event):
                provider_success += 1

        result = {
            "events_processed": 0,
            "total_deliveries": 0,
            "success": 0,
            "failures": 0,
        }
        if process_generic:
            result = WebhookDeliveryService.process_pending_events(
                session=session,
                enterprise_id=None,
                http_sender=httpx_sender,
                limit=50,
                excluded_event_types={TURNOVER_PUBLICATION_EVENT},
            )
        session.commit()
        result["events_processed"] += len(provider_events)
        result["total_deliveries"] += len(provider_events)
        result["success"] += provider_success
        result["failures"] += len(provider_events) - provider_success
        return result
