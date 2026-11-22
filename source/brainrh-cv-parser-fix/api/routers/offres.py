"""
Router Offres - CRUD et enrichissement d'offres
"""

import json
import sys
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query, UploadFile, File
from pydantic import BaseModel

from brainrh.paths import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from lib.models import Offre
import parseur_cv

router = APIRouter()


class ParseOffreRequest(BaseModel):
    """Requête pour parsing d'offre (texte brut)"""
    text: str
    model: str = "gpt-5-mini"


class EnrichOffreRequest(BaseModel):
    """Requête pour enrichissement d'offre"""
    description: str
    use_rome_api: bool = False
    rome_code: Optional[str] = None
    model: str = "gpt-5-mini"


@router.post("/{project_id}/parse")
async def parse_offre_text(project_id: str, request: ParseOffreRequest):
    """
    Parse une offre d'emploi (texte brut) en JSON structuré via GPT-5 mini
    + Extraction automatique des critères Must-have / Nice-to-have

    **Path params:**
    - `project_id`: ID du projet (pour référence future)

    **Body:**
    - `text`: Texte brut de l'offre
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Retourne:** Offre parsée au format JSON structuré avec critères classifiés
    """
    from matching_engine import MatchingEngine
    from config_loader import Config
    
    try:
        # 1. Parser la structure de l'offre
        job_raw_result = parseur_cv.analyze_text(request.text, parseur_cv.PROMPT_JOB_EXTRACTION)
        job_cleaned = parseur_cv.clean_json_text(job_raw_result)
        job_data = json.loads(job_cleaned)

        # 2. Extraire et classifier automatiquement les critères Must-have / Nice-to-have
        config = Config()
        engine = MatchingEngine(config._config)
        criteria_result = engine.extract_criteria_with_classification(request.text)

        # 3. Construire l'offre complète
        offre_data = {
            "sections": job_data.get("sections", {}),
            "must_have": criteria_result.get("must_haves", []),
            "nice_have": criteria_result.get("nice_to_haves", [])
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
async def parse_offre_file(project_id: str, file: UploadFile = File(...)):
    """
    Parse une offre d'emploi depuis un fichier (PDF ou DOCX)
    + Extraction automatique des critères Must-have / Nice-to-have

    **Path params:**
    - `project_id`: ID du projet

    **File:**
    - PDF ou DOCX contenant l'offre d'emploi

    **Retourne:** Offre parsée au format JSON structuré avec critères classifiés
    """
    import tempfile
    import os
    from matching_engine import MatchingEngine
    from config_loader import Config

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

        # 1. Parser la structure de l'offre
        job_raw_result = parseur_cv.analyze_text(offre_text, parseur_cv.PROMPT_JOB_EXTRACTION)
        job_cleaned = parseur_cv.clean_json_text(job_raw_result)
        job_data = json.loads(job_cleaned)

        # 2. Extraire et classifier automatiquement les critères Must-have / Nice-to-have
        config = Config()
        engine = MatchingEngine(config._config)
        criteria_result = engine.extract_criteria_with_classification(offre_text)

        # 3. Construire l'offre complète
        offre_data = {
            "sections": job_data.get("sections", {}),
            "must_have": criteria_result.get("must_haves", []),
            "nice_have": criteria_result.get("nice_to_haves", [])
        }

        return offre_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du parsing du fichier: {str(e)}"
        )


@router.post("/{project_id}/extract-criteria")
async def extract_criteria(project_id: str, request: ParseOffreRequest):
    """
    Extrait ET classifie automatiquement les critères Must-have / Nice-to-have depuis l'offre via LLM

    **Path params:**
    - `project_id`: ID du projet

    **Body:**
    - `text`: Texte de l'offre d'emploi
    - `model`: Modèle LLM (default: gpt-5-mini)

    **Retourne:** 
    ```json
    {
        "must_haves": ["critère 1", "critère 2", ...],
        "nice_to_haves": ["critère 1", "critère 2", ...],
        "count_must_haves": 5,
        "count_nice_to_haves": 3
    }
    ```
    """
    from matching_engine import MatchingEngine
    from config_loader import Config

    try:
        config = Config()
        engine = MatchingEngine(config._config)
        
        # Utiliser la nouvelle méthode avec classification automatique
        result = engine.extract_criteria_with_classification(request.text)

        return {
            "must_haves": result.get("must_haves", []),
            "nice_to_haves": result.get("nice_to_haves", []),
            "count_must_haves": len(result.get("must_haves", [])),
            "count_nice_to_haves": len(result.get("nice_to_haves", []))
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'extraction des critères: {str(e)}"
        )


@router.post("/{project_id}/apply")
async def apply_enrichment(project_id: str, request: dict):
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
async def create_offre(project_id: str, offre: Offre):
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
    import sys
    from brainrh.paths import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))

    from project_manager import ProjectManager

    try:
        pm = ProjectManager(projects_folder="projects")

        # Vérifier que le projet existe
        if not pm.get_project(project_id):
            raise HTTPException(
                status_code=404,
                detail=f"Projet {project_id} introuvable"
            )

        # Sauvegarder l'offre
        offre_data = offre.model_dump()
        pm.save_offer(project_id, offre_data)

        return offre

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la sauvegarde de l'offre: {str(e)}"
        )


@router.post("/{project_id}/enrich")
async def enrich_offre(project_id: str, request: EnrichOffreRequest):
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
    import sys
    from brainrh.paths import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))

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
            metier_label=request.description[:100]
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
async def get_offre(project_id: str):
    """
    Récupère l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    import sys
    from brainrh.paths import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))

    from project_manager import ProjectManager

    try:
        pm = ProjectManager(projects_folder="projects")

        offre_data = pm.load_offer(project_id)

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
async def update_offre(project_id: str, offre: Offre):
    """
    Modifie l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    import sys
    from brainrh.paths import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))

    from project_manager import ProjectManager

    try:
        pm = ProjectManager(projects_folder="projects")

        # Vérifier que le projet existe
        if not pm.get_project(project_id):
            raise HTTPException(
                status_code=404,
                detail=f"Projet {project_id} introuvable"
            )

        # Sauvegarder l'offre (écrase l'ancienne)
        offre_data = offre.model_dump()
        pm.save_offer(project_id, offre_data)

        return offre

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour de l'offre: {str(e)}"
        )


@router.delete("/{project_id}/offre", status_code=204)
async def delete_offre(project_id: str):
    """
    Supprime l'offre d'un projet

    **Path params:**
    - `project_id`: ID du projet
    """
    import sys
    from brainrh.paths import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))

    from project_manager import ProjectManager
    from pathlib import Path

    try:
        pm = ProjectManager(projects_folder="projects")

        # Vérifier que le projet existe
        if not pm.get_project(project_id):
            raise HTTPException(
                status_code=404,
                detail=f"Projet {project_id} introuvable"
            )

        # Supprimer le fichier offre_parsed.json
        project_dir = pm.get_project_path(project_id)
        offre_file = project_dir / "offre_parsed.json"

        if offre_file.exists():
            offre_file.unlink()

        # Mettre à jour le projet
        pm.update_project(project_id, {"offre_saved": False})

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression de l'offre: {str(e)}"
        )
