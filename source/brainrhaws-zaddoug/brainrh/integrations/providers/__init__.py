"""Auto-registration de tous les connecteurs dans le registry global.

Importer ce module suffit à peupler ``registry`` avec :
- le connecteur canonique Make (disponible) ;
- l'alias legacy ``zapier_make`` résolu par le registry ;
- tous les stubs (non-disponibles).
"""

from brainrh.integrations.registry import registry
from brainrh.integrations.providers.make import MakeConnector
from brainrh.integrations.providers.outlook import OutlookConnector
from brainrh.integrations.providers.turnover_it import TurnoverITConnector
from brainrh.integrations.providers.stubs import ALL_STUBS


def _bootstrap_registry() -> None:
    """Enregistre tous les connecteurs connus dans le registry global."""
    if registry.count > 0:
        return  # déjà initialisé
    registry.register(MakeConnector())
    registry.register(TurnoverITConnector())
    registry.register(OutlookConnector())
    registry.register_alias("zapier_make", "make")
    for stub in ALL_STUBS:
        registry.register(stub)


_bootstrap_registry()
