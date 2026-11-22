"""
Router Interview Sheets - Génération et gestion des fiches d'entretien
"""

import json
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, require_project_reader, require_project_writer
from brainrh.models.auth import UserDB
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.cv_service import CVService
from brainrh.services.project_service import ProjectService
from brainrh.services.file_storage import FileStorage
from brainrh.services.matching_file_service import MatchingFileService
from brainrh.services.project_file_service import ProjectFileService
from brainrh.services.llm_settings_service import (
    get_api_key,
    provider_base_url,
    resolve_llm_selection,
)
from brainrh.paths import PROJECT_ROOT, get_relative_path
from unified_project_manager import UnifiedProjectManager

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialiser UnifiedProjectManager
project_manager = UnifiedProjectManager(enterprises_folder="enterprises")


class GenerateInterviewSheetInput(BaseModel):
    """Input pour génération de fiche d'entretien"""
    candidate_id: str  # Nom fichier CV
    job_id: str  # ID projet
    matching_id: str  # ID matching (timestamp)
    interviewer_id: str = "default_interviewer"  # ID recruteur
    weights: Optional[Dict[str, float]] = None  # Pondérations personnalisées (optionnel)


class UpdateInterviewSheetInput(BaseModel):
    """Input pour mise à jour partielle de fiche d'entretien"""
    scorecard: Optional[Any] = None  # Grille d'évaluation remplie (liste ou dict)
    questions: Optional[Any] = None  # Questions modifiées/enrichies
    free_notes: Optional[str] = None  # Notes libres du recruteur
    recommendation: Optional[str] = None  # Recommandation finale
    status: Optional[str] = None  # Status (draft, in_progress)
    verdict: Optional[str] = None  # Verdict final
    verdict_detail: Optional[str] = None  # Justification verdict
    additional_tests: Optional[bool] = None  # Tests complémentaires requis
    residual_risks: Optional[str] = None  # Risques résiduels
    ai_plan_instructions: Optional[str] = Field(default=None, max_length=4000)

    # Champs pour la planification (stockés dans data['scheduling'])
    scheduled_at: Optional[datetime] = None  # ISO 8601 UTC
    location: Optional[str] = None
    scheduler_notes: Optional[str] = None
    interviewer: Optional[str] = None


def _json_chat_payload(model: str, full_prompt: str) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "Tu es un expert RH. Réponds uniquement avec du JSON valide."},
            {"role": "user", "content": full_prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 8000,
        "stream": False,
    }


def _extract_json_response(response_json: Dict[str, Any], provider: str) -> Dict[str, Any]:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"Réponse {provider} invalide: choices manquant")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"Réponse {provider} invalide: contenu vide")

    return json.loads(content)


def _call_json_chat_completion(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    full_prompt: str,
) -> Dict[str, Any]:
    response = requests.post(
        f"{base_url}/chat/completions",
        json=_json_chat_payload(model, full_prompt),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=90,
    )
    response.raise_for_status()
    return _extract_json_response(response.json(), provider)


def generate_sheet_with_available_llm(full_prompt: str) -> Dict[str, Any]:
    selection = resolve_llm_selection("interview_sheet_generation")
    provider_attempts = [(selection.provider, selection.model)]
    if selection.provider == "xai":
        provider_attempts.append(("openai", "gpt-4o-mini"))
    errors: list[str] = []

    for provider, model in provider_attempts:
        try:
            api_key = get_api_key(provider)
        except ValueError:
            errors.append(f"{provider}: clé API absente")
            continue

        try:
            logger.info("Génération fiche d'entretien via %s (%s)", provider, model)
            return _call_json_chat_completion(
                provider=provider,
                base_url=provider_base_url(provider) or "https://api.openai.com/v1",
                api_key=api_key,
                model=model,
                full_prompt=full_prompt,
            )
        except json.JSONDecodeError as exc:
            errors.append(f"{provider}: JSON invalide ({exc})")
            logger.warning("Réponse JSON invalide pendant la génération fiche via %s", provider)
        except requests.exceptions.RequestException as exc:
            errors.append(f"{provider}: erreur API ({exc})")
            logger.warning("Erreur API pendant la génération fiche via %s: %s", provider, exc)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            logger.warning("Erreur pendant la génération fiche via %s: %s", provider, exc)

    raise HTTPException(
        status_code=502,
        detail="Aucun provider LLM disponible pour générer la fiche d'entretien: " + " ; ".join(errors),
    )


