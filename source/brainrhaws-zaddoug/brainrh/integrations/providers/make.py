"""Connecteur canonique Make.com (webhook sortant no-code).

Le registry expose ce connecteur sous l'identifiant ``make``.
L'alias legacy ``zapier_make`` est géré au niveau du registry.
"""

from __future__ import annotations

from typing import Any, Dict, List

from brainrh.integrations.base import (
    BaseConnector,
    ConnectorCapability,
    ConnectorFamily,
    ConnectorInfo,
)


class MakeConnector(BaseConnector):
    """Connecteur webhook générique pour Make.com."""

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            id="make",
            name="Make",
            family=ConnectorFamily.NO_CODE,
            capabilities=[
                ConnectorCapability.OUTBOUND_WEBHOOK,
            ],
            description="Webhook sortant générique pour Make.com",
            is_available=True,
        )

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not config.get("webhook_url"):
            errors.append("webhook_url est requis")
        url = config.get("webhook_url", "")
        if url and not url.startswith("https://"):
            errors.append("webhook_url doit commencer par https://")
        return errors

    def test_connection(self, config: Dict[str, Any]) -> bool:
        # Ne fait aucun appel réseau réel — surchargé en production
        return False
