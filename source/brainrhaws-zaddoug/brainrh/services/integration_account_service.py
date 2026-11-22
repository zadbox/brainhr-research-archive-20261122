"""Adaptateur SQL pour les comptes de connecteurs BrainRH."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from brainrh.integrations.account_application import (
    IntegrationAccountRecord,
    IntegrationAccountStore,
)
from brainrh.models.integration import (
    ConnectorScopePolicy,
    ConnectorScopePolicyDB,
    ConnectorStatus,
    IntegrationAccountDB,
    IntegrationScopeKind,
)


def _to_record(account: IntegrationAccountDB) -> IntegrationAccountRecord:
    return IntegrationAccountRecord(
        id=account.id,
        enterprise_id=account.enterprise_id,
        scope_kind=account.scope_kind,
        scope_id=account.scope_id,
        connector_id=account.connector_id,
        status=account.status,
        config_json=account.config_json,
        secret_ref=account.secret_ref,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


class SqlIntegrationAccountStore(IntegrationAccountStore):
    """Persistance SQLModel pour le cas d'usage des comptes d'intégration."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_accounts(
        self,
        *,
        tenant_id: Optional[str] = None,
        legacy_enterprise_ids: Optional[list[str]] = None,
        include_platform: bool = True,
        include_all: bool = False,
    ) -> list[IntegrationAccountRecord]:
        stmt = select(IntegrationAccountDB)
        if not include_all:
            scope_filters = []
            if tenant_id:
                scope_filters.append(
                    (
                        IntegrationAccountDB.scope_kind == IntegrationScopeKind.client,
                        IntegrationAccountDB.scope_id == tenant_id,
                    )
                )
            if include_platform:
                scope_filters.append(
                    (
                        IntegrationAccountDB.scope_kind == IntegrationScopeKind.platform,
                        IntegrationAccountDB.scope_id == "platform",
                    )
                )
            if legacy_enterprise_ids:
                scope_filters.append(
                    (
                        IntegrationAccountDB.scope_kind == IntegrationScopeKind.enterprise_legacy,
                        IntegrationAccountDB.scope_id.in_(legacy_enterprise_ids),
                    )
                )

            if not scope_filters:
                return []

            stmt = stmt.where(
                or_(*[condition[0] & condition[1] for condition in scope_filters])
            )

        stmt = stmt.order_by(
            IntegrationAccountDB.scope_kind,
            IntegrationAccountDB.scope_id,
            IntegrationAccountDB.connector_id,
        )
        accounts = self._session.exec(stmt).all()
        return [_to_record(account) for account in accounts]

    def has_account_for_connector_ids(
        self,
        scope_kind: IntegrationScopeKind,
        scope_id: str,
        connector_ids: list[str],
    ) -> bool:
        stmt = select(IntegrationAccountDB).where(
            IntegrationAccountDB.scope_kind == scope_kind,
            IntegrationAccountDB.scope_id == scope_id,
            IntegrationAccountDB.connector_id.in_(connector_ids),
        )
        return self._session.exec(stmt).first() is not None

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
        account = IntegrationAccountDB(
            scope_kind=scope_kind,
            scope_id=scope_id,
            connector_id=connector_id,
            status=status_value,
            config_json=config_json,
            secret_ref=secret_ref,
        )
        self._session.add(account)
        self._session.flush()
        return _to_record(account)

    def get_scope_policy(self, connector_id: str) -> ConnectorScopePolicy:
        policy = self._session.get(ConnectorScopePolicyDB, connector_id)
        if policy is None:
            return ConnectorScopePolicy.client_only
        return ConnectorScopePolicy(policy.scope_policy)
