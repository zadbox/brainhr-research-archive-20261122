from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import or_
from sqlmodel import Session, select

from brainrh.models.application import ApplicationDB
from brainrh.models.crustdata import (
    CrustdataCriteriaDB, CrustdataIdentityDB, CrustdataIdentityEnterpriseDB, CrustdataSearchResultDB,
    CrustdataSearchSessionDB,
)
from brainrh.models.cv import CVMetaDB
from brainrh.models.resume_version import ResumeVersionDB
from brainrh.models.talent_profile import TalentProfileDB
from brainrh.models.project import ProjectDB
from brainrh.schemas.crustdata import CreditsSummary, ImportResponse
from brainrh.services.crustdata_client import CrustdataClient, CrustdataError
from brainrh.services.crustdata_credit_service import CreditLedgerService, request_fingerprint
from brainrh.services.crustdata_criteria_service import CrustdataCriteriaService
from brainrh.services.file_storage import FileStorage
from brainrh.settings import (
    get_crustdata_max_profile_age_days,
    get_crustdata_person_enrich_base_cost,
    get_crustdata_search_cost_per_result,
)
from lib.models import CV


def normalize_linkedin_url(value: str | None) -> str:
    if not value or not str(value).strip():
        raise ValueError("URL LinkedIn absente")
    raw = str(value).strip()
    if "://" not in raw: raw = "https://" + raw
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."): host = host[4:]
    if host not in {"linkedin.com", "linkedin.cn"}:
        raise ValueError("URL LinkedIn invalide")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    if not path.startswith("/in/"):
        raise ValueError("URL de profil LinkedIn invalide")
    return urlunsplit(("https", host, path, "", ""))


def _nested(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict): return default
        current = current.get(part)
    return default if current is None else current


def _timestamp(value: object) -> datetime | None:
    if not value: return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError: return None


def _name_parts(basic: dict[str, Any]) -> tuple[str, str]:
    first, last = str(basic.get("first_name") or "").strip(), str(basic.get("last_name") or "").strip()
    if not first and not last:
        chunks = str(basic.get("name") or "").strip().split(maxsplit=1)
        first = chunks[0] if chunks else ""; last = chunks[1] if len(chunks) > 1 else ""
    return first, last


def candidate_storage_paths(*, tenant_id: str, enterprise_id: str, project_id: str,
                            person_id: str, storage_version: str) -> tuple[str, str]:
    return (
        f"crustdata/{tenant_id}/identities/{person_id}/snapshots/{storage_version}.json",
        f"enterprises/{enterprise_id}/projects/{project_id}/cvs_parsed/crustdata_{person_id}/{storage_version}.json",
    )


def _credits(*, estimated: object, consumed: object = None, available: object = None,
             status: str, error_code: str | None = None) -> CreditsSummary:
    return CreditsSummary(
        estimated=str(estimated), consumed=str(consumed) if consumed is not None else None,
        available=str(available) if available is not None else None,
        search_cost_per_result=str(get_crustdata_search_cost_per_result()),
        enrich_cost_per_person=str(get_crustdata_person_enrich_base_cost()),
        status=status, error_code=error_code,
    )


def import_context_is_stale(session: Session, *, criteria_row: CrustdataCriteriaDB | None,
                            search_session: CrustdataSearchSessionDB, project_id: str) -> bool:
    criteria_stale = bool(criteria_row and CrustdataCriteriaService.refresh_stale(session, criteria_row, project_id))
    project = session.get(ProjectDB, project_id)
    project_updated = project.last_modified if project else None
    session_created = search_session.created_at
    if project_updated and project_updated.tzinfo is None: project_updated = project_updated.replace(tzinfo=timezone.utc)
    if session_created.tzinfo is None: session_created = session_created.replace(tzinfo=timezone.utc)
    return criteria_stale or bool(project_updated and project_updated > session_created)


