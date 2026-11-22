from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from api.dependencies import get_current_user, get_project_writer_context, require_project_writer
from brainrh.database import get_session_dependency
from brainrh.models.auth import TenantDB, UserDB, UserRole
from brainrh.models.crustdata import CrustdataCreditOperationDB, CrustdataSearchSessionDB, CrustdataWalletDB
from brainrh.models.project import ProjectDB
from brainrh.schemas.crustdata import (
    AutocompleteRequest, CreditReconcileRequest, CriteriaPatch, CriteriaResponse, ImportRequest, ImportResponse,
    NextSearchRequest, SearchRequest, SearchResponse, TenantWalletUpdate,
)
from brainrh.services.auth_service import TenantContext
from brainrh.services.audit_service import AuditService
from brainrh.services.crustdata_client import CrustdataClient, CrustdataError
from brainrh.services.crustdata_credit_service import CreditLedgerService, InsufficientCreditsError, PLATFORM_SCOPE_ID
from brainrh.services.crustdata_criteria_service import CrustdataCriteriaService
from brainrh.services.crustdata_import_service import CandidateImportService
from brainrh.services.crustdata_search_service import CandidateSearchService
from brainrh.settings import get_crustdata_person_enrich_base_cost, get_crustdata_search_cost_per_result


router = APIRouter()


def normalize_autocomplete_suggestions(data: object) -> list[str]:
    if isinstance(data, dict):
        data = data.get("suggestions", [])
    if not isinstance(data, list):
        return []
    values = [item.get("value") if isinstance(item, dict) else item for item in data]
    return [str(item) for item in values if item is not None]


def _scope(tenant: TenantContext) -> tuple[str, str]:
    if not tenant.tenant_id or not tenant.enterprise_id:
        raise HTTPException(400, "Contexte tenant et entreprise obligatoire.")
    return tenant.tenant_id, tenant.enterprise_id


def _criteria_row(session: Session, tenant: TenantContext, project_id: str):
    tenant_id, enterprise_id = _scope(tenant)
    row = CrustdataCriteriaService.find(session, tenant_id, enterprise_id, project_id)
    if row is None: raise HTTPException(404, "Critères Crustdata introuvables.")
    return row


def _provider_error(exc: CrustdataError) -> HTTPException:
    return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})


def raise_for_search_response_error(response: SearchResponse) -> None:
    code = response.credits.error_code
    if not code:
        return
    status_by_code = {
        "INVALID_REQUEST": 400, "INVALID_API_KEY": 401, "INSUFFICIENT_CREDITS": 402,
        "PERMISSION_DENIED": 403, "RATE_LIMITED": 429, "PROVIDER_TIMEOUT": 503,
        "PROVIDER_TEMPORARY_FAILURE": 503, "LOCAL_PROCESSING_ERROR": 500,
        "OPERATION_IN_PROGRESS": 409, "RESERVATION_EXPIRED": 503,
    }
    raise HTTPException(status_by_code.get(code, 502), {"code": code, "message": "Opération Crustdata échouée."})


def raise_for_import_response_error(response: ImportResponse) -> None:
    if response.imported_count > 0 or not response.credits.error_code:
        return
    code = response.credits.error_code
    status_by_code = {
        "INVALID_REQUEST": 400, "INVALID_API_KEY": 401, "INSUFFICIENT_CREDITS": 402,
        "PERMISSION_DENIED": 403, "RATE_LIMITED": 429, "PROVIDER_TIMEOUT": 503,
        "PROVIDER_TEMPORARY_FAILURE": 503, "PROVIDER_ERROR": 503,
        "OPERATION_IN_PROGRESS": 409, "RESERVATION_EXPIRED": 503,
    }
    raise HTTPException(status_by_code.get(code, 502), {"code": code, "message": "Import Crustdata échoué."})


def _require_platform_admin(user: UserDB) -> None:
    if user.role != UserRole.platform_admin:
        raise HTTPException(403, "Administrateur plateforme requis.")


@router.get("/projects/{project_id}/criteria", response_model=CriteriaResponse)
async def get_criteria(project_id: str, tenant: TenantContext = Depends(get_project_writer_context),
                       session: Session = Depends(get_session_dependency)):
    tenant_id, enterprise_id = _scope(tenant)
    return await CrustdataCriteriaService.get_or_create(session, tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id)


@router.patch("/projects/{project_id}/criteria", response_model=CriteriaResponse)
def patch_criteria(project_id: str, body: CriteriaPatch, tenant: TenantContext = Depends(get_project_writer_context),
                   session: Session = Depends(get_session_dependency)):
    return CrustdataCriteriaService.update(session, _criteria_row(session, tenant, project_id), body.current_criteria)


@router.post("/projects/{project_id}/criteria/reset", response_model=CriteriaResponse)
def reset_criteria(project_id: str, tenant: TenantContext = Depends(get_project_writer_context),
                   session: Session = Depends(get_session_dependency)):
    return CrustdataCriteriaService.reset(session, _criteria_row(session, tenant, project_id))


