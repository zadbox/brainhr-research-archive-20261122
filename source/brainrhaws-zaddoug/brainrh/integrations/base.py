"""Interface de base pour tous les connecteurs BrainRH.

Chaque connecteur concret (Zapier, LinkedIn, Slack…) doit implémenter
``BaseConnector``. Aucun appel réseau ne doit se produire
dans ce module — les connecteurs concrets gèrent eux-mêmes le transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ConnectorCapability(str, Enum):
    """Capacités qu'un connecteur peut déclarer."""
    OUTBOUND_WEBHOOK = "outbound_webhook"
    INBOUND_WEBHOOK = "inbound_webhook"
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    POLLING = "polling"
    BIDIRECTIONAL_SYNC = "bidirectional_sync"


class ConnectorFamily(str, Enum):
    """Famille d'intégration à laquelle appartient un connecteur."""
    WEBHOOK = "webhook"
    NO_CODE = "no_code"
    SOURCING = "sourcing"
    SIRH_FR = "sirh_fr"
    SIRH_INT = "sirh_int"
    COLLABORATION = "collaboration"
    SIGNATURE = "signature"
    ASSESSMENT = "assessment"
    BACKGROUND_CHECK = "background_check"
    JOBBOARD = "jobboard"


@dataclass(frozen=True)
class ConnectorInfo:
    """Métadonnées statiques décrivant un connecteur."""
    id: str
    name: str
    family: ConnectorFamily
    capabilities: List[ConnectorCapability] = field(default_factory=list)
    description: str = ""
    is_available: bool = False  # prêt à être configuré


class BaseConnector(ABC):
    """Interface commune pour tous les connecteurs d'intégration.

    Les méthodes sont volontairement simples :
    - ``info()``      : retourne les métadonnées statiques du connecteur.
    - ``validate_config()`` : vérifie qu'une configuration est complète / cohérente.
    - ``test_connection()`` : effectue un test de connectivité basique (sera mocké en test).
    """

    @abstractmethod
    def info(self) -> ConnectorInfo:
        """Retourne les métadonnées du connecteur."""
        ...

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Vérifie la configuration donnée.

        Retourne une liste vide si valide, sinon la liste des erreurs.
        """
        ...

    def test_connection(self, config: Dict[str, Any]) -> bool:
        """Teste la connexion avec la configuration donnée.

        Par défaut retourne False (pas de connectivité).
        Les connecteurs concrets surchargent cette méthode.
        """
        return False
