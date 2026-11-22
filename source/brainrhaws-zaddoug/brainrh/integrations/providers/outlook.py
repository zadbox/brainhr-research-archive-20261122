"""Fondation du connecteur Microsoft Outlook / O365.

Cette tranche déclare le connecteur et son contrat de configuration serveur,
mais n'essaie pas de simuler une autorisation OAuth. Les secrets Microsoft
restent exclusivement dans l'environnement du backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from brainrh.integrations.base import (
    BaseConnector,
    ConnectorCapability,
    ConnectorFamily,
    ConnectorInfo,
)


class OutlookSetupState(str, Enum):
    configuration_required = "configuration_required"
    authorization_unavailable = "authorization_unavailable"


@dataclass(frozen=True)
class OutlookOAuthConfiguration:
    setup_state: OutlookSetupState
    missing_settings: tuple[str, ...]
    oauth_start_available: bool = False


OUTLOOK_REQUIRED_SETTINGS = (
    "MICROSOFT_OUTLOOK_CLIENT_ID",
    "MICROSOFT_OUTLOOK_CLIENT_SECRET",
    "MICROSOFT_OUTLOOK_REDIRECT_URI",
)


def get_outlook_oauth_configuration() -> OutlookOAuthConfiguration:
    """Retourne uniquement l'état de présence des settings, jamais leur valeur."""
    missing = tuple(
        setting_name
        for setting_name in OUTLOOK_REQUIRED_SETTINGS
        if not (os.getenv(setting_name) or "").strip()
    )
    if missing:
        return OutlookOAuthConfiguration(
            setup_state=OutlookSetupState.configuration_required,
            missing_settings=missing,
        )
    return OutlookOAuthConfiguration(
        setup_state=OutlookSetupState.authorization_unavailable,
        missing_settings=(),
    )


class OutlookConnector(BaseConnector):
    """Connecteur concret dont l'activation passe exclusivement par OAuth."""

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            id="outlook",
            name="Microsoft Outlook / O365",
            family=ConnectorFamily.COLLABORATION,
            capabilities=[ConnectorCapability.OAUTH2],
            description="Microsoft Outlook and Microsoft 365 OAuth connection",
            is_available=False,
        )

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        del config
        return ["Outlook accounts must be created through the specialized OAuth flow"]
