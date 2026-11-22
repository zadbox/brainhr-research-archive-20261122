"""Connecteurs stub pour les familles déclarées mais pas encore implémentées.

Chaque stub est marqué ``is_available=False``. Ils servent à :
- peupler le registry avec la liste complète des intégrations prévues ;
- permettre à l'API ``GET /connectors`` de les lister dès maintenant.
"""

from __future__ import annotations

from typing import Any, Dict, List

from brainrh.integrations.base import (
    BaseConnector,
    ConnectorCapability,
    ConnectorFamily,
    ConnectorInfo,
)


def _stub(
    connector_id: str,
    name: str,
    family: ConnectorFamily,
    capabilities: List[ConnectorCapability] | None = None,
    description: str = "",
) -> BaseConnector:
    """Fabrique un connecteur stub non-disponible."""
    caps = capabilities or []

    class _Stub(BaseConnector):
        def info(self) -> ConnectorInfo:
            return ConnectorInfo(
                id=connector_id,
                name=name,
                family=family,
                capabilities=caps,
                description=description,
                is_available=False,
            )

        def validate_config(self, config: Dict[str, Any]) -> List[str]:
            return [f"Connector '{connector_id}' is not yet implemented"]

    return _Stub()


# --- Sourcing & Réseaux ---
linkedin_stub = _stub("linkedin", "LinkedIn RSC", ConnectorFamily.SOURCING,
                       [ConnectorCapability.OAUTH2, ConnectorCapability.BIDIRECTIONAL_SYNC],
                       "LinkedIn Recruiter System Connect")

# --- Jobboards ---
jobboard_multipost_stub = _stub("jobboard_multipost", "Jobboard Multiposting",
                                 ConnectorFamily.JOBBOARD,
                                 [ConnectorCapability.API_KEY],
                                 "Multiposting vers 80-150 jobboards")

# --- SIRH FR ---
cegid_stub = _stub("cegid", "Cegid", ConnectorFamily.SIRH_FR, [ConnectorCapability.API_KEY])
lucca_stub = _stub("lucca", "Lucca", ConnectorFamily.SIRH_FR, [ConnectorCapability.API_KEY])
silae_stub = _stub("silae", "Silae", ConnectorFamily.SIRH_FR, [ConnectorCapability.API_KEY])
sage_stub = _stub("sage", "Sage", ConnectorFamily.SIRH_FR, [ConnectorCapability.API_KEY])
payfit_stub = _stub("payfit", "Payfit", ConnectorFamily.SIRH_FR, [ConnectorCapability.OAUTH2])
personio_stub = _stub("personio", "Personio", ConnectorFamily.SIRH_FR, [ConnectorCapability.OAUTH2])

# --- SIRH INT ---
workday_stub = _stub("workday", "Workday", ConnectorFamily.SIRH_INT, [ConnectorCapability.OAUTH2])
bamboohr_stub = _stub("bamboohr", "BambooHR", ConnectorFamily.SIRH_INT, [ConnectorCapability.API_KEY])
adp_stub = _stub("adp", "ADP", ConnectorFamily.SIRH_INT, [ConnectorCapability.OAUTH2])
sap_sf_stub = _stub("sap_sf", "SAP SuccessFactors", ConnectorFamily.SIRH_INT, [ConnectorCapability.OAUTH2])
oracle_hcm_stub = _stub("oracle_hcm", "Oracle HCM", ConnectorFamily.SIRH_INT, [ConnectorCapability.OAUTH2])
ukg_stub = _stub("ukg", "UKG", ConnectorFamily.SIRH_INT, [ConnectorCapability.OAUTH2])
rippling_stub = _stub("rippling", "Rippling", ConnectorFamily.SIRH_INT, [ConnectorCapability.API_KEY])

# --- Collaboration ---
slack_stub = _stub("slack", "Slack", ConnectorFamily.COLLABORATION,
                   [ConnectorCapability.OUTBOUND_WEBHOOK, ConnectorCapability.OAUTH2])
ms_teams_stub = _stub("ms_teams", "Microsoft Teams", ConnectorFamily.COLLABORATION,
                       [ConnectorCapability.OUTBOUND_WEBHOOK, ConnectorCapability.OAUTH2])
google_workspace_stub = _stub("google_workspace", "Google Workspace", ConnectorFamily.COLLABORATION,
                              [ConnectorCapability.OAUTH2])
calendly_stub = _stub("calendly", "Calendly", ConnectorFamily.COLLABORATION,
                       [ConnectorCapability.OAUTH2])
zoom_stub = _stub("zoom", "Zoom", ConnectorFamily.COLLABORATION,
                  [ConnectorCapability.OAUTH2])

# --- Signature ---
yousign_stub = _stub("yousign", "Yousign", ConnectorFamily.SIGNATURE, [ConnectorCapability.API_KEY])
docusign_stub = _stub("docusign", "DocuSign", ConnectorFamily.SIGNATURE, [ConnectorCapability.OAUTH2])
hellosign_stub = _stub("hellosign", "HelloSign", ConnectorFamily.SIGNATURE, [ConnectorCapability.API_KEY])

# --- Assessment ---
testgorilla_stub = _stub("testgorilla", "TestGorilla", ConnectorFamily.ASSESSMENT, [ConnectorCapability.API_KEY])
codility_stub = _stub("codility", "Codility", ConnectorFamily.ASSESSMENT, [ConnectorCapability.API_KEY])
hackerrank_stub = _stub("hackerrank", "HackerRank", ConnectorFamily.ASSESSMENT, [ConnectorCapability.API_KEY])

# --- Background Check ---
checkr_stub = _stub("checkr", "Checkr", ConnectorFamily.BACKGROUND_CHECK, [ConnectorCapability.API_KEY])

# Liste complète pour auto-registration
ALL_STUBS = [
    linkedin_stub, jobboard_multipost_stub,
    cegid_stub, lucca_stub, silae_stub, sage_stub, payfit_stub, personio_stub,
    workday_stub, bamboohr_stub, adp_stub, sap_sf_stub, oracle_hcm_stub, ukg_stub, rippling_stub,
    slack_stub, ms_teams_stub, google_workspace_stub, calendly_stub, zoom_stub,
    yousign_stub, docusign_stub, hellosign_stub,
    testgorilla_stub, codility_stub, hackerrank_stub,
    checkr_stub,
]