def map_crustdata_to_cv(person: dict[str, Any], *, filename: str, profile_url: str,
                        source_person_id: str, imported_by_user_id: str, tenant_id: str,
                        project_id: str, confidence_score: object, retrieved_at: datetime) -> dict[str, Any]:
    basic = person.get("basic_profile") if isinstance(person.get("basic_profile"), dict) else {}
    first, last = _name_parts(basic)
    employment = _nested(person, "experience.employment_details", {})
    current = employment.get("current", []) if isinstance(employment, dict) else []
    past = employment.get("past", []) if isinstance(employment, dict) else []
    if isinstance(current, dict): current = [current]
    if isinstance(past, dict): past = [past]
    experiences = []
    for item in [*current, *past]:
        if not isinstance(item, dict): continue
        experiences.append({
            "poste": str(item.get("title") or ""), "entreprise": str(item.get("company_name") or item.get("name") or ""),
            "lieu": str(item.get("location") or ""), "date_debut": str(item.get("start_date") or ""),
            "date_fin": str(item.get("end_date") or ""), "missions": item.get("description") if isinstance(item.get("description"), list) else ([str(item["description"])] if item.get("description") else []),
        })
    education = _nested(person, "education.schools", [])
    skills = _nested(person, "skills.professional_network_skills", [])
    if not isinstance(education, list): education = []
    if not isinstance(skills, list): skills = []
    location = basic.get("location") or ""
    if isinstance(location, dict): location = location.get("raw") or location.get("name") or ""
    source_updated = basic.get("last_updated") or person.get("updated_at") or _nested(person, "metadata.updated_at")
    payload = {
        "cv": filename,
        "identite": {"nom": last, "prenom": first, "adresse": str(location), "linkedin": profile_url},
        "titre": str(basic.get("current_title") or basic.get("headline") or ""),
        "resume_professionnel": str(basic.get("summary") or ""),
        "competences_techniques": [str(item.get("name") if isinstance(item, dict) else item) for item in skills],
        "langues": [str(item.get("name") if isinstance(item, dict) else item) for item in (basic.get("languages") or [])],
        "experiences_professionnelles": experiences,
        "formations": education,
        "source": "crustdata", "source_profile_url": profile_url, "source_person_id": source_person_id,
        "crustdata_person_id": source_person_id, "source_last_updated_at": source_updated,
        "source_confidence_score": confidence_score, "retrieved_at": retrieved_at.isoformat(),
        "imported_at": retrieved_at.isoformat(), "imported_by_user_id": imported_by_user_id,
        "tenant_id": tenant_id, "job_offer_id": project_id,
    }
    return CV.model_validate(payload).model_dump()


