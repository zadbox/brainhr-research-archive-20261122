"""Compatibilité legacy pour l'ancien provider ``zapier_make``.

Le connecteur canonique est désormais ``make``. Le registry expose
``zapier_make`` comme alias du connecteur canonique.
"""

from brainrh.integrations.providers.make import MakeConnector


class ZapierMakeConnector(MakeConnector):
    """Alias legacy du connecteur canonique Make."""


__all__ = ["MakeConnector", "ZapierMakeConnector"]
