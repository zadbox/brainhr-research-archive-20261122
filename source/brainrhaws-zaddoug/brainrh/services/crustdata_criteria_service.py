from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from brainrh.models.crustdata import CrustdataCriteriaDB
from brainrh.models.project import ProjectDB
from brainrh.schemas.crustdata import CandidateSearchCriteria, CriteriaResponse
from brainrh.services.llm_settings_service import get_chat_client_for_process
from brainrh.services.project_file_service import ProjectFileService
from brainrh.settings import get_crustdata_default_result_limit, get_crustdata_max_profile_age_days


SYSTEM_PROMPT = """Tu extrais uniquement des critères de recherche de candidats à partir d'une offre.
Retourne un objet JSON strict avec exactement: titles, required_skills, locations, min_years_experience,
seniority_levels, max_profile_age_days, result_limit. N'invente jamais un fait absent. Aucun autre champ."""


def _dump(criteria: CandidateSearchCriteria) -> str:
    return json.dumps(criteria.model_dump(mode="json"), sort_keys=True)


def _load(raw: str) -> CandidateSearchCriteria:
    return CandidateSearchCriteria.model_validate_json(raw)


def _fallback(offer: dict[str, Any]) -> CandidateSearchCriteria:
    sections = offer.get("sections") if isinstance(offer.get("sections"), dict) else offer
    title = str(sections.get("titre") or offer.get("titre") or "").strip()
    skills: list[str] = []
    for key in ("competences_techniques", "outils", "langages"):
        value = sections.get(key, [])
        if isinstance(value, list):
            skills.extend(str(item).strip() for item in value if str(item).strip())
    return CandidateSearchCriteria(
        titles=[title] if title else [],
        required_skills=list(dict.fromkeys(skills))[:30],
        max_profile_age_days=get_crustdata_max_profile_age_days(),
        result_limit=get_crustdata_default_result_limit(),
    )


class CrustdataCriteriaService:
    @staticmethod
    async def get_or_create(session: Session, *, tenant_id: str, enterprise_id: str, project_id: str,
                            regenerate: bool = False) -> CriteriaResponse:
        row = session.exec(select(CrustdataCriteriaDB).where(
            CrustdataCriteriaDB.tenant_id == tenant_id,
            CrustdataCriteriaDB.enterprise_id == enterprise_id,
            CrustdataCriteriaDB.project_id == project_id,
        )).first()
        if row and not regenerate:
            CrustdataCriteriaService.refresh_stale(session, row, project_id)
            return CrustdataCriteriaService._response(row)
        offer = ProjectFileService.load_offer(project_id, enterprise_id) or {}
        criteria = await CrustdataCriteriaService._derive(offer)
        now = datetime.now(timezone.utc)
        if row:
            row.offer_derived_json = _dump(criteria)
            row.current_json = _dump(criteria)
            row.stale = False
            row.updated_at = now
        else:
            row = CrustdataCriteriaDB(
                tenant_id=tenant_id, enterprise_id=enterprise_id, project_id=project_id,
                offer_derived_json=_dump(criteria), current_json=_dump(criteria),
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return CrustdataCriteriaService._response(row)

    @staticmethod
    async def _derive(offer: dict[str, Any]) -> CandidateSearchCriteria:
        fallback = _fallback(offer)
        if not offer:
            return fallback
        try:
            client, selection = get_chat_client_for_process("offer_criteria", async_client=True)
            response = await client.chat.completions.create(
                model=selection.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(offer, ensure_ascii=False)}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return CandidateSearchCriteria.model_validate_json(content)
        except Exception:
            return fallback

    @staticmethod
    def update(session: Session, row: CrustdataCriteriaDB, criteria: CandidateSearchCriteria) -> CriteriaResponse:
        row.current_json = _dump(criteria)
        row.updated_at = datetime.now(timezone.utc)
        session.add(row); session.commit(); session.refresh(row)
        return CrustdataCriteriaService._response(row)

    @staticmethod
    def reset(session: Session, row: CrustdataCriteriaDB) -> CriteriaResponse:
        row.current_json = row.offer_derived_json
        row.updated_at = datetime.now(timezone.utc)
        session.add(row); session.commit(); session.refresh(row)
        return CrustdataCriteriaService._response(row)

    @staticmethod
    def clear(session: Session, row: CrustdataCriteriaDB) -> CriteriaResponse:
        existing = _load(row.current_json)
        cleared = CandidateSearchCriteria(max_profile_age_days=None, result_limit=existing.result_limit)
        return CrustdataCriteriaService.update(session, row, cleared)

    @staticmethod
    def find(session: Session, tenant_id: str, enterprise_id: str, project_id: str) -> CrustdataCriteriaDB | None:
        return session.exec(select(CrustdataCriteriaDB).where(
            CrustdataCriteriaDB.tenant_id == tenant_id,
            CrustdataCriteriaDB.enterprise_id == enterprise_id,
            CrustdataCriteriaDB.project_id == project_id,
        )).first()

    @staticmethod
    def refresh_stale(session: Session, row: CrustdataCriteriaDB, project_id: str) -> bool:
        project = session.get(ProjectDB, project_id)
        if not project or not project.last_modified:
            return row.stale
        project_updated = project.last_modified
        criteria_updated = row.updated_at
        if project_updated.tzinfo is None: project_updated = project_updated.replace(tzinfo=timezone.utc)
        if criteria_updated.tzinfo is None: criteria_updated = criteria_updated.replace(tzinfo=timezone.utc)
        stale = row.stale or project_updated > criteria_updated
        if stale != row.stale:
            row.stale = stale; session.add(row); session.commit(); session.refresh(row)
        return stale

    @staticmethod
    def _response(row: CrustdataCriteriaDB) -> CriteriaResponse:
        return CriteriaResponse(offer_derived_criteria=_load(row.offer_derived_json), current_criteria=_load(row.current_json), stale=row.stale)