@router.delete("/projects/{project_id}/criteria/current", response_model=CriteriaResponse)
def clear_criteria(project_id: str, tenant: TenantContext = Depends(get_project_writer_context),
                   session: Session = Depends(get_session_dependency)):
    return CrustdataCriteriaService.clear(session, _criteria_row(session, tenant, project_id))


@router.post("/projects/{project_id}/criteria/regenerate", response_model=CriteriaResponse)
async def regenerate_criteria(project_id: str, tenant: TenantContext = Depends(get_project_writer_context),
                              session: Session = Depends(get_session_dependency)):
    tenant_id, enterprise_id = _scope(tenant)
    return await CrustdataCriteriaService.get_or_create(session, tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id, regenerate=True)


@router.post("/projects/{project_id}/searches", response_model=SearchResponse)
async def create_search(project_id: str, body: SearchRequest, tenant: TenantContext = Depends(get_project_writer_context),
                        session: Session = Depends(get_session_dependency)):
    tenant_id, enterprise_id = _scope(tenant)
    criteria_state = await CrustdataCriteriaService.get_or_create(
        session, tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id
    )
    row = _criteria_row(session, tenant, project_id)
    if CrustdataCriteriaService.refresh_stale(session, row, project_id):
        raise HTTPException(409, "Les critères sont obsolètes; régénérez-les depuis l'offre.")
    criteria = body.criteria or criteria_state.current_criteria
    try:
        async with CrustdataClient() as client:
            response = await CandidateSearchService.start(session, client, tenant_id=tenant_id, enterprise_id=enterprise_id,
                project_id=project_id, user_id=tenant.user_id, operation_id=body.operation_id, criteria=criteria)
        raise_for_search_response_error(response)
        return response
    except InsufficientCreditsError as exc: raise HTTPException(402, str(exc)) from exc
    except CrustdataError as exc: raise _provider_error(exc) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post("/searches/{session_id}/next", response_model=SearchResponse)
async def next_search_page(session_id: str, body: NextSearchRequest, user: UserDB = Depends(get_current_user),
                           session: Session = Depends(get_session_dependency)):
    search_session = session.get(CrustdataSearchSessionDB, session_id)
    if not search_session: raise HTTPException(404, "Session de recherche introuvable.")
    tenant = require_project_writer(search_session.project_id, user)
    tenant_id, enterprise_id = _scope(tenant)
    if (search_session.tenant_id, search_session.enterprise_id) != (tenant_id, enterprise_id):
        raise HTTPException(404, "Session de recherche introuvable.")
    try:
        async with CrustdataClient() as client:
            response = await CandidateSearchService.next_page(
                session, client, search_session=search_session, operation_id=body.operation_id,
                user_id=tenant.user_id, cursor=body.cursor,
            )
        raise_for_search_response_error(response)
        return response
    except InsufficientCreditsError as exc: raise HTTPException(402, str(exc)) from exc
    except CrustdataError as exc: raise _provider_error(exc) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/imports", response_model=ImportResponse)
async def import_profiles(project_id: str, body: ImportRequest, tenant: TenantContext = Depends(get_project_writer_context),
                          session: Session = Depends(get_session_dependency)):
    tenant_id, enterprise_id = _scope(tenant)
    try:
        async with CrustdataClient() as client:
            response = await CandidateImportService.import_results(session, client, tenant_id=tenant_id, enterprise_id=enterprise_id,
                project_id=project_id, user_id=tenant.user_id, operation_id=body.operation_id,
                session_id=body.session_id, result_ids=body.result_ids)
        raise_for_import_response_error(response)
        return response
    except InsufficientCreditsError as exc: raise HTTPException(402, str(exc)) from exc
    except CrustdataError as exc: raise _provider_error(exc) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/credits")
def get_project_credits(project_id: str, tenant: TenantContext = Depends(get_project_writer_context),
                        session: Session = Depends(get_session_dependency)):
    tenant_id, _ = _scope(tenant)
    global_wallet = CreditLedgerService._wallet(session, "platform", PLATFORM_SCOPE_ID)
    tenant_wallet = CreditLedgerService._wallet(session, "tenant", tenant_id)
    costs = {"search_cost_per_result": str(get_crustdata_search_cost_per_result()),
             "enrich_cost_per_person": str(get_crustdata_person_enrich_base_cost())}
    if not global_wallet or not tenant_wallet:
        return {"available": "0", "tenant_balance": "0", "status": "not_initialized", **costs}
    available = min(global_wallet.balance - global_wallet.reserved, tenant_wallet.balance - tenant_wallet.reserved)
    return {"available": str(available), "tenant_balance": str(tenant_wallet.balance), "status": "ready", **costs}


@router.post("/projects/{project_id}/autocomplete")
async def autocomplete(project_id: str, body: AutocompleteRequest,
                       tenant: TenantContext = Depends(get_project_writer_context)):
    _scope(tenant)
    try:
        async with CrustdataClient() as client: response = await client.autocomplete(body.field, body.query)
        return {"suggestions": normalize_autocomplete_suggestions(response.data)}
    except CrustdataError as exc: raise _provider_error(exc) from exc