def _can_read_sheet(interview_sheet: Dict[str, Any], current_user: UserDB) -> bool:
    try:
        require_project_reader(interview_sheet["job_id"], current_user)
        return True
    except HTTPException:
        return False


def _require_sheet_reader(interview_sheet: Dict[str, Any], current_user: UserDB) -> None:
    require_project_reader(interview_sheet["job_id"], current_user)


@router.post("/generate", status_code=201)
async def generate_interview_sheet(
    input_data: GenerateInterviewSheetInput,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Génère une fiche d'entretien structurée via LLM

    **Étapes:**
    1. Charger CV + Offre depuis les données existantes
    2. Construire le prompt avec contexte matching
    3. Appeler LLM (OpenAI) pour génération JSON
    4. Sauvegarder le fichier JSON dans interviews/<candidate>/
    5. Créer un enregistrement draft dans interview_sheets
    6. Retourner la fiche générée

    **Body:**
    - `candidate_id`: Nom fichier CV (ex: "CV_John_Doe.pdf")
    - `job_id`: ID du projet/offre
    - `matching_id`: ID du matching (timestamp)
    - `interviewer_id`: ID recruteur (optionnel, default: "default_interviewer")
    - `weights`: Pondérations personnalisées pour grille eval (optionnel)

    **Retourne:** Fiche d'entretien générée (JSON)
    """

    # ==========================================
    # 0. RÉCUPÉRER LE PROJET ET SON ENTERPRISE_ID
    # ==========================================

    require_project_writer(input_data.job_id, current_user)

    try:
        project = ProjectService.get_project(input_data.job_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Projet {input_data.job_id} introuvable")

        enterprise_id = project.get("enterprise_id")
        if not enterprise_id:
            raise HTTPException(status_code=500, detail=f"Projet {input_data.job_id} sans enterprise_id")

        # Obtenir le chemin du projet via UnifiedProjectManager
        project_dir = project_manager._get_project_dir(input_data.job_id, enterprise_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération projet: {str(e)}")

    # ==========================================
    # 0.5. VÉRIFIER SI UNE FICHE EXISTE DÉJÀ
    # ==========================================

    existing_sheet = InterviewSheetService.find_existing(
        candidate_id=input_data.candidate_id,
        job_id=input_data.job_id,
        matching_id=input_data.matching_id
    )

    if existing_sheet:
        logger.info(
            f"♻️ Fiche existante trouvée (id={existing_sheet['id']}, status={existing_sheet['status']}) "
            f"pour trio ({input_data.candidate_id}, {input_data.job_id}, {input_data.matching_id})"
        )
        try:
            existing_data = FileStorage.load_json(existing_sheet["json_path"])
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Fiche d'entretien existante incohérente: "
                    f"fichier JSON introuvable ({existing_sheet['json_path']})"
                ),
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Fiche d'entretien existante incohérente: "
                    f"JSON invalide ({existing_sheet['json_path']})"
                ),
            ) from exc

        return {
            "interview_sheet_id": existing_sheet["id"],
            "status": existing_sheet["status"],
            "data": existing_data,
            "json_path": existing_sheet["json_path"],
            "created_at": existing_sheet["created_at"],
            "updated_at": existing_sheet["updated_at"],
            "existing": True
        }

    # ==========================================
    # 1. CHARGER LES DONNÉES (CV + OFFRE)
    # ==========================================

    # Charger le CV (gérer mapping .pdf vs .json)
    # Charger le CV (depuis ApplicationDB ou fallback legacy)
    try:
        from sqlmodel import Session
        from brainrh.database import engine
        from brainrh.services.application_service import ApplicationService

        with Session(engine) as session:
            candidates = ApplicationService.get_project_candidates(session, input_data.job_id)

        # Essayer plusieurs variantes du nom de fichier original / id candidat
        candidate_variants = [
            input_data.candidate_id,  # Ex: CV X.pdf
            input_data.candidate_id.replace('.pdf', '.json'),  # CV X.json
            input_data.candidate_id.replace('.docx', '.json')  # CV X.json
        ]

        cv_data = None
        for cand in candidates:
            # Cherche dans le sous dict de cv_data
            if cand.get("cv_data"):
                # Dans cv_data, il y a filename, cv (le nom pdf), etc.
                if (cand.get("filename") in candidate_variants) or (cand["cv_data"].get("cv") in candidate_variants):
                    cv_data = cand["cv_data"]
                    break

        if not cv_data:
            raise HTTPException(
                status_code=404,
                detail=f"CV {input_data.candidate_id} introuvable (testé avec ApplicationDB/Legacy)"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur chargement CV: {str(e)}")

    # Charger l'offre depuis le backend storage actif.
    try:
        offre_data = ProjectFileService.load_offer(input_data.job_id, enterprise_id)
        if not offre_data:
            raise HTTPException(status_code=404, detail=f"Offre introuvable pour projet {input_data.job_id}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur chargement offre: {str(e)}")

    # Charger les résultats du matching (optionnel, pour contexte)
    matching_data = None
    try:
        matching_full = MatchingFileService.load_matching_json(
            input_data.job_id,
            input_data.matching_id,
            enterprise_id,
        )
        if matching_full:
            # Trouver le résultat du candidat spécifique (tester les variantes)
            for variant in candidate_variants:
                matching_data = next(
                    (r for r in matching_full.get("results", []) if r["cv"] == variant),
                    None
                )
                if matching_data:
                    break
            if not matching_data:
                for variant in candidate_variants:
                    matching_data = next(
                        (r for r in matching_full.get("qualified_results", []) if r["cv"] == variant),
                        None
                    )
                    if matching_data:
                        break
    except Exception:
        # Pas grave si matching introuvable, on continue sans contexte
        pass

    # ==========================================
    # 2. CONSTRUIRE LE PROMPT
    # ==========================================

    # Charger le template de prompt
    prompt_path = PROJECT_ROOT / "prompts" / "prompt_fiche_entretien.txt"
    if not prompt_path.exists():
        raise HTTPException(status_code=500, detail="Template prompt fiche d'entretien introuvable")

    prompt_template = prompt_path.read_text(encoding="utf-8")

    # Construire le contexte pour le LLM
    context = f"""
# DONNÉES DU CANDIDAT

**Nom:** {cv_data.get('informations_personnelles', {}).get('nom_complet', 'N/A')}
**Compétences:** {', '.join(cv_data.get('competences', {}).get('techniques', [])[:10])}
**Expériences:** {len(cv_data.get('experiences_professionnelles', []))} expérience(s)
**Formations:** {len(cv_data.get('formations', []))} formation(s)

# OFFRE D'EMPLOI

**Poste:** {offre_data.get('intitule', 'N/A')}
**Missions:** {offre_data.get('missions', 'N/A')[:300]}...
**Must-have:** {', '.join(offre_data.get('must_have', [])[:5])}
**Nice-have:** {', '.join(offre_data.get('nice_have', [])[:5])}

# RÉSULTATS DU MATCHING (si disponible)

"""
    if matching_data:
        context += f"""
**Score final:** {matching_data.get('score_final', 0):.2f}
**Appréciation:** {matching_data.get('appreciation_globale', 'N/A')[:200]}...
**Nice-have manquants:** {', '.join(matching_data.get('nice_have_manquants', []))}
"""
    else:
        context += "_(Données de matching non disponibles)_\n"

    # Prompt final
    full_prompt = prompt_template + "\n\n" + context

    # ==========================================
    # 3. APPELER LE LLM
    # ==========================================

    generated_data = generate_sheet_with_available_llm(full_prompt)

    # ==========================================
    # 4. SAUVEGARDER LE FICHIER JSON
    # ==========================================

    try:
        # Créer le dossier interviews/<candidate-id>/
        # Utiliser un identifiant sûr basé sur le nom du CV (sans extension)
        candidate_safe_id = Path(input_data.candidate_id).stem.replace(' ', '_')
        interviews_dir = project_dir / "interviews" / candidate_safe_id
        if FileStorage.is_local_storage():
            interviews_dir.mkdir(parents=True, exist_ok=True)

        # Nom fichier avec timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        json_filename = f"{timestamp}.json"
        json_filepath = interviews_dir / json_filename

        # Sauvegarder le JSON (atomique)
        FileStorage.save_json_atomic(str(json_filepath), generated_data)

        # Chemin relatif pour la DB
        json_path_relative = get_relative_path(json_filepath)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur sauvegarde fichier JSON: {str(e)}")

    # ==========================================
    # 5. CRÉER L'ENREGISTREMENT EN BASE
    # ==========================================

    try:
        interview_sheet = InterviewSheetService.create(
            candidate_id=input_data.candidate_id,
            job_id=input_data.job_id,
            matching_id=input_data.matching_id,
            interviewer_id=input_data.interviewer_id,
            data=generated_data,
            json_path=json_path_relative
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur création fiche: {str(e)}")

    # ==========================================
    # 6. RETOURNER LA FICHE
    # ==========================================

    return {
        "interview_sheet_id": interview_sheet["id"],
        "status": interview_sheet["status"],
        "data": interview_sheet["data"],
        "json_path": interview_sheet["json_path"],
        "created_at": interview_sheet["created_at"],
        "existing": False
    }


@router.get("/")
async def list_interview_sheets(
    job_id: Optional[str] = None,
    limit: Optional[int] = None,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Liste toutes les fiches d'entretien avec filtres optionnels

    **Query params:**
    - `job_id`: Filtrer par projet (optionnel)
    - `limit`: Limiter le nombre de résultats (optionnel)

    **Retourne:** Liste des fiches d'entretien
    """
    try:
        sheets = InterviewSheetService.list_all(
            job_id=job_id,
            limit=limit
        )
        can_read_by_job: Dict[str, bool] = {}
        readable_sheets = []
        for sheet in sheets:
            sheet_job_id = sheet["job_id"]
            if sheet_job_id not in can_read_by_job:
                can_read_by_job[sheet_job_id] = _can_read_sheet(sheet, current_user)
            if can_read_by_job[sheet_job_id]:
                readable_sheets.append(sheet)

        sheets = readable_sheets
        return {"sheets": sheets, "total": len(sheets)}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des fiches: {str(e)}"
        )


