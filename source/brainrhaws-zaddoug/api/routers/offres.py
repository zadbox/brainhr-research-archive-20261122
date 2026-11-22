"""
Router Offres - CRUD et enrichissement d'offres
"""

import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query, UploadFile, File, Depends
from pydantic import BaseModel

from api.dependencies import get_project_tenant_context, get_project_writer_context
from brainrh.services.auth_service import TenantContext
from lib.models import Offre
import parseur_cv

router = APIRouter()
OFFER_ENRICHMENT_FAST_MODEL = "gpt-5.4-mini"


class ParseOffreRequest(BaseModel):
    """Requête pour parsing d'offre (texte brut)"""
    text: str
    model: Optional[str] = None


class EnrichOffreRequest(BaseModel):
    """Requête pour enrichissement d'offre"""
    description: str
    use_rome_api: bool = False
    rome_code: Optional[str] = None
    model: Optional[str] = None


def _offer_enrichment_model(model_override: Optional[str]) -> str:
    return model_override or OFFER_ENRICHMENT_FAST_MODEL


@router.post("/{project_id}/parse")
async def parse_offre_text(
    project_id: str,
    request: ParseOffreRequest,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Parse une offre d'emploi (texte brut) en JSON structuré via GPT-5 mini

    **Path params:**
    - `project_id`: ID du projet (pour référence future)

    **Body:**
    - `text`: Texte brut de l'offre
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Retourne:** Offre parsée au format JSON structuré
    """
    try:
        # Utiliser le parseur existant
        job_raw_result = parseur_cv.analyze_text(
            request.text,
            parseur_cv.PROMPT_JOB_EXTRACTION,
            model_name=request.model,
            process_id="offer_parsing",
        )
        job_cleaned = parseur_cv.clean_json_text(job_raw_result)

        job_data = json.loads(job_cleaned)

        # Normaliser pour correspondre au modèle Offre
        offre_data = {
            "sections": job_data.get("sections", {}),
            "must_have": [],
            "nice_have": [],
            "source_text": request.text,
            "source_file_name": None,
        }

        return offre_data

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de parsing JSON: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du parsing de l'offre: {str(e)}"
        )


@router.post("/{project_id}/parse/file")
async def parse_offre_file(
    project_id: str,
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Parse une offre d'emploi depuis un fichier (PDF ou DOCX)

    **Path params:**
    - `project_id`: ID du projet

    **File:**
    - PDF ou DOCX contenant l'offre d'emploi

    **Retourne:** Offre parsée au format JSON structuré
    """
    import tempfile
    import os

    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(
            status_code=400,
            detail="Format de fichier non supporté. Utilisez PDF ou DOCX."
        )

    try:
        # Sauvegarder temporairement
        with tempfile.NamedTemporaryFile(delete=False, suffix=file.filename) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name

        # Extraire le texte
        if file.filename.endswith('.pdf'):
            offre_text = parseur_cv.extract_text_from_pdf(tmp_path)
        elif file.filename.endswith('.docx'):
            offre_text = parseur_cv.extract_text_from_docx(tmp_path)

        # Nettoyer
        os.unlink(tmp_path)

        # Parser avec GPT-5 mini
        job_raw_result = parseur_cv.analyze_text(
            offre_text,
            parseur_cv.PROMPT_JOB_EXTRACTION,
            process_id="offer_parsing",
        )
        job_cleaned = parseur_cv.clean_json_text(job_raw_result)

        job_data = json.loads(job_cleaned)

        # Normaliser
        offre_data = {
            "sections": job_data.get("sections", {}),
            "must_have": [],
            "nice_have": [],
            "source_text": offre_text,
            "source_file_name": file.filename,
        }

        return offre_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du parsing du fichier: {str(e)}"
        )


@router.post("/{project_id}/extract-criteria")
async def extract_criteria(
    project_id: str,
    request: ParseOffreRequest,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Extrait les critères must-have depuis l'offre via LLM

    **Path params:**
    - `project_id`: ID du projet

    **Body:**
    - `text`: Texte de l'offre d'emploi
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Retourne:** Liste de critères must-have suggérés
    """
    from matching_engine import MatchingEngine
    from config_loader import Config

    try:
        config = Config()
        engine = MatchingEngine(config._config)
        criteria = engine.extract_must_have_with_llm(request.text, model_override=request.model)

        return {
            "criteria": criteria,
            "count": len(criteria)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'extraction des critères: {str(e)}"
        )


@router.post("/{project_id}/apply")
async def apply_enrichment(
    project_id: str,
    request: dict,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Applique les enrichissements sélectionnés à l'offre

    **Path params:**
    - `project_id`: ID du projet

    **Body:**
    - `offre`: Offre originale
    - `enrichment`: Résultat de l'enrichissement IA
    - `selections`: Sélections utilisateur {"competences": [0, 2], "outils": [1], ...}
    - `question_responses`: Réponses aux questions de clarification (optionnel)

    **Retourne:** Offre enrichie fusionnée
    """
    from offer_enrichment import merge_enrichment, integrate_question_responses

    try:
        offre = request.get("offre")
        enrichment = request.get("enrichment")
        selections = request.get("selections")
        question_responses = request.get("question_responses", {})

        if not all([offre, enrichment, selections]):
            raise HTTPException(
                status_code=400,
                detail="Paramètres manquants: offre, enrichment, selections requis"
            )

        # Fusionner les enrichissements
        offre_enrichie = merge_enrichment(offre, enrichment, selections)

        # Intégrer les réponses aux questions
        if question_responses:
            offre_enrichie = integrate_question_responses(offre_enrichie, question_responses)

        return offre_enrichie

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'application de l'enrichissement: {str(e)}"
        )