@router.get("/admin/credits")
def admin_credits(user: UserDB = Depends(get_current_user), session: Session = Depends(get_session_dependency)):
    _require_platform_admin(user)
    wallets = session.exec(select(CrustdataWalletDB).order_by(CrustdataWalletDB.scope_kind, CrustdataWalletDB.scope_id)).all()
    return [{"scope_kind": row.scope_kind, "scope_id": row.scope_id, "balance": str(row.balance),
             "reserved": str(row.reserved), "updated_at": row.updated_at.isoformat(),
             "provider_last_synced_at": row.provider_last_synced_at.isoformat() if row.provider_last_synced_at else None}
            for row in wallets]


@router.post("/admin/credits/sync")
async def admin_sync_credits(user: UserDB = Depends(get_current_user), session: Session = Depends(get_session_dependency)):
    _require_platform_admin(user)
    try:
        async with CrustdataClient() as client: response = await client.get_credits()
        balance = CreditLedgerService.parse_balance(response.data)
        wallet = CreditLedgerService.sync_platform_wallet(session, balance)
        return {"balance": str(wallet.balance), "reserved": str(wallet.reserved),
                "provider_last_synced_at": wallet.provider_last_synced_at.isoformat()}
    except CrustdataError as exc: raise _provider_error(exc) from exc
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc


@router.get("/admin/operations")
def admin_operations(limit: int = Query(100, ge=1, le=500), user: UserDB = Depends(get_current_user),
                     session: Session = Depends(get_session_dependency)):
    _require_platform_admin(user)
    rows = session.exec(select(CrustdataCreditOperationDB).order_by(CrustdataCreditOperationDB.created_at.desc()).limit(limit)).all()
    return [{"operation_id": row.operation_id, "tenant_id": row.tenant_id, "user_id": row.user_id,
             "project_id": row.project_id, "operation_type": row.operation_type, "requested_count": row.requested_count,
             "returned_or_matched_count": row.returned_or_matched_count, "estimated_credits": str(row.estimated_credits),
             "reported_credits_exact": str(row.reported_credits_exact) if row.reported_credits_exact is not None else None,
             "settled_credits": str(row.settled_credits) if row.settled_credits is not None else None,
             "status": row.status, "error_code": row.error_code, "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/admin/operations/{operation_id}/reconcile")
async def admin_reconcile_operation(operation_id: str, body: CreditReconcileRequest,
                                    user: UserDB = Depends(get_current_user),
                                    session: Session = Depends(get_session_dependency)):
    _require_platform_admin(user)
    operation = session.exec(select(CrustdataCreditOperationDB).where(
        CrustdataCreditOperationDB.operation_id == operation_id
    )).first()
    if operation is None: raise HTTPException(404, "Opération introuvable.")
    if operation.status != "pending_reconciliation":
        raise HTTPException(409, "Seule une opération pending_reconciliation peut être réconciliée.")
    try:
        actual = Decimal(body.actual_credits)
        if actual < 0: raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(400, "actual_credits doit être un décimal positif.") from exc
    try:
        async with CrustdataClient() as client: provider = await client.get_credits()
        provider_balance = CreditLedgerService.parse_balance(provider.data)
        operation = CreditLedgerService.reconcile(
            session, operation, actual=actual, provider_balance=provider_balance
        )
        project = session.get(ProjectDB, operation.project_id) if operation.project_id else None
        AuditService.create_event(
            session,
            enterprise_id=(project.enterprise_id if project and project.enterprise_id else operation.tenant_id),
            action="crustdata.credit_operation_reconciled",
            resource_type="crustdata_credit_operation",
            resource_id=operation.operation_id,
            actor_user_id=user.id,
            metadata={"actual_credits": str(actual), "provider_balance": str(provider_balance)},
        )
        return {"operation_id": operation.operation_id, "status": operation.status,
                "settled_credits": str(operation.settled_credits),
                "provider_balance": str(operation.provider_balance_after_or_next_sync)}
    except CrustdataError as exc: raise _provider_error(exc) from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.put("/admin/tenants/{tenant_id}/wallet")
def admin_update_tenant_wallet(tenant_id: str, body: TenantWalletUpdate, user: UserDB = Depends(get_current_user),
                               session: Session = Depends(get_session_dependency)):
    _require_platform_admin(user)
    try:
        balance = Decimal(body.balance)
        if balance < 0: raise InvalidOperation
    except (InvalidOperation, ValueError) as exc: raise HTTPException(400, "Solde décimal positif requis.") from exc
    if session.get(TenantDB, tenant_id) is None:
        raise HTTPException(404, "Tenant introuvable.")
    existing_wallet = CreditLedgerService._wallet(session, "tenant", tenant_id, lock=True)
    if existing_wallet is not None and balance < existing_wallet.reserved:
        raise HTTPException(409, "Le solde ne peut pas être inférieur aux crédits réservés.")
    wallet = CreditLedgerService.upsert_wallet(session, "tenant", tenant_id, balance)
    return {"tenant_id": tenant_id, "balance": str(wallet.balance), "reserved": str(wallet.reserved)}
