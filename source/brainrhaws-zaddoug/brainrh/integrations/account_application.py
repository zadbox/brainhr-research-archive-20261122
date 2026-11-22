"""Couche d'application des comptes d'intégration.

Cette couche porte le cas d'usage "accounts" hors du routeur FastAPI.
Elle reste intégrée au monolithe, mais sa surface est assez neutre pour
être réutilisée derrière un autre transport plus tard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from brainrh.models.auth import UserRole
from brainrh.models.integration import (
    ConnectorScopePolicy,
    ConnectorStatus,
    IntegrationAccountCreate,
    IntegrationAccountResponse,
    IntegrationScopeKind,
)
from brainrh.services.auth_service import TenantContext, tenant_has_any_role

import brainrh.integrations.providers  # noqa: F401 - bootstrap registry
from brainrh.integrations.registry import registry


@dataclass(frozen=True)
class IntegrationAccountRecord:
    id: str
    enterprise_id: Optional[str]
    scope_kind: IntegrationScopeKind
    scope_id: str
    connector_id: str
    status: ConnectorStatus
    config_json: str
    secret_ref: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IntegrationAccountAppError(Exception):
    status_code: int
    detail: Any


class IntegrationAccountStore(Protocol):
    def list_accounts(
        self,
        *,
        tenant_id: Optional[str] = None,
        legacy_enterprise_ids: Optional[list[str]] = None,
        include_platform: bool = True,
        include_all: bool = False,
    ) -> list[IntegrationAccountRecord]:
        ...

    def has_account_for_connector_ids(
        self,
        scope_kind: IntegrationScopeKind,
        scope_id: str,
        connector_ids: list[str],
    ) -> bool:
        ...

    def create_account(
        self,
        *,
        scope_kind: IntegrationScopeKind,
        scope_id: str,
        connector_id: str,
        config_json: str,
        status_value: ConnectorStatus,
        secret_ref: Optional[str],
    ) -> IntegrationAccountRecord:
        ...

    def get_scope_policy(self, connector_id: str) -> ConnectorScopePolicy:
        ...


def _normalize_secret_ref(secret_ref: Optional[str]) -> Optional[str]:
    if secret_ref is None:
        return None
    normalized = secret_ref.strip()
    return normalized or None


def _dump_config(config: Dict[str, Any]) -> str:
    return json.dumps(config, default=str, sort_keys=True)


def _serialize_account(account: IntegrationAccountRecord) -> IntegrationAccountResponse:
    connector_id = account.connector_id
    if registry.get(account.connector_id) is not None:
        connector_id = registry.canonicalize(account.connector_id)

    return IntegrationAccountResponse(
        id=account.id,
        enterprise_id=account.enterprise_id,
        tenant_id=account.scope_id if account.scope_kind == IntegrationScopeKind.client else None,
        scope_kind=account.scope_kind,
        scope_id=account.scope_id,
        connector_id=connector_id,
        status=account.status,
        config_json=account.config_json,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


class IntegrationAccountApplication:
    """Cas d'usage des comptes d'intégration, indépendant du transport."""

    def __init__(self, store: IntegrationAccountStore) -> None:
        self._store = store

    def list_accounts(
        self,
        tenant: TenantContext,
        *,
        tenant_id: Optional[str] = None,
        legacy_enterprise_ids: Optional[list[str]] = None,
    ) -> list[IntegrationAccountResponse]:
        is_platform_admin = tenant_has_any_role(tenant, {UserRole.platform_admin})
        resolved_tenant_id = tenant_id or tenant.tenant_id

        if not is_platform_admin and not resolved_tenant_id:
            raise IntegrationAccountAppError(
                status_code=400,
                detail="tenant_id requis pour consulter les intégrations client.",
            )

        return [
            _serialize_account(account)
            for account in self._store.list_accounts(
                tenant_id=resolved_tenant_id,
                legacy_enterprise_ids=legacy_enterprise_ids,
                include_platform=True,
                include_all=is_platform_admin and not resolved_tenant_id,
            )
        ]

    def create_account(
        self,
        tenant: TenantContext,
        payload: IntegrationAccountCreate,
        *,
        legacy_scope_ids: Optional[list[str]] = None,
    ) -> IntegrationAccountResponse:
        is_platform_admin = tenant_has_any_role(tenant, {UserRole.platform_admin})
        is_client_admin = tenant_has_any_role(tenant, {UserRole.client_admin})
        if not (is_platform_admin or is_client_admin):
            raise IntegrationAccountAppError(
                status_code=403,
                detail="Permissions insuffisantes pour gérer les intégrations.",
            )

        if payload.scope_kind == IntegrationScopeKind.enterprise_legacy:
            raise IntegrationAccountAppError(
                status_code=400,
                detail="La portée enterprise_legacy est réservée à la migration.",
            )

        if payload.scope_kind == IntegrationScopeKind.platform:
            if not is_platform_admin:
                raise IntegrationAccountAppError(
                    status_code=403,
                    detail="Seul un platform_admin peut créer une intégration globale.",
                )
            scope_id = "platform"
        else:
            scope_id = (payload.tenant_id or tenant.tenant_id or "").strip()
            if not scope_id:
                raise IntegrationAccountAppError(
                    status_code=400,
                    detail="tenant_id requis pour une intégration client.",
                )
            if not is_platform_admin and scope_id != tenant.tenant_id:
                raise IntegrationAccountAppError(
                    status_code=403,
                    detail="Accès interdit à ce client.",
                )

        connector_id = payload.connector_id.strip()
        if not connector_id:
            raise IntegrationAccountAppError(
                status_code=400,
                detail="connector_id est requis.",
            )

        connector = registry.get(connector_id)
        if connector is None:
            raise IntegrationAccountAppError(
                status_code=404,
                detail=f"Connecteur '{connector_id}' introuvable.",
            )

        info = connector.info()
        if info.id == "outlook":
            raise IntegrationAccountAppError(
                status_code=400,
                detail=(
                    "Les comptes Outlook doivent être créés par le parcours OAuth spécialisé; "
                    "la création générique est interdite."
                ),
            )
        if info.id == "turnover_it":
            raise IntegrationAccountAppError(
                status_code=400,
                detail=(
                    "Les comptes Turnover IT doivent être créés par le parcours token spécialisé; "
                    "la création générique est interdite."
                ),
            )

        if not info.is_available:
            raise IntegrationAccountAppError(
                status_code=400,
                detail=f"Connecteur '{info.id}' non disponible pour configuration.",
            )

        policy = self._store.get_scope_policy(info.id)
        allowed_scope_kinds = {
            ConnectorScopePolicy.client_only: {IntegrationScopeKind.client},
            ConnectorScopePolicy.platform_only: {IntegrationScopeKind.platform},
            ConnectorScopePolicy.client_or_platform: {
                IntegrationScopeKind.client,
                IntegrationScopeKind.platform,
            },
        }[policy]
        if payload.scope_kind not in allowed_scope_kinds:
            raise IntegrationAccountAppError(
                status_code=400,
                detail=(
                    f"La politique '{policy.value}' du connecteur '{info.id}' "
                    f"n'autorise pas la portée '{payload.scope_kind.value}'."
                ),
            )

        errors = connector.validate_config(payload.config)
        if errors:
            raise IntegrationAccountAppError(
                status_code=400,
                detail={"connector_id": info.id, "errors": errors},
            )

        canonical_connector_id = registry.canonicalize(info.id)
        equivalent_ids = registry.equivalent_ids(canonical_connector_id)
        if self._store.has_account_for_connector_ids(
            payload.scope_kind,
            scope_id,
            equivalent_ids,
        ):
            raise IntegrationAccountAppError(
                status_code=409,
                detail=(
                    f"Un compte '{canonical_connector_id}' existe déjà "
                    f"pour la portée {payload.scope_kind.value}:{scope_id}."
                ),
            )
        if payload.scope_kind == IntegrationScopeKind.client:
            for legacy_scope_id in legacy_scope_ids or []:
                if self._store.has_account_for_connector_ids(
                    IntegrationScopeKind.enterprise_legacy,
                    legacy_scope_id,
                    equivalent_ids,
                ):
                    raise IntegrationAccountAppError(
                        status_code=409,
                        detail=(
                            f"Une configuration historique '{canonical_connector_id}' "
                            "existe déjà pour une entreprise de ce client."
                        ),
                    )

        account = self._store.create_account(
            scope_kind=payload.scope_kind,
            scope_id=scope_id,
            connector_id=canonical_connector_id,
            config_json=_dump_config(payload.config),
            status_value=payload.status,
            secret_ref=_normalize_secret_ref(payload.secret_ref),
        )
        return _serialize_account(account)
