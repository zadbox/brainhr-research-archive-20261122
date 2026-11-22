"""Connecteur Turnover IT.

Connecteur disponible pour préparer une intégration tokenisée.
Les secrets restent hors du config JSON et passent par ``secret_ref``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from brainrh.integrations.base import (
    BaseConnector,
    ConnectorCapability,
    ConnectorFamily,
    ConnectorInfo,
)


TURNOVER_API_BASE_URL = "https://api.turnover-it.com/jobconnect/v2"


class TurnoverITConnector(BaseConnector):
    """Connecteur tokenisé Turnover IT.

    La base fournisseur est fixe et le compte est configuré exclusivement par
    les routes spécialisées, avec un token référencé dans SSM SecureString.
    """

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            id="turnover_it",
            name="Turnover IT",
            family=ConnectorFamily.JOBBOARD,
            capabilities=[
                ConnectorCapability.API_KEY,
                ConnectorCapability.POLLING,
            ],
            description=(
                "Turnover IT JobConnect v2 client integration backed by an SSM token."
            ),
            is_available=True,
        )

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        if not config:
            return []
        if config == {"api_base_url": TURNOVER_API_BASE_URL}:
            return []
        return ["Turnover IT configuration is fixed and must use the specialized setup route"]

    def test_connection(self, config: Dict[str, Any]) -> bool:
        return False