@router.post("/{project_id}/offre", response_model=Offre, status_code=201)
async def create_offre(
    project_id: str,
    offre: Offre,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Crée/sauvegarde une offre dans un projet

    **Path params:**
    - `project_id`: ID du projet où sauvegarder l'offre

    **Body:**
    - `sections`: Sections de l'offre (titre, compétences, etc.)
    - `must_have`: Critères éliminatoires (liste de strings)
    - `nice_have`: Critères souhaitables (liste de strings)

    **Retourne:** Offre sauvegardée
    """
    from brainrh.services.project_path_resolver import ProjectPathResolver
    from brainrh.services.project_file_service import ProjectFileService

    try:
        # Vérifier que le projet existe
        try:
            ProjectPathResolver.get_project_dir(project_id, tenant.enterprise_id)
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail=str(e)
            )

        # Sauvegarder l'offre
        offre_data = offre.model_dump()
        ProjectFileService.save_offer(project_id, offre_data, tenant.enterprise_id)

        return offre

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la sauvegarde de l'offre: {str(e)}"
        )


@router.post("/{project_id}/enrich")
async def enrich_offre(
    project_id: str,
    request: EnrichOffreRequest,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Enrichit une offre via LLM (génération must-have/nice-have)

    **Fonctionnement:**
    1. Envoie la description à un LLM
    2. Le LLM génère automatiquement propositions de compléments
    3. Optionnel: intégration France Travail API (ROME) pour enrichissement

    **Path params:**
    - `project_id`: ID du projet (pour référence future)

    **Body:**
    - `description`: Description textuelle de l'offre
    - `use_rome_api`: Utiliser France Travail API (default: false)
    - `rome_code`: Code ROME si use_rome_api=true
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Retourne:** Propositions d'enrichissement avec coverage_score
    """
    from offer_enrichment import enrich_offer_intelligently

    # TODO: use_rome_api non implémenté (nécessite rome_api.py)
    if request.use_rome_api:
        raise HTTPException(
            status_code=501,
            detail="Intégration France Travail API non implémentée"
        )

    # Créer offre basique depuis description
    offre_dict = {
        "titre": request.description[:100],  # Première ligne comme titre
        "description": request.description,
        "competences_techniques": [],
        "competences_transversales": [],
        "langues": [],
        "experiences_professionnelles": [],
        "formations": [],
        "certifications": [],
        "projets": []
    }

    try:
        # Enrichissement LLM
        enrichment = await enrich_offer_intelligently(
            offre_json=offre_dict,
            metier_label=request.description[:100],
            model_override=_offer_enrichment_model(request.model),
        )

        return {
            "coverage_score": enrichment.get("coverage_score", 0),
            "propositions": enrichment.get("propositions", {})
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'enrichissement: {str(e)}"
        )


@router.get("/{project_id}/offre", response_model=Offre)
async def get_offre(
    project_id: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    from brainrh.services.project_file_service import ProjectFileService

    try:
        offre_data = ProjectFileService.load_offer(project_id, tenant.enterprise_id)

        if not offre_data:
            raise HTTPException(
                status_code=404,
                detail=f"Offre du projet {project_id} introuvable"
            )

        return Offre(**offre_data)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération de l'offre: {str(e)}"
        )


@router.put("/{project_id}/offre", response_model=Offre)
async def update_offre(
    project_id: str,
    offre: Offre,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Modifie l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    from brainrh.services.project_path_resolver import ProjectPathResolver
    from brainrh.services.project_file_service import ProjectFileService

    try:
        # Vérifier que le projet existe
        try:
            ProjectPathResolver.get_project_dir(project_id, tenant.enterprise_id)
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail=str(e)
            )

        # Sauvegarder l'offre (écrase l'ancienne)
        offre_data = offre.model_dump()
        ProjectFileService.save_offer(project_id, offre_data, tenant.enterprise_id)

        return offre

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour de l'offre: {str(e)}"
        )


@router.delete("/{project_id}/offre", status_code=204)
async def delete_offre(
    project_id: str,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Supprime l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    from brainrh.services.project_path_resolver import ProjectPathResolver
    from brainrh.services.project_file_service import ProjectFileService

    try:
        # Vérifier que le projet existe
        try:
            ProjectPathResolver.get_project_dir(project_id, tenant.enterprise_id)
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail=str(e)
            )

        # Supprimer le fichier offre_parsed.json
        ProjectFileService.delete_offer(project_id, tenant.enterprise_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression de l'offre: {str(e)}"
        )
