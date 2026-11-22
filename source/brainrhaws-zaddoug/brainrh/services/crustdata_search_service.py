from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from brainrh.models.crustdata import CrustdataCreditOperationDB, CrustdataSearchResultDB, CrustdataSearchSessionDB
from brainrh.schemas.crustdata import CandidateSearchCriteria, CreditsSummary, SearchProfile, SearchResponse
from brainrh.services.crustdata_client import CrustdataClient, CrustdataError
from brainrh.services.crustdata_compiler import CandidateSearchCriteriaCompiler
from brainrh.services.crustdata_credit_service import CreditLedgerService, request_fingerprint
from brainrh.services.crustdata_import_service import normalize_linkedin_url
from brainrh.settings import get_crustdata_person_enrich_base_cost, get_crustdata_search_cost_per_result


def _nested(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict): return default
        current = current.get(part)
    return default if current is None else current


def _parse_dt(value: object) -> datetime | None:
    if not value: return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError: return None


class CandidateSearchService:
    @staticmethod
    async def start(session: Session, client: CrustdataClient, *, tenant_id: str, enterprise_id: str,
                    project_id: str, user_id: str, operation_id: str,
                    criteria: CandidateSearchCriteria) -> SearchResponse:
        existing = session.exec(select(CrustdataSearchSessionDB).where(
            CrustdataSearchSessionDB.operation_id == operation_id
        )).first()
        if existing:
            if (existing.tenant_id != tenant_id or existing.enterprise_id != enterprise_id
                    or existing.project_id != project_id or existing.user_id != user_id):
                raise ValueError("operation_id déjà utilisé dans un autre contexte")
            incoming = CandidateSearchCriteriaCompiler.compile(criteria)
            if incoming != json.loads(existing.compiled_query_json):
                raise ValueError("operation_id déjà utilisé pour une requête différente")
            return await CandidateSearchService._execute(
                session, client, existing, operation_id, json.loads(existing.compiled_query_json), actor_user_id=user_id
            )
        compiled = CandidateSearchCriteriaCompiler.compile(criteria)
        search_session = CrustdataSearchSessionDB(
            tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id, user_id=user_id,
            operation_id=operation_id, compiled_query_json=json.dumps(compiled, sort_keys=True), requested_count=criteria.result_limit,
        )
        session.add(search_session)
        try:
            session.commit(); session.refresh(search_session)
        except IntegrityError:
            session.rollback()
            search_session = session.exec(select(CrustdataSearchSessionDB).where(
                CrustdataSearchSessionDB.operation_id == operation_id
            )).first()
            if search_session is None:
                raise
            if (search_session.tenant_id != tenant_id or search_session.enterprise_id != enterprise_id
                    or search_session.project_id != project_id or search_session.user_id != user_id
                    or json.loads(search_session.compiled_query_json) != compiled):
                raise ValueError("operation_id déjà utilisé dans un autre contexte")
        return await CandidateSearchService._execute(
            session, client, search_session, operation_id, compiled, actor_user_id=user_id
        )

    @staticmethod
    async def next_page(session: Session, client: CrustdataClient, *, search_session: CrustdataSearchSessionDB,
                        operation_id: str, user_id: str, cursor: str) -> SearchResponse:
        payload = json.loads(search_session.compiled_query_json)
        payload["cursor"] = cursor
        existing_operation = session.exec(select(CrustdataCreditOperationDB).where(
            CrustdataCreditOperationDB.operation_id == operation_id
        )).first()
        if existing_operation is not None:
            return await CandidateSearchService._execute(
                session, client, search_session, operation_id, payload, actor_user_id=user_id,
            )
        if not search_session.next_cursor:
            return CandidateSearchService.response_for_session(session, search_session, profiles=[])
        if cursor != search_session.next_cursor:
            raise ValueError("Curseur de pagination obsolète ou invalide")
        return await CandidateSearchService._execute(
            session, client, search_session, operation_id, payload, actor_user_id=user_id
        )

    @staticmethod
    async def _execute(session: Session, client: CrustdataClient, search_session: CrustdataSearchSessionDB,
                       operation_id: str, payload: dict[str, Any], *, actor_user_id: str) -> SearchResponse:
        limit = int(payload["limit"])
        fingerprint = request_fingerprint({"operation_type": "search", "session_id": search_session.id, "payload": payload})
        existing_operation = CreditLedgerService._operation(session, operation_id)
        if existing_operation is None:
            # Preflight gratuit: ne jamais créer de réservation si la capacité
            # fournisseur est indisponible. reserve re-check ensuite la course.
            await client.ensure_endpoint_enabled("/person/search")
        reservation = CreditLedgerService.reserve(
            session, operation_id=operation_id, tenant_id=search_session.tenant_id, user_id=actor_user_id,
            project_id=search_session.project_id, operation_type="search", requested_count=limit,
            estimated=Decimal(limit) * get_crustdata_search_cost_per_result(), fingerprint=fingerprint,
        )
        operation = reservation.operation
        if not reservation.acquired:
            if operation.response_json:
                return SearchResponse.model_validate_json(operation.response_json)
            code = operation.error_code or "OPERATION_IN_PROGRESS"
            return CandidateSearchService.response_for_session(
                session, search_session, profiles=[], operation=operation, error_code=code
            )
        try:
            provider = await client.search(payload)
        except CrustdataError as exc:
            if exc.credits_used is not None:
                terminal = CreditLedgerService.settle(
                    session, operation, reported=exc.credits_used, returned_count=0, error_code=exc.code
                )
            elif exc.code in {"PROVIDER_TIMEOUT", "PROVIDER_TEMPORARY_FAILURE"}:
                terminal = CreditLedgerService.settle(session, operation, reported=None, returned_count=0, error_code=exc.code)
            else:
                terminal = CreditLedgerService.release(session, operation, exc.code)
            response = CandidateSearchService.response_for_session(
                session, search_session, profiles=[], operation=terminal, error_code=exc.code
            )
            CreditLedgerService.store_response(session, terminal, response)
            return response
        try:
            data = provider.data if isinstance(provider.data, dict) else {}
            raw_profiles = data.get("profiles") or data.get("data") or []
            page_rows = CandidateSearchService._persist_profiles(session, search_session, raw_profiles)
            search_session.next_cursor = data.get("next_cursor")
            search_session.total_count = data.get("total_count")
            search_session.returned_count += len(page_rows)
            session.add(search_session); session.commit(); session.refresh(search_session)
            settled = CreditLedgerService.settle(session, operation, reported=provider.credits_used, returned_count=len(page_rows))
            response = CandidateSearchService.response_for_session(session, search_session, profiles=page_rows, operation=settled)
        except Exception:
            session.rollback()
            operation = session.exec(select(CrustdataCreditOperationDB).where(
                CrustdataCreditOperationDB.operation_id == operation_id
            )).one()
            settled = CreditLedgerService.settle(
                session, operation, reported=provider.credits_used, returned_count=0,
                error_code="LOCAL_PROCESSING_ERROR",
            )
            response = CandidateSearchService.response_for_session(
                session, search_session, profiles=[], operation=settled, error_code="LOCAL_PROCESSING_ERROR"
            )
        CreditLedgerService.store_response(session, settled, response)
        return response

    @staticmethod
    def _persist_profiles(session: Session, search_session: CrustdataSearchSessionDB,
                          raw_profiles: list[dict[str, Any]]) -> list[CrustdataSearchResultDB]:
        rows: list[CrustdataSearchResultDB] = []
        for raw in raw_profiles:
            person_id = str(raw.get("crustdata_person_id") or raw.get("person_id") or "").strip()
            if not person_id: continue
            existing = session.exec(select(CrustdataSearchResultDB).where(
                CrustdataSearchResultDB.search_session_id == search_session.id,
                CrustdataSearchResultDB.provider_person_id == person_id,
            )).first()
            if existing: rows.append(existing); continue
            profile_url = _nested(raw, "social_handles.professional_network_identifier.profile_url") or raw.get("profile_url")
            row = CrustdataSearchResultDB(
                search_session_id=search_session.id, tenant_id=search_session.tenant_id,
                enterprise_id=search_session.enterprise_id, project_id=search_session.project_id,
                provider_person_id=person_id,
                normalized_profile_url=normalize_linkedin_url(profile_url) if profile_url else None,
                lightweight_json=json.dumps(raw, ensure_ascii=False),
                provider_updated_at=_parse_dt(_nested(raw, "metadata.updated_at") or raw.get("updated_at")),
            )
            session.add(row); session.flush(); rows.append(row)
        session.commit()
        for row in rows: session.refresh(row)
        return rows

    @staticmethod
    def response_for_session(session: Session, row: CrustdataSearchSessionDB, *,
                             profiles: list[CrustdataSearchResultDB] | None = None, operation: Any = None,
                             error_code: str | None = None) -> SearchResponse:
        if profiles is None:
            profiles = list(session.exec(select(CrustdataSearchResultDB).where(
                CrustdataSearchResultDB.search_session_id == row.id
            )).all())
        cards = [CandidateSearchService._card(result) for result in profiles]
        consumed = str(operation.settled_credits) if operation and operation.settled_credits is not None else None
        status = operation.status if operation else "completed"
        available = CreditLedgerService.available(session, row.tenant_id)
        return SearchResponse(
            session_id=row.id, profiles=cards, next_cursor=row.next_cursor, total_count=row.total_count,
            requested_count=row.requested_count, returned_count=len(cards),
            credits=CreditsSummary(estimated=str(Decimal(row.requested_count) * get_crustdata_search_cost_per_result()),
                consumed=consumed, available=str(available) if available is not None else None,
                search_cost_per_result=str(get_crustdata_search_cost_per_result()),
                enrich_cost_per_person=str(get_crustdata_person_enrich_base_cost()),
                status=status, error_code=error_code or (operation.error_code if operation else None)),
        )

    @staticmethod
    def _card(row: CrustdataSearchResultDB) -> SearchProfile:
        raw = json.loads(row.lightweight_json)
        current = _nested(raw, "experience.employment_details.current", {})
        if isinstance(current, list): current = current[0] if current else {}
        location = _nested(raw, "basic_profile.location", "")
        if isinstance(location, dict): location = location.get("raw") or location.get("name") or location.get("city") or ""
        url = row.normalized_profile_url
        return SearchProfile(
            result_id=row.id, name=str(_nested(raw, "basic_profile.name", raw.get("name", ""))),
            headline=str(_nested(raw, "basic_profile.headline", raw.get("headline", ""))),
            current_title=str(_nested(raw, "basic_profile.current_title", current.get("title", "") if isinstance(current, dict) else "")),
            current_company=str((current.get("company_name") or current.get("name") or "") if isinstance(current, dict) else ""),
            location=str(location), updated_at=row.provider_updated_at.isoformat() if row.provider_updated_at else None,
            profile_url=url, selectable=bool(url),
        )