@router.get("/{interview_sheet_id}")
async def get_interview_sheet(
    interview_sheet_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Récupère une fiche d'entretien par son ID

    **Étapes:**
    1. Charger les métadonnées depuis la DB
    2. Recharger le JSON complet depuis json_path (source de vérité)
    3. Retourner la fiche complète

    **Path:**
    - `interview_sheet_id`: UUID de la fiche

    **Retourne:** Fiche d'entretien complète
    """

    # ==========================================
    # 1. CHARGER LES MÉTADONNÉES DB
    # ==========================================

    interview_sheet = InterviewSheetService.get(interview_sheet_id)

    if not interview_sheet:
        raise HTTPException(
            status_code=404,
            detail=f"Fiche d'entretien {interview_sheet_id} introuvable"
        )
    _require_sheet_reader(interview_sheet, current_user)

    # ==========================================
    # 2. RECHARGER LE JSON COMPLET
    # ==========================================

    try:
        # Une lecture suffit : le stockage signale lui-même un fichier absent.
        data = FileStorage.load_json(interview_sheet["json_path"])

        print(f"📥 [GET] Fiche {interview_sheet_id}")
        print(f"   Verdict dans JSON: {data.get('verdict', 'NON DÉFINI')}")

    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Fichier JSON introuvable: {interview_sheet['json_path']}"
        ) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lecture fichier JSON: {str(e)}"
        )

    # ==========================================
    # 3. RETOURNER LA FICHE COMPLÈTE
    # ==========================================

    scheduling_data = data.get("scheduling") if isinstance(data, dict) else {}
    if not isinstance(scheduling_data, dict):
        scheduling_data = {}
    appointment_id = scheduling_data.get("appointment_id")
    if appointment_id:
        try:
            from brainrh.services.interview_appointment_service import InterviewAppointmentService

            appointment = InterviewAppointmentService.get(str(appointment_id))
            existing_provider_artifacts = scheduling_data.get("provider_artifacts")
            scheduling_data = {
                **scheduling_data,
                "status": appointment["status"],
                "booking_status": appointment["status"],
                "provider_artifacts": InterviewAppointmentService.provider_artifacts_from_appointment(
                    appointment,
                    existing_provider_artifacts,
                ),
            }
            data["scheduling"] = scheduling_data
        except Exception as exc:
            logger.warning("Impossible d'hydrater les artefacts appointment %s: %s", appointment_id, exc)

    scheduler_notes = scheduling_data.get("notes")
    if scheduler_notes is None:
        scheduler_notes = scheduling_data.get("scheduler_notes")

    return {
        "id": interview_sheet["id"],
        "candidate_id": interview_sheet["candidate_id"],
        "job_id": interview_sheet["job_id"],
        "matching_id": interview_sheet["matching_id"],
        "interviewer_id": interview_sheet["interviewer_id"],
        "status": interview_sheet["status"],
        "data": data,  # Données rechargées depuis le fichier
        "json_path": interview_sheet["json_path"],
        "created_at": interview_sheet["created_at"],
        "updated_at": interview_sheet["updated_at"],
        "completed_at": interview_sheet["completed_at"],
        "pdf_url": interview_sheet["pdf_url"],
        # Champs de planification (issus du JSON, source de vérité)
        "scheduled_at": scheduling_data.get("scheduled_at"),
        "location": scheduling_data.get("location"),
        "scheduler_notes": scheduler_notes,
        "interviewer": scheduling_data.get("interviewer"),
    }


@router.patch("/{interview_sheet_id}")
async def update_interview_sheet(
    interview_sheet_id: str,
    updates: UpdateInterviewSheetInput,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Met à jour partiellement une fiche d'entretien

    **Étapes:**
    1. Charger les métadonnées depuis la DB
    2. Lire le JSON complet depuis json_path
    3. Fusionner les nouveaux champs dans le JSON
    4. Réécrire le fichier JSON (atomique)
    5. Mettre à jour la DB (data + status + updated_at)

    **Path:**
    - `interview_sheet_id`: UUID de la fiche

    **Body:**
    - `scorecard`: Grille d'évaluation remplie (optionnel)
    - `questions`: Questions modifiées (optionnel)
    - `free_notes`: Notes libres (optionnel)
    - `recommendation`: Recommandation finale (optionnel)
    - `status`: Nouveau statut (draft/in_progress) (optionnel)

    **Retourne:** {"success": true, "updated_at": ...}
    """

    # ==========================================
    # 1. VÉRIFIER QUE LA FICHE EXISTE
    # ==========================================

    interview_sheet = InterviewSheetService.get(interview_sheet_id)

    if not interview_sheet:
        raise HTTPException(
            status_code=404,
            detail=f"Fiche d'entretien {interview_sheet_id} introuvable"
        )

    require_project_writer(interview_sheet["job_id"], current_user)

    # ==========================================
    # 2. LIRE LE JSON COMPLET
    # ==========================================

    try:
        if not FileStorage.file_exists(interview_sheet["json_path"]):
            raise HTTPException(
                status_code=500,
                detail=f"Fichier JSON introuvable: {interview_sheet['json_path']}"
            )

        # Charger les données actuelles
        current_data = FileStorage.load_json(interview_sheet["json_path"])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lecture fichier JSON: {str(e)}"
        )

    # ==========================================
    # 3. FUSIONNER LES NOUVEAUX CHAMPS
    # ==========================================

    # Construire le dictionnaire des mises à jour (seulement les champs fournis)
    updates_dict = updates.model_dump(exclude_unset=True)

    print(f"💾 [PATCH] Fiche {interview_sheet_id}")
    print(f"   Champs à mettre à jour: {list(updates_dict.keys())}")
    if 'verdict' in updates_dict:
        print(f"   ⚖️  Verdict: {updates_dict['verdict']}")

    # Extraire les champs de planification
    scheduling_fields = ["scheduled_at", "location", "scheduler_notes", "interviewer"]
    scheduling_updates = {f: updates_dict.pop(f) for f in scheduling_fields if f in updates_dict}

    # Conversions éventuelles (datetime -> ISO string UTC)
    if "scheduled_at" in scheduling_updates and scheduling_updates["scheduled_at"] is not None:
        v = scheduling_updates["scheduled_at"]
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            else:
                v = v.astimezone(timezone.utc)
            scheduling_updates["scheduled_at"] = v.isoformat().replace("+00:00", "Z")
        else:
            scheduling_updates["scheduled_at"] = v

    # Merge autres champs hors status
    for k, v in updates_dict.items():
        if k != "status":
            current_data[k] = v

    # Merge scheduling dans current_data["scheduling"]
    if scheduling_updates:
        scheduling_data = current_data.get("scheduling") or {}
        if not isinstance(scheduling_data, dict):
            scheduling_data = {}

        # Migration douce : anciens JSON pouvaient stocker "scheduler_notes"
        if "scheduler_notes" in scheduling_data and "notes" not in scheduling_data:
            scheduling_data["notes"] = scheduling_data.get("scheduler_notes")
        if "scheduler_notes" in scheduling_data:
            scheduling_data.pop("scheduler_notes", None)

        if "scheduled_at" in scheduling_updates:
            scheduling_data["scheduled_at"] = scheduling_updates["scheduled_at"]
        if "location" in scheduling_updates:
            scheduling_data["location"] = scheduling_updates["location"]
        if "interviewer" in scheduling_updates:
            scheduling_data["interviewer"] = scheduling_updates["interviewer"]
        if "scheduler_notes" in scheduling_updates:
            scheduling_data["notes"] = scheduling_updates["scheduler_notes"]

        current_data["scheduling"] = scheduling_data
        print(f"   📅 Planning mis à jour: {scheduling_updates}")

    # ==========================================
    # 4. RÉÉCRIRE LE FICHIER JSON (ATOMIQUE)
    # ==========================================

    try:
        # Écriture atomique
        FileStorage.save_json_atomic(interview_sheet["json_path"], current_data)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur écriture fichier JSON: {str(e)}"
        )

    # ==========================================
    # 5. METTRE À JOUR LA DB
    # ==========================================

    try:
        db_updates = {
            "data": current_data
        }

        # Si le status est fourni, le mettre à jour
        if "status" in updates_dict:
            db_updates["status"] = updates_dict["status"]

        print(f"   💾 Mise à jour DB: {list(db_updates.keys())}")

        updated_sheet = InterviewSheetService.update_partial(
            interview_sheet_id,
            db_updates
        )

        if not updated_sheet:
            raise HTTPException(
                status_code=500,
                detail="Erreur mise à jour base de données"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur mise à jour DB: {str(e)}"
        )

    # ==========================================
    # 6. RETOURNER LE SUCCÈS
    # ==========================================

    return {
        "success": True,
        "updated_at": updated_sheet["updated_at"]
    }