class CandidateImportService:
    @staticmethod
    def _already_imported(
        session: Session,
        *,
        row: CrustdataSearchResultDB,
        tenant_id: str,
        enterprise_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        identity = session.exec(select(CrustdataIdentityDB).where(
            CrustdataIdentityDB.tenant_id == tenant_id,
            or_(
                CrustdataIdentityDB.provider_person_id == row.provider_person_id,
                CrustdataIdentityDB.normalized_profile_url == row.normalized_profile_url,
            ),
        )).first()
        if identity is None:
            return None
        link = session.exec(select(CrustdataIdentityEnterpriseDB).where(
            CrustdataIdentityEnterpriseDB.identity_id == identity.id,
            CrustdataIdentityEnterpriseDB.enterprise_id == enterprise_id,
        )).first()
        if link is None:
            return None
        application = session.exec(select(ApplicationDB).where(
            ApplicationDB.enterprise_id == enterprise_id,
            ApplicationDB.project_id == project_id,
            ApplicationDB.talent_profile_id == link.talent_profile_id,
        )).first()
        if application is None:
            return None
        return {
            "result_id": row.id,
            "talent_profile_id": link.talent_profile_id,
            "application_id": application.id,
            "status": "already_imported",
        }

    @staticmethod
    async def import_results(session: Session, client: CrustdataClient, *, tenant_id: str, enterprise_id: str,
                             project_id: str, user_id: str, operation_id: str, session_id: str,
                             result_ids: list[str]) -> ImportResponse:
        search_session = session.exec(select(CrustdataSearchSessionDB).where(
            CrustdataSearchSessionDB.id == session_id, CrustdataSearchSessionDB.tenant_id == tenant_id,
            CrustdataSearchSessionDB.enterprise_id == enterprise_id, CrustdataSearchSessionDB.project_id == project_id,
        )).first()
        if not search_session: raise ValueError("Session de recherche introuvable")
        rows = list(session.exec(select(CrustdataSearchResultDB).where(
            CrustdataSearchResultDB.id.in_(result_ids), CrustdataSearchResultDB.search_session_id == session_id,
            CrustdataSearchResultDB.tenant_id == tenant_id, CrustdataSearchResultDB.enterprise_id == enterprise_id,
            CrustdataSearchResultDB.project_id == project_id,
        )).all())
        if len({row.id for row in rows}) != len(set(result_ids)):
            raise ValueError("Un ou plusieurs résultats sont hors du périmètre autorisé")
        selectable = [row for row in rows if row.normalized_profile_url]
        if len(selectable) != len(rows): raise ValueError("Un profil sans URL LinkedIn ne peut pas être importé")
        fingerprint = request_fingerprint({
            "operation_type": "enrich", "session_id": session_id, "result_ids": sorted(result_ids),
        })
        existing_operation = CreditLedgerService._operation(session, operation_id)
        already_imported = [
            existing
            for row in rows
            if (existing := CandidateImportService._already_imported(
                session,
                row=row,
                tenant_id=tenant_id,
                enterprise_id=enterprise_id,
                project_id=project_id,
            )) is not None
        ]
        already_imported_ids = {item["result_id"] for item in already_imported}
        rows_to_enrich = [row for row in rows if row.id not in already_imported_ids]
        if existing_operation is None and not rows_to_enrich:
            available = CreditLedgerService.available(session, tenant_id)
            return ImportResponse(
                imported_count=0,
                already_imported_count=len(already_imported),
                failed_count=0,
                imported=[],
                already_imported=already_imported,
                failed=[],
                credits=_credits(
                    estimated=Decimal("0"), consumed=Decimal("0"), available=available, status="settled"
                ),
                warnings=[],
            )
        if existing_operation is None:
            # /account/endpoints est gratuit: un échec preflight ne doit laisser
            # ni opération de crédit ni réservation.
            await client.ensure_endpoint_enabled("/person/enrich")
        reservation = CreditLedgerService.reserve(
            session, operation_id=operation_id, tenant_id=tenant_id, user_id=user_id, project_id=project_id,
            operation_type="enrich", requested_count=len(rows_to_enrich),
            estimated=Decimal(len(rows_to_enrich)) * get_crustdata_person_enrich_base_cost(), fingerprint=fingerprint,
        )
        operation = reservation.operation
        if not reservation.acquired:
            available = CreditLedgerService.available(session, tenant_id)
            if operation.response_json:
                return ImportResponse.model_validate_json(operation.response_json)
            code = operation.error_code or "OPERATION_IN_PROGRESS"
            return ImportResponse(imported_count=0, already_imported_count=0, failed_count=0,
                imported=[], already_imported=[], failed=[],
                credits=_credits(estimated=operation.estimated_credits,
                    consumed=operation.settled_credits, available=available,
                    status=operation.status, error_code=code),
                warnings=["Une opération identique est déjà en cours."])
        by_url = {row.normalized_profile_url: row for row in rows_to_enrich}
        imported: list[dict[str, Any]] = []; failed: list[dict[str, Any]] = []; warnings: list[str] = []
        reported_total = Decimal("0"); missing_header = False; provider_called = False; ambiguous_timeout = False
        last_error_code: str | None = None
        urls = list(by_url)
        for start in range(0, len(urls), 25):
            chunk = urls[start:start + 25]
            try:
                response = await client.enrich(chunk); provider_called = True
            except CrustdataError as exc:
                last_error_code = exc.code
                if exc.credits_used is not None:
                    provider_called = True
                    reported_total += exc.credits_used
                ambiguous_provider_result = (
                    exc.credits_used is None
                    and exc.code in {"PROVIDER_TIMEOUT", "PROVIDER_TEMPORARY_FAILURE"}
                )
                ambiguous_timeout = ambiguous_timeout or ambiguous_provider_result
                failed.extend({"result_id": by_url[url].id, "code": exc.code} for url in chunk)
                failed.extend(
                    {"result_id": by_url[url].id, "code": exc.code}
                    for url in urls[start + len(chunk):]
                )
                break
            if response.credits_used is None: missing_header = True
            else: reported_total += response.credits_used
            returned_urls: set[str] = set()
            for entry in response.data if isinstance(response.data, list) else []:
                try: matched_url = normalize_linkedin_url(entry.get("matched_on"))
                except (ValueError, AttributeError): continue
                row = by_url.get(matched_url)
                if not row: continue
                returned_urls.add(matched_url)
                matches = entry.get("matches") if isinstance(entry, dict) else []
                if not matches:
                    failed.append({"result_id": row.id, "code": "NO_MATCH"}); continue
                match = max(matches, key=lambda item: float(item.get("confidence_score") or 0))
                try:
                    raw_person = match.get("person_data") or {}
                    storage_person_id = str(raw_person.get("crustdata_person_id") or row.provider_person_id)
                    storage_version = str(uuid4())
                    storage_paths = candidate_storage_paths(
                        tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id,
                        person_id=storage_person_id, storage_version=storage_version,
                    )
                    result, freshness_warning = CandidateImportService._persist_candidate(
                        session, row=row, person=raw_person, confidence=match.get("confidence_score"),
                        tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id, user_id=user_id,
                        storage_version=storage_version,
                    )
                    imported.append(result)
                    if freshness_warning: warnings.append(freshness_warning)
                except Exception:
                    session.rollback()
                    for path in storage_paths:
                        try: FileStorage.delete_file(path)
                        except Exception: pass
                    failed.append({"result_id": row.id, "code": "IMPORT_FAILED"})
            failed.extend({"result_id": by_url[url].id, "code": "NO_MATCH"} for url in chunk if url not in returned_urls)
        if not provider_called and ambiguous_timeout:
            terminal_operation = CreditLedgerService.settle(
                session, operation, reported=None, returned_count=0,
                error_code=last_error_code or "PROVIDER_TIMEOUT",
            )
            status, consumed = terminal_operation.status, None
        elif not provider_called:
            terminal_operation = CreditLedgerService.release(
                session, operation, last_error_code or "PROVIDER_ERROR"
            )
            status, consumed = terminal_operation.status, None
        else:
            terminal_operation = CreditLedgerService.settle(
                session,
                operation,
                reported=None if missing_header or ambiguous_timeout else reported_total,
                returned_count=len(imported),
                error_code=last_error_code,
            )
            status = terminal_operation.status
            consumed = str(terminal_operation.settled_credits) if terminal_operation.settled_credits is not None else None
        available = CreditLedgerService.available(session, tenant_id)
        if status == "pending_reconciliation":
            warnings.append("Crédits Crustdata en attente de rapprochement.")
        response = ImportResponse(
            imported_count=len(imported), already_imported_count=len(already_imported),
            failed_count=len(failed), imported=imported, already_imported=already_imported, failed=failed,
            credits=_credits(estimated=operation.estimated_credits, consumed=consumed,
                available=available, status=status, error_code=terminal_operation.error_code),
            warnings=list(dict.fromkeys(warnings)),
        )
        CreditLedgerService.store_response(session, terminal_operation, response)
        return response

    @staticmethod
    def _persist_candidate(session: Session, *, row: CrustdataSearchResultDB, person: dict[str, Any], confidence: object,
                           tenant_id: str, enterprise_id: str, project_id: str, user_id: str,
                           storage_version: str) -> tuple[dict[str, Any], str | None]:
        url = normalize_linkedin_url(row.normalized_profile_url)
        person_id = str(person.get("crustdata_person_id") or row.provider_person_id)
        identity = session.exec(select(CrustdataIdentityDB).where(
            CrustdataIdentityDB.tenant_id == tenant_id,
            or_(CrustdataIdentityDB.provider_person_id == person_id, CrustdataIdentityDB.normalized_profile_url == url),
        )).first()
        now = datetime.now(timezone.utc)
        source_updated = _timestamp(
            _nested(person, "basic_profile.last_updated") or person.get("updated_at") or _nested(person, "metadata.updated_at")
        ) or row.provider_updated_at
        freshness = "unknown" if source_updated is None else ("fresh" if source_updated >= now - timedelta(days=get_crustdata_max_profile_age_days()) else "stale")
        filename = f"crustdata_{person_id}.json"
        raw_path, normalized_path = candidate_storage_paths(
            tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id,
            person_id=person_id, storage_version=storage_version,
        )
        cv = map_crustdata_to_cv(person, filename=filename, profile_url=url, source_person_id=person_id,
            imported_by_user_id=user_id, tenant_id=tenant_id, project_id=project_id,
            confidence_score=confidence, retrieved_at=now)
        FileStorage.save_json_atomic(raw_path, person); FileStorage.save_json_atomic(normalized_path, cv)
        if identity is None:
            identity = CrustdataIdentityDB(tenant_id=tenant_id, provider_person_id=person_id, normalized_profile_url=url)
        identity.raw_snapshot_path = raw_path; identity.source_last_updated_at = source_updated; identity.updated_at = now
        session.add(identity); session.flush()
        link = session.exec(select(CrustdataIdentityEnterpriseDB).where(
            CrustdataIdentityEnterpriseDB.identity_id == identity.id,
            CrustdataIdentityEnterpriseDB.enterprise_id == enterprise_id,
        )).first()
        basic = person.get("basic_profile") if isinstance(person.get("basic_profile"), dict) else {}
        first, last = _name_parts(basic)
        if link:
            profile = session.get(TalentProfileDB, link.talent_profile_id)
        else:
            profile = TalentProfileDB(enterprise_id=enterprise_id, first_name=first or None, last_name=last or None)
            session.add(profile); session.flush()
            link = CrustdataIdentityEnterpriseDB(identity_id=identity.id, enterprise_id=enterprise_id, talent_profile_id=profile.id)
            session.add(link)
        if profile:
            profile.first_name = first or profile.first_name; profile.last_name = last or profile.last_name; session.add(profile)
        last_version = session.exec(select(ResumeVersionDB).where(
            ResumeVersionDB.talent_profile_id == profile.id
        ).order_by(ResumeVersionDB.version_number.desc())).first()
        resume = ResumeVersionDB(enterprise_id=enterprise_id, talent_profile_id=profile.id,
            version_number=(last_version.version_number + 1 if last_version else 1), storage_path=normalized_path,
            parsed_json_str=json.dumps(cv, ensure_ascii=False))
        session.add(resume); session.flush()
        application = session.exec(select(ApplicationDB).where(
            ApplicationDB.enterprise_id == enterprise_id, ApplicationDB.project_id == project_id,
            ApplicationDB.talent_profile_id == profile.id,
        )).first()
        if application is None:
            application = ApplicationDB(enterprise_id=enterprise_id, project_id=project_id,
                talent_profile_id=profile.id, resume_version_id=resume.id, status="new")
        else: application.resume_version_id = resume.id
        session.add(application)
        cv_meta = session.exec(select(CVMetaDB).where(CVMetaDB.project_id == project_id, CVMetaDB.filename == filename)).first()
        if cv_meta is None:
            cv_meta = CVMetaDB(filename=filename, project_id=project_id, json_path=normalized_path, file_path=normalized_path)
        cv_meta.candidat_nom = " ".join(part for part in (first, last) if part); cv_meta.candidat_titre = cv.get("titre")
        cv_meta.json_path = normalized_path; cv_meta.file_path = normalized_path; cv_meta.last_modified = now
        session.add(cv_meta); session.commit()
        warning = None if freshness == "fresh" else f"Profil {filename}: fraîcheur {freshness}."
        return {"result_id": row.id, "talent_profile_id": profile.id, "application_id": application.id, "filename": filename, "freshness": freshness}, warning
