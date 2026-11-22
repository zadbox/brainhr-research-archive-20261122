"""Registry central des connecteurs d'intégration.

Le registry est un singleton fonctionnel :
- ``register()`` ajoute un connecteur.
- ``get()`` retourne un connecteur par son id.
- ``list_all()`` retourne tous les connecteurs enregistrés.
- ``list_available()`` retourne les connecteurs marqués ``is_available=True``.

L'enregistrement se fait au chargement du module ``providers``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .base import BaseConnector, ConnectorInfo


class ConnectorRegistry:
    """Registry thread-safe (dict simple, pas de concurrence en écriture)."""

    def __init__(self) -> None:
        self._connectors: Dict[str, BaseConnector] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, connector: BaseConnector) -> None:
        """Enregistre un connecteur dans le registry."""
        info = connector.info()
        if info.id in self._connectors or info.id in self._aliases:
            raise ValueError(f"Connector '{info.id}' already registered")
        self._connectors[info.id] = connector

    def register_alias(self, alias_id: str, connector_id: str) -> None:
        """Enregistre un alias qui résout vers un connecteur canonique."""
        if alias_id in self._connectors or alias_id in self._aliases:
            raise ValueError(f"Connector '{alias_id}' already registered")
        if connector_id not in self._connectors:
            raise ValueError(f"Connector '{connector_id}' is not registered")
        self._aliases[alias_id] = connector_id

    def _resolve_connector_id(self, connector_id: str) -> str:
        resolved_id = connector_id
        seen_ids = set()

        while resolved_id in self._aliases:
            if resolved_id in seen_ids:
                raise ValueError(f"Alias cycle detected for '{connector_id}'")
            seen_ids.add(resolved_id)
            resolved_id = self._aliases[resolved_id]

        return resolved_id

    def get(self, connector_id: str) -> Optional[BaseConnector]:
        """Retourne un connecteur par son identifiant, ou None."""
        return self._connectors.get(self._resolve_connector_id(connector_id))

    def canonicalize(self, connector_id: str) -> str:
        """Retourne l'identifiant canonique d'un connecteur ou de son alias."""
        return self._resolve_connector_id(connector_id)

    def equivalent_ids(self, connector_id: str) -> List[str]:
        """Retourne l'id canonique et tous ses alias connus."""
        canonical_id = self._resolve_connector_id(connector_id)
        ids = [canonical_id]
        ids.extend(
            alias_id for alias_id, target_id in self._aliases.items()
            if self._resolve_connector_id(target_id) == canonical_id
        )
        return ids

    def list_all(self) -> List[ConnectorInfo]:
        """Retourne les métadonnées de tous les connecteurs enregistrés."""
        return [c.info() for c in self._connectors.values()]

    def list_available(self) -> List[ConnectorInfo]:
        """Retourne uniquement les connecteurs disponibles (prêts à l'emploi)."""
        return [c.info() for c in self._connectors.values() if c.info().is_available]

    def list_by_family(self, family: str) -> List[ConnectorInfo]:
        """Retourne les connecteurs d'une famille donnée."""
        return [c.info() for c in self._connectors.values() if c.info().family.value == family]

    @property
    def count(self) -> int:
        return len(self._connectors)


# Instance globale du registry
registry = ConnectorRegistry()
