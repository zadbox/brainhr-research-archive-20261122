"""
Router Matching - Lancement et résultats de matchings
"""

import json
import asyncio
import os
import re
from typing import List, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import (
    get_current_user,
    get_matching_id_tenant_context,
    get_project_tenant_context,
    require_project_access_sse_for_request,
)
from api.request_security import validate_cookie_authenticated_mutation_origin
from brainrh.models.auth import UserDB, UserRole
from brainrh.services.auth_service import TenantContext
from brainrh.paths import PROJECT_ROOT
from brainrh.settings import is_production
from lib.models import Offre, MatchingResponse, ResultatMatching, MatchingMetadata
from brainrh.services.matching_file_service import MatchingFileService
from brainrh.services.matching_runtime import get_matching_engine

router = APIRouter()


def _normalize_cv_key(name: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def _build_cv_file_map(candidates: List[dict]) -> dict:
    cv_file_map = {}
    for cand in candidates:
        cv_data = cand.get("cv_data") or {}
        filename = cand.get("filename") or cv_data.get("cv") or cand.get("email")
        if filename:
            cv_file_map[_normalize_cv_key(filename)] = re.sub(r"\s+", " ", str(filename).strip())
    return cv_file_map


def _original_cv_url_for(project_id: str, cv_name: Optional[str], cv_file_map: dict) -> Optional[str]:
    candidate_id = cv_file_map.get(_normalize_cv_key(cv_name))
    if not candidate_id:
        return None
    safe_project_id = quote(project_id, safe="")
    safe_candidate_id = quote(candidate_id, safe="")
    return f"/api/v1/cvs/projects/{safe_project_id}/cvs/{safe_candidate_id}/download"


def _candidate_name_from_cv_content(cv_content: Optional[dict], fallback: str) -> str:
    if not isinstance(cv_content, dict):
        return fallback
    sections = cv_content.get("sections", cv_content)
    identite = sections.get("identite", {}) if isinstance(sections, dict) else {}
    first_name = (identite.get("prenom") or "").strip()
    last_name = (identite.get("nom") or "").strip()
    candidate_name = f"{first_name} {last_name}".strip()
    return candidate_name or fallback


def _normalize_offer_criteria(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    normalized: List[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _detect_flags_from_cv_content(cv_content: Optional[dict]) -> dict:
    if not isinstance(cv_content, dict):
        return {}

    sections = cv_content.get("sections", cv_content)
    all_experiences = sections.get("experiences_professionnelles", []) if isinstance(sections.get("experiences_professionnelles"), list) else []
    if not all_experiences:
        return {}

    from lib.experience_analyzer import detect_gaps_and_overlaps as detect_gaps

    flags = detect_gaps(all_experiences)
    return {
        "gappes": [{"period": g.period, "duration_months": g.duration_months, "between": g.between} for g in flags.gappes],
        "overlaps": [{"overlap_period": o.overlap_period, "overlap_days": o.overlap_days, "experiences": o.experiences, "same_company": o.same_company} for o in flags.overlaps],
    }


def _serialize_matching_result(
    payload: dict,
    project_id: str,
    cv_file_map: dict,
    *,
    algorithmic_rank: Optional[int] = None,
    reranked: Optional[bool] = None,
) -> dict:
    cv_name = payload.get("cv", "inconnu")
    cv_content = payload.get("content", {})
    evidence_map_raw = payload.get("evidence_map") or {}
    flags_raw = payload.get("flags_raw") or payload.get("flags") or _detect_flags_from_cv_content(cv_content)
    original_cv_url = _original_cv_url_for(project_id, cv_name, cv_file_map)

    result = {
        "cv": cv_name,
        "candidate_name": payload.get("candidate_name") or _candidate_name_from_cv_content(cv_content, cv_name),
        "score_final": payload.get("score_final", 0.0),
        "score_base": payload.get("score_base", 0.0),
        "bonus_nice_have_multiplicateur": payload.get("bonus_nice_have_multiplicateur", 1.0),
        "coefficient_qualite_experience": payload.get("coefficient_qualite_experience", 1.0),
        "nice_have_manquants": payload.get("nice_have_manquants", []),
        "commentaire_scoring": payload.get("commentaire_scoring", ""),
        "appreciation_globale": payload.get("appreciation_globale", ""),
        "evidences": payload.get("evidences") or [],
        "evidence_map": evidence_map_raw if evidence_map_raw else None,
        "flags": flags_raw if flags_raw else None,
        "original_cv_url": original_cv_url,
        "matrix_summary": payload.get("matrix_summary", ""),
        "recommendation_level": payload.get("recommendation_level", ""),
        "relevant_experience_years": payload.get("relevant_experience_years"),
        "top_strengths": payload.get("top_strengths") or [],
        "watchouts": payload.get("watchouts") or [],
        "interview_focus": payload.get("interview_focus") or [],
        "must_have_assessment": payload.get("must_have_assessment") or [],
        "nice_have_assessment": payload.get("nice_have_assessment") or [],
        "algorithmic_breakdown": payload.get("algorithmic_breakdown"),
    }
    if algorithmic_rank is not None:
        result["algorithmic_rank"] = algorithmic_rank
    if reranked is not None:
        result["reranked"] = reranked
    return result


def _to_result_model(cv_result: dict) -> ResultatMatching:
    return ResultatMatching(
        cv=cv_result.get("cv", "inconnu"),
        candidate_name=cv_result.get("candidate_name"),
        score_final=cv_result.get("score_final", 0.0),
        score_base=cv_result.get("score_base", 0.0),
        bonus_nice_have_multiplicateur=cv_result.get("bonus_nice_have_multiplicateur", 1.0),
        coefficient_qualite_experience=cv_result.get("coefficient_qualite_experience", 1.0),
        nice_have_manquants=cv_result.get("nice_have_manquants", []),
        commentaire_scoring=cv_result.get("commentaire_scoring", ""),
        appreciation_globale=cv_result.get("appreciation_globale", ""),
        evidences=cv_result.get("evidences"),
        evidence_map=cv_result.get("evidence_map"),
        flags=cv_result.get("flags"),
        original_cv_url=cv_result.get("original_cv_url"),
        matrix_summary=cv_result.get("matrix_summary"),
        recommendation_level=cv_result.get("recommendation_level"),
        relevant_experience_years=cv_result.get("relevant_experience_years"),
        top_strengths=cv_result.get("top_strengths") or [],
        watchouts=cv_result.get("watchouts") or [],
        interview_focus=cv_result.get("interview_focus") or [],
        must_have_assessment=cv_result.get("must_have_assessment") or [],
        nice_have_assessment=cv_result.get("nice_have_assessment") or [],
        algorithmic_rank=cv_result.get("algorithmic_rank"),
        reranked=cv_result.get("reranked"),
        algorithmic_breakdown=cv_result.get("algorithmic_breakdown"),
    )


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _validate_matching_stream_request_origin(request: Request) -> None:
    validate_cookie_authenticated_mutation_origin(request, action_label="lancer un matching", force=True)


class MatchingRequest(BaseModel):
    """Requête pour lancer un matching"""
    offre: Offre
    cvs: List[str]  # Liste d'IDs de CVs (noms de fichiers)
    top_n_rerank: int = 10
    model: Optional[str] = None
    concurrency: int = 500
    qps: float = 10.0



@router.post("/run", response_model=MatchingResponse)
async def run_matching(
    request: MatchingRequest,
    _current_user: UserDB = Depends(get_current_user),
):
    """
    Lance un matching complet en mode batch

    **Pipeline:**
    1. Filtrage must-have (éliminatoire)
    2. Calcul similarité (embeddings)
    3. Détection nice-have manquants
    4. Re-ranking LLM du top N

    **Body:**
    - `offre`: Offre avec must-have/nice-have
    - `cvs`: Liste d'IDs de CVs (noms de fichiers parsés)
    - `top_n_rerank`: Nombre de CVs à re-ranker avec LLM (default: 10)
    - `model`: Modèle LLM (default: gpt-5-mini)
    - `concurrency`: Concurrence max (default: 500)
    - `qps`: QPS max (default: 10.0)

    **Retourne:** Résultats complets une fois terminé

    **Note:** Pour feedback temps-réel, utiliser `/matching/run/stream`
    """
    raise HTTPException(
        status_code=501,
        detail="Matching batch nécessite système de stockage persistant (CVs parsés). Utiliser /matching/run/stream avec données complètes.",
    )


@router.get("/run/stream")
async def run_matching_stream(
    request: Request,
    project_id: str = Query(..., description="ID du projet"),
    top_n_rerank: int = Query(default=10, ge=1, le=50, description="Nombre de CVs à re-ranker (max 50)"),
    model: Optional[str] = Query(default=None, description="Modèle LLM legacy")
):
    """
    Lance un matching avec streaming SSE depuis un project_id

    **Query params:**
    - `project_id`: ID du projet (obligatoire)
    - `top_n_rerank`: Nombre de CVs à re-ranker (default: 10)
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Événements:**
    - `progress`: Progression par étape (must_have_filtering, embedding, reranking)
    - `done`: Résultats finaux + métadonnées
    - `error`: Erreur

    **Pipeline complet:**
    1. Chargement de l'offre et des CVs depuis le projet
    2. Filtrage must-have (éliminatoire)
    3. Calcul similarité embeddings + nice-have
    4. Re-ranking LLM du top N
    5. Sauvegarde des résultats dans projects/{project_id}/matchings/{timestamp}/

    **Consommation côté client:**
    ```javascript
    const eventSource = new EventSource('/api/v1/matching/run/stream?project_id=X&top_n_rerank=10&model=gpt-5-mini');

    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      console.log(`Étape: ${data.step}, ${data.current}/${data.total}`);
    });

    eventSource.addEventListener('done', (e) => {
      const data = JSON.parse(e.data);
      console.log('Matching terminé:', data.summary);
      eventSource.close();
    });
    ```
    """
    _validate_matching_stream_request_origin(request)

    async def event_generator():
        import time
        import asyncio

        start_time = time.time()

        try:
            tenant_context, access_error = require_project_access_sse_for_request(
                request,
                project_id,
                {UserRole.enterprise_admin, UserRole.recruiter},
            )
            if access_error:
                yield "event: error\n"
                yield f"data: {json.dumps(access_error)}\n\n"
                return

            # === Charger le projet, l'offre et les CVs ===
            from unified_project_manager import UnifiedProjectManager

            pm = UnifiedProjectManager(enterprises_folder="enterprises")

            # Charger le projet
            project = pm.get_project(project_id, tenant_context.enterprise_id)
            if not project:
                yield "event: error\n"
                error_data = {'code': 'PROJECT_NOT_FOUND', 'message': f'Projet {project_id} introuvable'}
                yield f"data: {json.dumps(error_data)}\n\n"
                return

            # Charger l'offre
            from brainrh.services.project_file_service import ProjectFileService

            offre_data = ProjectFileService.load_offer(project_id, tenant_context.enterprise_id)
            if not offre_data or not offre_data.get("sections"):
                yield "event: error\n"
                error_data = {'code': 'NO_OFFRE', 'message': "Aucune offre définie pour ce projet. Créez d'abord une offre."}
                yield f"data: {json.dumps(error_data)}\n\n"
                return

            # Charger les CVs parsés depuis ApplicationService/legacy fallback
            from brainrh.services.application_service import ApplicationService
            from sqlmodel import Session
            from brainrh.database import engine

            with Session(engine) as session:
                candidates = ApplicationService.get_project_candidates(session, project_id)

            if not candidates:
                yield "event: error\n"
                error_data = {'code': 'NO_CVS', 'message': "Aucun CV rattaché à ce projet (via base ou legacy)."}
                yield f"data: {json.dumps(error_data)}\n\n"
                return

            # Construire le mapping CV -> fichier source original et extraire 'cv_data'
            cv_file_map = _build_cv_file_map(candidates)
            cvs_data = []

            for cand in candidates:
                cv_d = cand.get("cv_data")
                if cv_d:
                    # Garantir que la clé 'cv' (le filename originel) est dispo dans le payload
                    filename = cand.get("filename") or cand.get("cv_data", {}).get("cv") or cand.get("email")
                    cv_d["cv"] = filename
                    cvs_data.append(cv_d)

            print(f"📇 {len(cv_file_map)} liens CV source mappés via les candidatures")
            print(f"📂 Fichiers CV chargés en mémoire: {len(cvs_data)}")

            total_cvs_initial = len(cvs_data)
            print(f"📊 Total CVs chargés en mémoire: {total_cvs_initial}")

            # Extraire must-have et nice-have de l'offre
            must_have = _normalize_offer_criteria(offre_data.get("must_have", []))
            nice_have = _normalize_offer_criteria(offre_data.get("nice_have", []))

            # Générer job_text pour embeddings (TOUTES les sections)
            sections = offre_data.get("sections", {})
            job_text = " ".join([
                str(v) for v in sections.values() if v
            ])

            # job_description = MÊME contenu que job_text pour alignement Streamlit
            job_description = job_text

            # Get event loop
            loop = asyncio.get_event_loop()

            if not must_have:
                filtered_cvs = list(cvs_data)
                must_have_runtime_meta = {
                    "provider_used": None,
                    "model_used": None,
                    "duration_s": None,
                    "fallback_used": None,
                }
                yield _sse_event("progress", {
                    "step": "must_have_filtering",
                    "current": total_cvs_initial,
                    "total": total_cvs_initial,
                    "progress": 1.0,
                    "message": "Skipped: 0 must-have criteria",
                    "skipped": True,
                    "criteria_count": 0,
                })
            else:
                # === ÉTAPE 1: Filtrage must-have ===
                message = f'Filtrage must-have ({len(must_have)} critères)'
                yield _sse_event("progress", {
                    'step': 'must_have_filtering',
                    'current': 0,
                    'total': total_cvs_initial,
                    'progress': 0.0,
                    'message': message,
                    'skipped': False,
                    'criteria_count': len(must_have),
                })

                # Callback pour progression
                def progress_callback_must_have(current, total):
                    pass  # SSE progression déjà envoyée

                # Exécuter filtrage must-have en thread pool (fonction sync)
                filter_task = loop.run_in_executor(
                    None,
                    lambda: get_matching_engine().filter_cvs_by_must_have(
                        cvs=cvs_data,
                        indispensables=must_have,
                        job_description=job_description,
                        use_parallel=True,
                        progress_callback=progress_callback_must_have
                    )
                )
                while not filter_task.done():
                    await asyncio.sleep(10)
                    if not filter_task.done():
                        yield _sse_event("progress", {
                            "step": "must_have_filtering",
                            "current": 0,
                            "total": total_cvs_initial,
                            "progress": 0.0,
                            "message": message,
                            "skipped": False,
                            "criteria_count": len(must_have),
                        })
                filtered_cvs, must_have_runtime_meta = await filter_task

                total_cvs_filtered = len(filtered_cvs)

                progress_msg = f'Filtrage terminé: {total_cvs_filtered}/{total_cvs_initial} CVs acceptés'
                progress_data = {
                    'step': 'must_have_filtering',
                    'current': total_cvs_initial,
                    'total': total_cvs_initial,
                    'progress': 1.0,
                    'message': progress_msg,
                    'skipped': False,
                    'criteria_count': len(must_have),
                }
                yield _sse_event("progress", progress_data)

            total_cvs_filtered = len(filtered_cvs)

            if total_cvs_filtered == 0:
                timestamp_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(start_time))
                summary = {
                    "results": [],
                    "qualified_results": [],
                    "metadata": {
                        "total_cvs": total_cvs_initial,
                        "filtered_must_have": 0,
                        "top_reranked": 0,
                        "qualified_pool_count": 0,
                        "duree_totale_s": round(time.time() - start_time, 2),
                        "must_have_criteria_count": len(must_have),
                        "must_have_skipped": not bool(must_have),
                        "must_have_provider_used": must_have_runtime_meta.get("provider_used"),
                        "must_have_model_used": must_have_runtime_meta.get("model_used"),
                        "must_have_duration_s": must_have_runtime_meta.get("duration_s"),
                        "must_have_fallback_used": must_have_runtime_meta.get("fallback_used"),
                        "nice_have_provider_used": None,
                        "nice_have_model_used": None,
                        "nice_have_duration_s": None,
                        "nice_have_fallback_used": None,
                        "reranking_provider_used": None,
                        "reranking_model_used": None,
                        "reranking_reasoning_effort_used": None,
                        "reranking_duration_s": None,
                        "reranking_attempt_count": None,
                        "reranking_fallback_used": None,
                        "timestamp": timestamp_str,
                    },
                }
                saved = MatchingFileService.save_matching_json(
                    project_id=project_id,
                    timestamp=timestamp_str,
                    results=summary,
                    enterprise_id=tenant_context.enterprise_id,
                )
                if not saved:
                    yield _sse_event("error", {
                        "code": "PERSISTENCE_ERROR",
                        "message": "Impossible de sauvegarder les résultats du matching",
                    })
                    return
                yield _sse_event("done", {"summary": summary})
                return

            # === ÉTAPE 2: Calcul similarité + Nice-have (compute_similarity_with_scoring fait les 2) ===
            embed_data = {'step': 'embedding', 'current': 0, 'total': total_cvs_filtered, 'progress': 0.0, 'message': 'Calcul des embeddings et nice-have'}
            yield _sse_event("progress", embed_data)

            def progress_callback_scoring(current, total):
                pass  # SSE déjà géré

            # Exécuter scoring en thread pool (fonction sync)
            scoring_task = loop.run_in_executor(
                None,
                lambda: get_matching_engine().compute_similarity_with_scoring(
                    job_text=job_text,
                    cvs=filtered_cvs,
                    nice_have_list=nice_have,
                    job_description=job_description,
                    progress_callback=progress_callback_scoring,
                    offre_struct=offre_data
                )
            )
            while not scoring_task.done():
                await asyncio.sleep(10)
                if not scoring_task.done():
                    yield _sse_event("progress", embed_data)
            scored_cvs, nice_have_runtime_meta = await scoring_task

            embed_done_data = {'step': 'embedding', 'current': total_cvs_filtered, 'total': total_cvs_filtered, 'progress': 1.0, 'message': 'Scoring et nice-have terminés'}
            yield _sse_event("progress", embed_done_data)

            # === ÉTAPE 3: Re-ranking LLM ===
            top_n = min(top_n_rerank, len(scored_cvs))
            rerank_msg = f'Re-ranking top {top_n}'
            rerank_data = {'step': 'reranking', 'current': 0, 'total': top_n, 'progress': 0.0, 'message': rerank_msg}
            yield _sse_event("progress", rerank_data)

            def progress_callback_rerank(current, total):
                pass

            # Exécuter re-ranking en thread pool avec le top_n de l'utilisateur
            rerank_task = loop.run_in_executor(
                None,
                lambda: get_matching_engine().rerank_with_llm(
                    top_cvs=scored_cvs,
                    job_description=job_description,
                    progress_callback=progress_callback_rerank,
                    top_n=top_n,  # Passer le paramètre utilisateur
                    nice_have_list=nice_have  # ✅ Passer les nice-have pour le reranking
                )
            )
            rerank_timeout_s = int(os.getenv("BRAINRH_RERANK_STREAM_TIMEOUT_S", "240"))
            rerank_timed_out = False
            rerank_started_at = time.time()
            rerank_runtime_meta = {
                "provider_used": "unknown",
                "model_used": None,
                "reasoning_effort_used": None,
                "duration_s": None,
                "attempt_count": None,
                "fallback_used": False,
            }
            while not rerank_task.done():
                await asyncio.sleep(10)
                if time.time() - rerank_started_at > rerank_timeout_s:
                    rerank_task.cancel()
                    rerank_timed_out = True
                    break
                if not rerank_task.done():
                    yield _sse_event("progress", rerank_data)
            if rerank_timed_out:
                reranked_cvs = [
                    {
                        "cv": cv.get("cv", "inconnu"),
                        "coefficient_qualite_experience": 1.0,
                        "commentaire_scoring": (
                            "Re-ranking LLM indisponible après timeout; classement conservé "
                            "à partir du score de similarité et des nice-have."
                        ),
                        "appreciation_globale": (
                            "Le profil est présenté avec le scoring automatique disponible. "
                            "Relancer le matching plus tard peut compléter l'analyse qualitative LLM."
                        ),
                        "evidences": [],
                        "evidence_map": None,
                        "flags_raw": None,
                    }
                    for cv in scored_cvs[:top_n]
                ]
                rerank_runtime_meta = {
                    "provider_used": "timeout",
                    "model_used": None,
                    "reasoning_effort_used": None,
                    "duration_s": round(time.time() - rerank_started_at, 2),
                    "attempt_count": None,
                    "fallback_used": True,
                }
            else:
                reranked_cvs, rerank_runtime_meta = await rerank_task

            rerank_done_data = {
                'step': 'reranking',
                'current': top_n,
                'total': top_n,
                'progress': 1.0,
                'message': 'Re-ranking indisponible, fallback scoring utilisé' if rerank_timed_out else 'Re-ranking terminé',
            }
            yield _sse_event("progress", rerank_done_data)

            # === Événement done ===
            total_duration = time.time() - start_time

            # Convertir les résultats en format API
            # La liste principale `results` reste le top reranké et son ordre ne change pas.
            results = []

            # Créer un dictionnaire des scores originaux indexé par nom de CV normalisé
            scored_map = {_normalize_cv_key(cv.get("cv")): cv for cv in scored_cvs}
            reranked_map: dict[str, dict] = {}

            for cv_result in reranked_cvs:
                cv_name = cv_result.get("cv", "inconnu")

                # Récupérer les données de scoring originales avec clé normalisée
                original_data = scored_map.get(_normalize_cv_key(cv_name), {})

                # Récupérer le coefficient d'expérience
                coefficient_experience = cv_result.get("coefficient_qualite_experience", 1.0)

                # Recalculer le score_final avec le coefficient d'expérience
                score_base = original_data.get("score_base", 0.0)
                bonus_nice_have = original_data.get("bonus_nice_have_multiplicateur", 1.0)
                score_final_with_coef = score_base * bonus_nice_have * coefficient_experience
                score_final_with_coef = max(0.0, min(1.0, score_final_with_coef))

                reranked_payload = _serialize_matching_result(
                    {
                        **original_data,
                        **cv_result,
                        "cv": cv_name,
                        "score_final": score_final_with_coef,
                        "score_base": score_base,
                        "bonus_nice_have_multiplicateur": bonus_nice_have,
                        "nice_have_manquants": original_data.get("nice_have_manquants", []),
                        "coefficient_qualite_experience": coefficient_experience,
                    },
                    project_id,
                    cv_file_map,
                    reranked=True,
                )
                results.append(reranked_payload)
                reranked_map[_normalize_cv_key(cv_name)] = reranked_payload

            # Trier les résultats par score_final décroissant (avec coefficient appliqué)
            results.sort(key=lambda x: x["score_final"], reverse=True)

            qualified_results = []
            for algorithmic_rank, scored_cv in enumerate(scored_cvs, start=1):
                cv_name = scored_cv.get("cv", "inconnu")
                reranked_payload = reranked_map.get(_normalize_cv_key(cv_name), {})
                qualified_payload = _serialize_matching_result(
                    {
                        **scored_cv,
                        **reranked_payload,
                        "cv": cv_name,
                        "score_final": scored_cv.get("score_final", 0.0),
                        "score_base": scored_cv.get("score_base", 0.0),
                        "bonus_nice_have_multiplicateur": scored_cv.get("bonus_nice_have_multiplicateur", 1.0),
                        "nice_have_manquants": scored_cv.get("nice_have_manquants", []),
                        "coefficient_qualite_experience": reranked_payload.get("coefficient_qualite_experience", 1.0),
                        "commentaire_scoring": reranked_payload.get("commentaire_scoring", ""),
                        "appreciation_globale": reranked_payload.get("appreciation_globale", ""),
                        "evidences": reranked_payload.get("evidences") or [],
                        "evidence_map": reranked_payload.get("evidence_map") or {},
                        "flags": reranked_payload.get("flags") or scored_cv.get("flags") or {},
                        "matrix_summary": reranked_payload.get("matrix_summary", ""),
                        "recommendation_level": reranked_payload.get("recommendation_level", ""),
                        "relevant_experience_years": reranked_payload.get("relevant_experience_years"),
                        "top_strengths": reranked_payload.get("top_strengths") or [],
                        "watchouts": reranked_payload.get("watchouts") or [],
                        "interview_focus": reranked_payload.get("interview_focus") or [],
                        "must_have_assessment": reranked_payload.get("must_have_assessment") or [],
                        "nice_have_assessment": reranked_payload.get("nice_have_assessment") or [],
                    },
                    project_id,
                    cv_file_map,
                    algorithmic_rank=algorithmic_rank,
                    reranked=_normalize_cv_key(cv_name) in reranked_map,
                )
                qualified_results.append(qualified_payload)

            summary = {
                "results": results,
                "qualified_results": qualified_results,
                "metadata": {
                    "total_cvs": total_cvs_initial,
                    "filtered_must_have": total_cvs_filtered,
                    "top_reranked": len(reranked_cvs),
                    "qualified_pool_count": len(scored_cvs),
                    "duree_totale_s": round(total_duration, 2),
                    "must_have_criteria_count": len(must_have),
                    "must_have_skipped": not bool(must_have),
                    "must_have_provider_used": must_have_runtime_meta.get("provider_used"),
                    "must_have_model_used": must_have_runtime_meta.get("model_used"),
                    "must_have_duration_s": must_have_runtime_meta.get("duration_s"),
                    "must_have_fallback_used": must_have_runtime_meta.get("fallback_used"),
                    "nice_have_provider_used": nice_have_runtime_meta.get("provider_used"),
                    "nice_have_model_used": nice_have_runtime_meta.get("model_used"),
                    "nice_have_duration_s": nice_have_runtime_meta.get("duration_s"),
                    "nice_have_fallback_used": nice_have_runtime_meta.get("fallback_used"),
                    "reranking_provider_used": rerank_runtime_meta.get("provider_used"),
                    "reranking_model_used": rerank_runtime_meta.get("model_used"),
                    "reranking_reasoning_effort_used": rerank_runtime_meta.get("reasoning_effort_used"),
                    "reranking_duration_s": rerank_runtime_meta.get("duration_s"),
                    "reranking_attempt_count": rerank_runtime_meta.get("attempt_count"),
                    "reranking_fallback_used": rerank_runtime_meta.get("fallback_used"),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
            }

            # Sauvegarder les résultats dans le projet (utilise le bon chemin: projects/ ou enterprises/)
            timestamp_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(start_time))
            saved = MatchingFileService.save_matching_json(
                project_id=project_id,
                timestamp=timestamp_str,
                results=summary,
                enterprise_id=tenant_context.enterprise_id,
            )
            if not saved:
                error_data = {
                    "code": "PERSISTENCE_ERROR",
                    "message": "Impossible de sauvegarder les résultats du matching",
                }
                yield _sse_event("error", error_data)
                return

            yield _sse_event("done", {"summary": summary})

        except Exception as e:
            error_data = {
                "code": "MATCHING_ERROR",
                "message": "Erreur lors du matching",
            }
            if not is_production():
                import traceback

                error_data["details"] = {"error": str(e), "traceback": traceback.format_exc()}
            yield _sse_event("error", error_data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/results")
async def get_results(
    project_id: str = Query(..., description="ID du projet"),
    timestamp: str = Query(..., description="Timestamp du matching (format: YYYY-MM-DD_HH-MM-SS)"),
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère les résultats d'un matching depuis le fichier results.json

    **Paramètres:**
    - `project_id`: ID du projet
    - `timestamp`: Timestamp du matching (ex: 2025-10-12_06-49-01)

    **Retourne:** Liste des CVs avec leurs scores et commentaires
    """
    try:
        results_data = MatchingFileService.load_matching_json(
            project_id,
            timestamp,
            enterprise_id=tenant.enterprise_id,
        )
        if not results_data:
            raise HTTPException(
                status_code=404,
                detail=f"Aucun résultat trouvé pour le projet {project_id} au timestamp {timestamp}"
            )

        # Retourner les résultats directement
        return results_data.get('results', [])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la lecture des résultats: {str(e)}"
        )


@router.get("/{project_id}/{timestamp}/results", response_model=MatchingResponse)
async def get_matching_results_by_params(
    project_id: str,
    timestamp: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère les résultats d'un matching depuis l'historique

    **Path params:**
    - `project_id`: ID du projet
    - `timestamp`: Timestamp du matching
    """
    try:
        from unified_project_manager import UnifiedProjectManager

        pm = UnifiedProjectManager(enterprises_folder="enterprises")
        matching_data = pm.load_matching(project_id, timestamp, tenant.enterprise_id)

        if not matching_data:
            raise HTTPException(
                status_code=404,
                detail=f"Matching {project_id}/{timestamp} introuvable"
            )

        # Nouveau format: results.json contient directement {"results": [...], "qualified_results": [...], "metadata": {...}}
        results_data = matching_data.get("results", [])
        qualified_results_data = matching_data.get("qualified_results", [])
        results = [_to_result_model(cv_result) for cv_result in results_data]
        qualified_results = [_to_result_model(cv_result) for cv_result in qualified_results_data]

        metadata_dict = matching_data.get("metadata", {})
        metadata = MatchingMetadata(
            total_cvs=metadata_dict.get("total_cvs", 0),
            filtered_must_have=metadata_dict.get("filtered_must_have", 0),
            top_reranked=metadata_dict.get("top_reranked", len(results)),
            qualified_pool_count=metadata_dict.get("qualified_pool_count", len(qualified_results)),
            duree_totale_s=metadata_dict.get("duree_totale_s", 0),
            must_have_criteria_count=metadata_dict.get("must_have_criteria_count"),
            must_have_skipped=metadata_dict.get("must_have_skipped"),
            must_have_provider_used=metadata_dict.get("must_have_provider_used"),
            must_have_model_used=metadata_dict.get("must_have_model_used"),
            must_have_duration_s=metadata_dict.get("must_have_duration_s"),
            must_have_fallback_used=metadata_dict.get("must_have_fallback_used"),
            nice_have_provider_used=metadata_dict.get("nice_have_provider_used"),
            nice_have_model_used=metadata_dict.get("nice_have_model_used"),
            nice_have_duration_s=metadata_dict.get("nice_have_duration_s"),
            nice_have_fallback_used=metadata_dict.get("nice_have_fallback_used"),
            reranking_provider_used=metadata_dict.get("reranking_provider_used"),
            reranking_model_used=metadata_dict.get("reranking_model_used"),
            reranking_reasoning_effort_used=metadata_dict.get("reranking_reasoning_effort_used"),
            reranking_duration_s=metadata_dict.get("reranking_duration_s"),
            reranking_attempt_count=metadata_dict.get("reranking_attempt_count"),
            reranking_fallback_used=metadata_dict.get("reranking_fallback_used"),
        )

        return MatchingResponse(results=results, qualified_results=qualified_results, metadata=metadata)

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Matching {project_id}/{timestamp} introuvable"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du chargement du matching: {str(e)}"
        )


@router.get("/{matching_id}/results", response_model=MatchingResponse)
async def get_matching_results(
    matching_id: str,
    tenant: TenantContext = Depends(get_matching_id_tenant_context),
):
    """
    Récupère les résultats d'un matching depuis l'historique

    **LEGACY ROUTE** - Format: {project_id}/{timestamp}

    **Note:** Utilisez plutôt `/matching/{project_id}/{timestamp}/results`
    """
    # Parser matching_id: format attendu "project_id/timestamp"
    parts = matching_id.split("/")
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="Format matching_id invalide. Attendu: {project_id}/{timestamp}"
        )

    project_id, timestamp = parts

    try:
        from unified_project_manager import UnifiedProjectManager

        pm = UnifiedProjectManager(enterprises_folder="enterprises")
        matching_data = pm.load_matching(project_id, timestamp, tenant.enterprise_id)

        if not matching_data:
            raise HTTPException(
                status_code=404,
                detail=f"Matching {matching_id} introuvable"
            )

        # Nouveau format: results.json contient directement {"results": [...], "qualified_results": [...], "metadata": {...}}
        results_data = matching_data.get("results", [])
        qualified_results_data = matching_data.get("qualified_results", [])
        results = [_to_result_model(cv_result) for cv_result in results_data]
        qualified_results = [_to_result_model(cv_result) for cv_result in qualified_results_data]

        metadata_dict = matching_data.get("metadata", {})
        metadata = MatchingMetadata(
            total_cvs=metadata_dict.get("total_cvs", 0),
            filtered_must_have=metadata_dict.get("filtered_must_have", 0),
            top_reranked=metadata_dict.get("top_reranked", len(results)),
            qualified_pool_count=metadata_dict.get("qualified_pool_count", len(qualified_results)),
            duree_totale_s=metadata_dict.get("duree_totale_s", 0),
            must_have_criteria_count=metadata_dict.get("must_have_criteria_count"),
            must_have_skipped=metadata_dict.get("must_have_skipped"),
            must_have_provider_used=metadata_dict.get("must_have_provider_used"),
            must_have_model_used=metadata_dict.get("must_have_model_used"),
            must_have_duration_s=metadata_dict.get("must_have_duration_s"),
            must_have_fallback_used=metadata_dict.get("must_have_fallback_used"),
            nice_have_provider_used=metadata_dict.get("nice_have_provider_used"),
            nice_have_model_used=metadata_dict.get("nice_have_model_used"),
            nice_have_duration_s=metadata_dict.get("nice_have_duration_s"),
            nice_have_fallback_used=metadata_dict.get("nice_have_fallback_used"),
            reranking_provider_used=metadata_dict.get("reranking_provider_used"),
            reranking_model_used=metadata_dict.get("reranking_model_used"),
            reranking_reasoning_effort_used=metadata_dict.get("reranking_reasoning_effort_used"),
            reranking_duration_s=metadata_dict.get("reranking_duration_s"),
            reranking_attempt_count=metadata_dict.get("reranking_attempt_count"),
            reranking_fallback_used=metadata_dict.get("reranking_fallback_used"),
            timestamp=metadata_dict.get("timestamp", "")
        )

        return MatchingResponse(results=results, qualified_results=qualified_results, metadata=metadata)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération du matching: {str(e)}"
        )


@router.get("/{project_id}/{timestamp}/export/csv")
async def export_matching_csv_new(
    project_id: str,
    timestamp: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Exporte les résultats en CSV

    **Path params:**
    - `project_id`: ID du projet
    - `timestamp`: Timestamp du matching (format: YYYY-MM-DD_HH-MM-SS)

    **Format CSV:**
    ```
    cv,score_final,score_base,bonus_nice_have,coefficient_experience,nice_have_manquants,commentaire_scoring
    cv1.pdf,0.85,0.80,0.95,1.15,"GraphQL;AWS",Excellent profil...
    ```
    """

    try:
        from unified_project_manager import UnifiedProjectManager
        import csv
        from io import StringIO

        pm = UnifiedProjectManager(enterprises_folder="enterprises")
        matching_data = pm.load_matching(project_id, timestamp, tenant.enterprise_id)

        if not matching_data:
            raise HTTPException(
                status_code=404,
                detail=f"Matching {project_id}/{timestamp} introuvable"
            )

        # Générer CSV
        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "cv",
            "score_final",
            "score_base",
            "bonus_nice_have_multiplicateur",
            "coefficient_qualite_experience",
            "nice_have_manquants",
            "commentaire_scoring",
            "appreciation_globale",
            "evidences",
            "evidence_map",
            "flags"
        ])

        # Rows - nouveau format
        results = matching_data.get("results", [])
        for cv_result in results:
            nice_have_manquants = cv_result.get("nice_have_manquants", [])
            nice_have_str = ";".join(nice_have_manquants) if nice_have_manquants else ""

            # Formater evidences
            evidences_list = cv_result.get("evidences", [])
            evidences_str = ""
            if evidences_list:
                evidences_str = " | ".join([
                    f"{ev.get('id', '')}:{ev.get('type', '')}:{ev.get('ref', '')}"
                    for ev in evidences_list
                ])

            # Formater evidence_map (normaliser None → {})
            evidence_map = cv_result.get("evidence_map") or {}
            evidence_map_str = ""
            if evidence_map:
                parts = []
                if evidence_map.get("commentaire_scoring"):
                    parts.append(f"scoring:[{','.join(evidence_map['commentaire_scoring'])}]")
                if evidence_map.get("appreciation_globale"):
                    parts.append(f"globale:[{','.join(evidence_map['appreciation_globale'])}]")
                evidence_map_str = " | ".join(parts)

            # Formater flags
            flags = cv_result.get("flags", {})
            flags_str = ""
            if flags:
                parts = []
                gappes = flags.get("gappes", [])
                if gappes:
                    gaps_details = ", ".join([
                        f"{g.get('period', '')} ({g.get('duration_months', 0)}m)"
                        for g in gappes
                    ])
                    parts.append(f"Gaps: {gaps_details}")
                overlaps = flags.get("overlaps", [])
                if overlaps:
                    overlaps_details = ", ".join([
                        f"{o.get('overlap_period', '')} ({o.get('overlap_days', 0)}j)"
                        for o in overlaps
                    ])
                    parts.append(f"Overlaps: {overlaps_details}")
                flags_str = " | ".join(parts)

            writer.writerow([
                cv_result.get("cv", "inconnu"),
                round(cv_result.get("score_final", 0.0), 4),
                round(cv_result.get("score_base", 0.0), 4),
                round(cv_result.get("bonus_nice_have_multiplicateur", 1.0), 4),
                round(cv_result.get("coefficient_qualite_experience", 1.0), 4),
                nice_have_str,
                cv_result.get("commentaire_scoring", "").replace("\n", " "),
                cv_result.get("appreciation_globale", "").replace("\n", " "),
                evidences_str,
                evidence_map_str,
                flags_str
            ])

        # Retourner CSV
        from fastapi.responses import Response

        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=matching_{project_id}_{timestamp}.csv"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'export CSV: {str(e)}"
        )


@router.get("/{project_id}/{timestamp}/export/excel")
async def export_matching_excel_new(
    project_id: str,
    timestamp: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Exporte les résultats en Excel (XLSX) avec mise en forme

    **Path params:**
    - `project_id`: ID du projet
    - `timestamp`: Timestamp du matching (format: YYYY-MM-DD_HH-MM-SS)

    **Format Excel:**
    - Feuille "Résultats" avec colonnes :
      - Rang, CV, Score Final, Score Base, Malus Nice-have, Coeff. Qualité, Nice-have Manquants, Commentaire, Appréciation
    - Tri par score final décroissant
    - Mise en forme (couleurs, bordures, largeur colonnes)
    """

    try:
        from unified_project_manager import UnifiedProjectManager
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from io import BytesIO

        pm = UnifiedProjectManager(enterprises_folder="enterprises")
        matching_data = pm.load_matching(project_id, timestamp, tenant.enterprise_id)

        if not matching_data:
            raise HTTPException(
                status_code=404,
                detail=f"Matching {project_id}/{timestamp} introuvable"
            )

        # Créer workbook Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Résultats Matching"

        # Styles
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=12)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        # En-têtes
        headers = [
            "Rang",
            "CV",
            "Score Final",
            "Score Base",
            "Malus Nice-have (×)",
            "Coeff. Qualité (×)",
            "Nice-have Manquants",
            "Commentaire Scoring",
            "Appréciation Globale",
            "Evidences",
            "Evidence Map",
            "Flags"
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

        # Récupérer et trier les résultats par score final décroissant
        results_data = matching_data.get("results", [])
        # Les résultats sont déjà triés par score final dans le fichier

        # Remplir les données
        for row_idx, cv_result in enumerate(results_data, start=2):
            nice_have_manquants = cv_result.get("nice_have_manquants", [])
            nice_have_str = ", ".join(nice_have_manquants) if nice_have_manquants else "Aucun"

            # Formater evidences
            evidences_list = cv_result.get("evidences", [])
            evidences_str = ""
            if evidences_list:
                evidences_str = "\n".join([
                    f"{ev.get('id', '')}: {ev.get('type', '')} - {ev.get('ref', '')}"
                    for ev in evidences_list
                ])

            # Formater evidence_map (normaliser None → {})
            evidence_map = cv_result.get("evidence_map") or {}
            evidence_map_str = ""
            if evidence_map:
                parts = []
                if evidence_map.get("commentaire_scoring"):
                    parts.append(f"Scoring: [{', '.join(evidence_map['commentaire_scoring'])}]")
                if evidence_map.get("appreciation_globale"):
                    parts.append(f"Globale: [{', '.join(evidence_map['appreciation_globale'])}]")
                evidence_map_str = "\n".join(parts)

            # Formater flags
            flags = cv_result.get("flags", {})
            flags_str = ""
            if flags:
                parts = []
                gappes = flags.get("gappes", [])
                if gappes:
                    parts.append(f"🔴 GAPS ({len(gappes)}):")
                    for g in gappes:
                        parts.append(f"  • {g.get('period', '')} ({g.get('duration_months', 0)} mois)")
                overlaps = flags.get("overlaps", [])
                if overlaps:
                    parts.append(f"⚠️ OVERLAPS ({len(overlaps)}):")
                    for o in overlaps:
                        same_company = " (même ent.)" if o.get('same_company') else ""
                        parts.append(f"  • {o.get('overlap_period', '')} ({o.get('overlap_days', 0)} jours){same_company}")
                flags_str = "\n".join(parts)

            row_data = [
                row_idx - 1,  # Rang
                cv_result.get("cv", "inconnu"),
                round(cv_result.get("score_final", 0.0), 4),
                round(cv_result.get("score_base", 0.0), 4),
                round(cv_result.get("bonus_nice_have_multiplicateur", 1.0), 4),
                round(cv_result.get("coefficient_qualite_experience", 1.0), 4),
                nice_have_str,
                cv_result.get("commentaire_scoring", ""),
                cv_result.get("appreciation_globale", ""),
                evidences_str,
                evidence_map_str,
                flags_str
            ]

            for col_idx, value in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)

                # Coloration score final
                if col_idx == 3:  # Score Final
                    score_pct = value * 100
                    if score_pct >= 80:
                        cell.font = Font(bold=True, color="006100")
                    elif score_pct >= 60:
                        cell.font = Font(bold=True, color="0070C0")
                    elif score_pct >= 40:
                        cell.font = Font(color="FFC000")
                    else:
                        cell.font = Font(color="C00000")

        # Ajuster largeurs colonnes
        column_widths = [8, 40, 12, 12, 18, 18, 30, 50, 50, 40, 30, 40]
        for col_idx, width in enumerate(column_widths, start=1):
            col_letter = chr(64 + col_idx) if col_idx <= 26 else chr(64 + (col_idx // 26)) + chr(64 + (col_idx % 26))
            ws.column_dimensions[col_letter].width = width

        # Figer première ligne
        ws.freeze_panes = "A2"

        # Sauvegarder dans BytesIO
        excel_output = BytesIO()
        wb.save(excel_output)
        excel_output.seek(0)

        # Retourner fichier Excel
        from fastapi.responses import Response

        return Response(
            content=excel_output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=matching_{project_id}_{timestamp}.xlsx"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'export Excel: {str(e)}"
        )


@router.get("/{project_id}/{timestamp}/export/json", response_model=MatchingResponse)
async def export_matching_json_new(
    project_id: str,
    timestamp: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Exporte les résultats en JSON (même format que /results)

    **Path params:**
    - `project_id`: ID du projet
    - `timestamp`: Timestamp du matching (format: YYYY-MM-DD_HH-MM-SS)
    """
    # Réutiliser la fonction get_matching_results_by_params
    return await get_matching_results_by_params(project_id, timestamp, tenant)
