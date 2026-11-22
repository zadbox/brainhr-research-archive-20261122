from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from brainrh.models.crustdata import CrustdataCreditOperationDB, CrustdataWalletDB
from brainrh.settings import get_crustdata_operation_lease_seconds


PLATFORM_SCOPE_ID = "platform"


class InsufficientCreditsError(ValueError):
    pass


@dataclass(frozen=True)
class ReservationResult:
    operation: CrustdataCreditOperationDB
    acquired: bool


def request_fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CreditLedgerService:
    @staticmethod
    def _operation(session: Session, operation_id: str, *, lock: bool = False) -> CrustdataCreditOperationDB | None:
        statement = select(CrustdataCreditOperationDB).where(
            CrustdataCreditOperationDB.operation_id == operation_id
        )
        if lock and session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.exec(statement).first()

    @staticmethod
    def _validate_operation(operation: CrustdataCreditOperationDB, *, tenant_id: str, user_id: str,
                            project_id: str | None, operation_type: str, fingerprint: str) -> None:
        if (operation.tenant_id != tenant_id or operation.user_id != user_id
                or operation.project_id != project_id or operation.operation_type != operation_type):
            raise ValueError("operation_id déjà utilisé dans un autre contexte")
        if operation.request_fingerprint != fingerprint:
            raise ValueError("operation_id déjà utilisé pour une requête différente")

    @staticmethod
    def _expire_if_needed(session: Session, operation: CrustdataCreditOperationDB) -> CrustdataCreditOperationDB:
        created_at = operation.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        if operation.status == "reserved" and age > get_crustdata_operation_lease_seconds():
            operation.status = "pending_reconciliation"
            operation.error_code = "RESERVATION_EXPIRED"
            operation.completed_at = datetime.now(timezone.utc)
            session.add(operation); session.commit(); session.refresh(operation)
        return operation

    @staticmethod
    def _wallet(session: Session, scope_kind: str, scope_id: str, *, lock: bool = False) -> CrustdataWalletDB | None:
        statement = select(CrustdataWalletDB).where(
            CrustdataWalletDB.scope_kind == scope_kind, CrustdataWalletDB.scope_id == scope_id
        )
        if lock and session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.exec(statement).first()

    @staticmethod
    def reserve(session: Session, *, operation_id: str, tenant_id: str, user_id: str, project_id: str | None,
                operation_type: str, requested_count: int, estimated: Decimal,
                fingerprint: str) -> ReservationResult:
        existing = CreditLedgerService._operation(session, operation_id)
        if existing:
            CreditLedgerService._validate_operation(existing, tenant_id=tenant_id, user_id=user_id,
                project_id=project_id, operation_type=operation_type, fingerprint=fingerprint)
            # Le lookup initial est indicatif seulement; la décision se prend
            # après les locks canoniques et un second lookup de l'opération.
        global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID, lock=True)
        tenant_wallet = CreditLedgerService._wallet(session, "tenant", tenant_id, lock=True)
        if not global_wallet or not tenant_wallet:
            raise InsufficientCreditsError("Wallet Crustdata non initialisé")
        existing = CreditLedgerService._operation(session, operation_id, lock=True)
        if existing:
            CreditLedgerService._validate_operation(existing, tenant_id=tenant_id, user_id=user_id,
                project_id=project_id, operation_type=operation_type, fingerprint=fingerprint)
            return ReservationResult(CreditLedgerService._expire_if_needed(session, existing), False)
        if min(global_wallet.balance - global_wallet.reserved, tenant_wallet.balance - tenant_wallet.reserved) < estimated:
            raise InsufficientCreditsError("Crédits insuffisants")
        global_wallet.reserved += estimated
        tenant_wallet.reserved += estimated
        operation = CrustdataCreditOperationDB(
            operation_id=operation_id, request_fingerprint=fingerprint,
            tenant_id=tenant_id, user_id=user_id, project_id=project_id,
            operation_type=operation_type, requested_count=requested_count, estimated_credits=estimated,
            provider_balance_before_or_last_known=global_wallet.balance,
        )
        session.add(global_wallet); session.add(tenant_wallet); session.add(operation); session.commit(); session.refresh(operation)
        return ReservationResult(operation, True)

    @staticmethod
    def settle(session: Session, operation: CrustdataCreditOperationDB, *, reported: Decimal | None,
               returned_count: int, error_code: str | None = None) -> CrustdataCreditOperationDB:
        # Ordre de verrouillage canonique: wallet global -> wallet tenant -> opération.
        global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID, lock=True)
        tenant_wallet = CreditLedgerService._wallet(session, "tenant", operation.tenant_id, lock=True)
        if not global_wallet or not tenant_wallet:
            raise RuntimeError("Wallet réservé introuvable")
        current = CreditLedgerService._operation(session, operation.operation_id, lock=True)
        if current is None:
            raise RuntimeError("Opération de crédit introuvable")
        if current.status != "reserved":
            return current
        reserved = Decimal(current.estimated_credits)
        current.returned_or_matched_count = returned_count
        current.reported_credits_exact = reported
        current.error_code = error_code
        current.completed_at = datetime.now(timezone.utc)
        if reported is None:
            current.status = "pending_reconciliation"
        else:
            actual = Decimal(reported)
            global_wallet.reserved = max(Decimal("0"), global_wallet.reserved - reserved)
            tenant_wallet.reserved = max(Decimal("0"), tenant_wallet.reserved - reserved)
            global_wallet.balance -= actual
            tenant_wallet.balance -= actual
            current.settled_credits = actual
            current.status = "settled"
        current.provider_balance_after_or_next_sync = global_wallet.balance
        global_wallet.updated_at = tenant_wallet.updated_at = datetime.now(timezone.utc)
        session.add(global_wallet); session.add(tenant_wallet); session.add(current); session.commit(); session.refresh(current)
        return current

    @staticmethod
    def release(session: Session, operation: CrustdataCreditOperationDB, error_code: str) -> CrustdataCreditOperationDB:
        # Même ordre que reserve/settle/reconcile pour éviter les cycles de locks.
        global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID, lock=True)
        tenant_wallet = CreditLedgerService._wallet(session, "tenant", operation.tenant_id, lock=True)
        current = CreditLedgerService._operation(session, operation.operation_id, lock=True)
        if current is None:
            raise RuntimeError("Opération de crédit introuvable")
        if current.status != "reserved":
            return current
        reserved = Decimal(current.estimated_credits)
        if global_wallet:
            global_wallet.reserved = max(Decimal("0"), global_wallet.reserved - reserved); session.add(global_wallet)
        if tenant_wallet:
            tenant_wallet.reserved = max(Decimal("0"), tenant_wallet.reserved - reserved); session.add(tenant_wallet)
        current.status = "released"; current.error_code = error_code; current.completed_at = datetime.now(timezone.utc)
        session.add(current); session.commit(); session.refresh(current)
        return current

    @staticmethod
    def upsert_wallet(session: Session, scope_kind: str, scope_id: str, balance: Decimal) -> CrustdataWalletDB:
        wallet = CreditLedgerService._wallet(session, scope_kind, scope_id)
        if wallet is None:
            wallet = CrustdataWalletDB(scope_kind=scope_kind, scope_id=scope_id, balance=balance)
        else:
            wallet.balance = balance; wallet.updated_at = datetime.now(timezone.utc)
        session.add(wallet); session.commit(); session.refresh(wallet); return wallet

    @staticmethod
    def sync_platform_wallet(session: Session, balance: Decimal) -> CrustdataWalletDB:
        wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID, lock=True)
        if wallet is None:
            wallet = CrustdataWalletDB(scope_kind="platform", scope_id=PLATFORM_SCOPE_ID, balance=balance)
        else:
            wallet.balance = balance
        wallet.provider_last_synced_at = datetime.now(timezone.utc)
        wallet.updated_at = datetime.now(timezone.utc)
        session.add(wallet); session.commit(); session.refresh(wallet)
        return wallet

    @staticmethod
    def reconcile(session: Session, operation: CrustdataCreditOperationDB, *, actual: Decimal,
                  provider_balance: Decimal) -> CrustdataCreditOperationDB:
        # Ordre canonique partagé avec toutes les transitions payantes.
        global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID, lock=True)
        tenant_wallet = CreditLedgerService._wallet(session, "tenant", operation.tenant_id, lock=True)
        if not global_wallet or not tenant_wallet:
            raise RuntimeError("Wallet réservé introuvable")
        current = CreditLedgerService._operation(session, operation.operation_id, lock=True)
        if current is None or current.status != "pending_reconciliation":
            raise ValueError("Seule une opération pending_reconciliation peut être réconciliée")
        reserved = Decimal(current.estimated_credits)
        global_wallet.reserved = max(Decimal("0"), global_wallet.reserved - reserved)
        tenant_wallet.reserved = max(Decimal("0"), tenant_wallet.reserved - reserved)
        global_wallet.balance = provider_balance
        global_wallet.provider_last_synced_at = datetime.now(timezone.utc)
        tenant_wallet.balance -= actual
        now = datetime.now(timezone.utc)
        global_wallet.updated_at = tenant_wallet.updated_at = now
        current.reported_credits_exact = actual
        current.settled_credits = actual
        current.provider_balance_after_or_next_sync = provider_balance
        current.status = "settled"
        current.error_code = None
        current.completed_at = now
        if current.response_json:
            payload = json.loads(current.response_json)
            if isinstance(payload, dict) and isinstance(payload.get("credits"), dict):
                available = min(
                    global_wallet.balance - global_wallet.reserved,
                    tenant_wallet.balance - tenant_wallet.reserved,
                )
                payload["credits"].update({
                    "consumed": str(actual), "available": str(available),
                    "status": "settled", "error_code": None,
                })
                current.response_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        session.add(global_wallet); session.add(tenant_wallet); session.add(current)
        session.commit(); session.refresh(current)
        return current

    @staticmethod
    def store_response(session: Session, operation: CrustdataCreditOperationDB, response: object) -> None:
        if hasattr(response, "model_dump"):
            payload = response.model_dump(mode="json")
        else:
            payload = response
        operation.response_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        session.add(operation); session.commit()

    @staticmethod
    def parse_balance(payload: object) -> Decimal:
        if isinstance(payload, dict):
            account = payload.get("account")
            if isinstance(account, dict) and "credits" in account:
                try: return Decimal(str(account["credits"]))
                except InvalidOperation: pass
            for key in ("credits", "balance", "credit_balance"):
                if key in payload:
                    try: return Decimal(str(payload[key]))
                    except InvalidOperation: break
        raise ValueError("Solde Crustdata invalide")

    @staticmethod
    def available(session: Session, tenant_id: str) -> Decimal | None:
        global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID)
        tenant_wallet = CreditLedgerService._wallet(session, "tenant", tenant_id)
        if not global_wallet or not tenant_wallet:
            return None
        return min(global_wallet.balance - global_wallet.reserved, tenant_wallet.balance - tenant_wallet.reserved)