@router.post("/{interview_sheet_id}/finalize")
async def finalize_interview_sheet(
    interview_sheet_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Finalise une fiche d'entretien (marque comme completed)

    **Étapes:**
    1. Vérifier que la fiche existe
    2. Marquer status = completed, completed_at, updated_at
    3. Retourner le succès avec statut actualisé

    **Path:**
    - `interview_sheet_id`: UUID de la fiche

    **Retourne:** {"success": true, "status": "completed", "completed_at": ...}
    """

    # ==========================================
    # 1. VÉRIFIER QUE LA FICHE EXISTE
    # ==========================================

    interview_sheet = InterviewSheetService.get(interview_sheet_id)

    if not interview_sheet:
        raise HTTPException(
            status_code=404,
            detail=f"Fiche d'entretien {interview_sheet_id} introuvable"
        )

    require_project_writer(interview_sheet["job_id"], current_user)

    # ==========================================
    # 2. FINALISER LA FICHE
    # ==========================================

    try:
        finalized_sheet = InterviewSheetService.finalize(interview_sheet_id)

        if not finalized_sheet:
            raise HTTPException(
                status_code=500,
                detail="Erreur finalisation fiche"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur finalisation: {str(e)}"
        )

    # ==========================================
    # 3. RETOURNER LE SUCCÈS
    # ==========================================

    return {
        "success": True,
        "status": finalized_sheet["status"],
        "completed_at": finalized_sheet["completed_at"],
        "updated_at": finalized_sheet["updated_at"]
    }
