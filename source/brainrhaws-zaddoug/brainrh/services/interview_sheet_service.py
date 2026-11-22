"""
InterviewSheetService - Gestion des fiches d'entretien
Couche service : DB JSONB pour données complètes
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import update
from sqlmodel import Session, select
import uuid

from brainrh.database import get_session
from brainrh.models import InterviewSheetDB
from brainrh.services.file_storage import FileStorage


class InterviewSheetService:
    """Service pour gestion des fiches d'entretien"""

    SCHEDULING_FIELDS = {"scheduled_at", "location", "scheduler_notes", "interviewer"}

    @staticmethod
    def create(
        candidate_id: str,
        job_id: str,
        matching_id: str,
        interviewer_id: str,
        data: Dict[str, Any],
        json_path: str
    ) -> Dict[str, Any]:
        """
        Crée une nouvelle fiche d'entretien (draft)

        Args:
            candidate_id: ID du candidat (CV)
            job_id: ID de l'offre
            matching_id: ID du matching source
            interviewer_id: ID du recruteur
            data: Données structurées de la fiche
            json_path: Chemin relatif vers le fichier JSON

        Returns:
            Données de la fiche créée
        """
        interview_sheet_id = str(uuid.uuid4())

        with get_session() as session:
            db_sheet = InterviewSheetDB(
                id=interview_sheet_id,
                candidate_id=candidate_id,
                job_id=job_id,
                matching_id=matching_id,
                interviewer_id=interviewer_id,
                status="draft",
                data=data,
                json_path=json_path,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            session.add(db_sheet)
            session.commit()
            session.refresh(db_sheet)

            return InterviewSheetService._to_dict(db_sheet)

    @staticmethod
    def get(interview_sheet_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère une fiche d'entretien par ID

        Args:
            interview_sheet_id: ID de la fiche

        Returns:
            Données de la fiche ou None
        """
        with get_session() as session:
            db_sheet = session.get(InterviewSheetDB, interview_sheet_id)

            if not db_sheet:
                return None

            return InterviewSheetService._to_dict(db_sheet)

    @staticmethod
    def update_partial(interview_sheet_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Met à jour partiellement une fiche d'entretien

        Args:
            interview_sheet_id: ID de la fiche
            updates: Dictionnaire de champs à mettre à jour

        Returns:
            Données mises à jour ou None
        """
        with get_session() as session:
            db_sheet = session.get(InterviewSheetDB, interview_sheet_id)

            if not db_sheet:
                return None

            # Mettre à jour les champs autorisés
            if "data" in updates:
                db_sheet.data = updates["data"]
            if "status" in updates:
                db_sheet.status = updates["status"]
                if updates["status"] != "completed":
                    db_sheet.completed_at = None
            if "pdf_url" in updates:
                db_sheet.pdf_url = updates["pdf_url"]

            # Gestion du planning (stockage dans JSONB data['scheduling'])
            scheduling_updates = {
                k: v for k, v in updates.items() if k in InterviewSheetService.SCHEDULING_FIELDS
            }
            
            if scheduling_updates:
                # Copie explicite pour détection de changement par SQLModel
                current_data = db_sheet.data.copy() if db_sheet.data else {}
                scheduling_data = InterviewSheetService.normalize_scheduling_data(
                    current_data.get("scheduling")
                )

                if "scheduled_at" in updates:
                    # Conversion datetime -> ISO string si nécessaire
                    val = updates["scheduled_at"]
                    if isinstance(val, datetime):
                        if val.tzinfo is None:
                            val = val.replace(tzinfo=timezone.utc)
                        else:
                            val = val.astimezone(timezone.utc)
                        scheduling_data["scheduled_at"] = val.isoformat().replace("+00:00", "Z")
                    else:
                        scheduling_data["scheduled_at"] = val
                
                if "location" in updates:
                    scheduling_data["location"] = updates["location"]
                
                if "scheduler_notes" in updates:
                    scheduling_data["notes"] = updates["scheduler_notes"]
                    scheduling_data.pop("scheduler_notes", None)
                
                if "interviewer" in updates:
                    scheduling_data["interviewer"] = updates["interviewer"]

                current_data["scheduling"] = scheduling_data
                db_sheet.data = current_data

            db_sheet.updated_at = datetime.now()

            session.add(db_sheet)
            session.commit()
            session.refresh(db_sheet)

            return InterviewSheetService._to_dict(db_sheet)

    @staticmethod
    def normalize_scheduling_data(raw_value: Any) -> Dict[str, Any]:
        scheduling_data = raw_value if isinstance(raw_value, dict) else {}
        normalized = dict(scheduling_data)
        if "scheduler_notes" in normalized and "notes" not in normalized:
            normalized["notes"] = normalized.get("scheduler_notes")
        normalized.pop("scheduler_notes", None)
        return normalized

    @staticmethod
    def load_sheet_payload(interview_sheet_id: str) -> Optional[tuple[Dict[str, Any], Dict[str, Any], str]]:
        interview_sheet = InterviewSheetService.get(interview_sheet_id)
        if not interview_sheet:
            return None

        json_path = interview_sheet["json_path"]
        if not FileStorage.file_exists(json_path):
            raise FileNotFoundError(f"Fichier JSON introuvable: {interview_sheet['json_path']}")

        current_data = FileStorage.load_json(json_path)
        return interview_sheet, current_data, json_path

    @staticmethod
    def merge_and_persist(
        interview_sheet_id: str,
        *,
        field_updates: Optional[Dict[str, Any]] = None,
        scheduling_updates: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        loaded = InterviewSheetService.load_sheet_payload(interview_sheet_id)
        if not loaded:
            return None

        interview_sheet, current_data, json_path = loaded
        del interview_sheet

        next_data = dict(current_data) if isinstance(current_data, dict) else {}
        for key, value in (field_updates or {}).items():
            next_data[key] = value

        if scheduling_updates:
            merged_scheduling = InterviewSheetService.normalize_scheduling_data(
                next_data.get("scheduling")
            )
            for key, value in scheduling_updates.items():
                normalized_key = "notes" if key == "scheduler_notes" else key
                merged_scheduling[normalized_key] = value
            next_data["scheduling"] = merged_scheduling

        FileStorage.save_json_atomic(json_path, next_data)

        db_updates: Dict[str, Any] = {"data": next_data}
        if status:
            db_updates["status"] = status
        return InterviewSheetService.update_partial(interview_sheet_id, db_updates)

    @staticmethod
    def attach_realtime_summary(
        interview_sheet_id: str,
        *,
        interview_id: str,
        summary_text: str,
        summary_data: Dict[str, Any],
        transcript_turns: list[Dict[str, Any]],
        notable_signals: list[Dict[str, Any]],
        registry_context: Optional[Dict[str, Any]] = None,
        completed_at: Optional[str] = None,
        realtime_status: str = "completed",
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        overall_appreciation = ""
        if isinstance(summary_data, dict):
            overall_appreciation = str(
                summary_data.get("overallAppreciation")
                or summary_data.get("overall_appreciation")
                or summary_data.get("appreciation_globale")
                or ""
            )
        realtime_payload = {
            "interview_id": interview_id,
            "status": realtime_status,
            "summary": summary_text,
            "summary_data": summary_data,
            "overall_appreciation": overall_appreciation,
            "appreciation_globale": overall_appreciation,
            "transcript_turns": transcript_turns,
            "notable_signals": notable_signals,
            "completed_at": completed_at,
        }
        if registry_context:
            realtime_payload["registry_context"] = registry_context

        return InterviewSheetService.publish_realtime_result(
            interview_sheet_id,
            realtime_payload=realtime_payload,
            status=status,
        )

    @staticmethod
    def attach_realtime_preparation(
        interview_sheet_id: str,
        *,
        interview_id: str,
        status: str,
        updated_at: str,
    ) -> Optional[Dict[str, Any]]:
        preparation_payload = {
            "interview_id": interview_id,
            "status": status,
            "updated_at": updated_at,
        }
        return InterviewSheetService._cas_realtime_projection(
            interview_sheet_id,
            preparation_payload=preparation_payload,
        )

    @staticmethod
    def publish_realtime_result(
        interview_sheet_id: str,
        *,
        realtime_payload: Dict[str, Any],
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return InterviewSheetService._cas_realtime_projection(
            interview_sheet_id,
            realtime_payload=realtime_payload,
            status=status,
        )

    @staticmethod
    def _cas_realtime_projection(
        interview_sheet_id: str,
        *,
        preparation_payload: Optional[Dict[str, Any]] = None,
        realtime_payload: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Project realtime state with a DB compare-and-swap before updating the JSON file."""
        for _attempt in range(3):
            with get_session() as session:
                db_sheet = session.get(InterviewSheetDB, interview_sheet_id)
                if not db_sheet:
                    return None

                observed_updated_at = db_sheet.updated_at
                current_data = dict(db_sheet.data) if isinstance(db_sheet.data, dict) else {}
                next_data = dict(current_data)
                may_publish_current = False

                if preparation_payload is not None:
                    next_data["realtime_preparation"] = preparation_payload

                if realtime_payload is not None:
                    interview_id = realtime_payload.get("interview_id")
                    preparation = current_data.get("realtime_preparation")
                    current_result = current_data.get("realtime_interview")
                    raw_history = current_data.get("realtime_interview_history")
                    history = list(raw_history) if isinstance(raw_history, list) else []

                    def history_id(item: Any) -> Any:
                        return item.get("interview_id") if isinstance(item, dict) else None

                    preparation_matches = (
                        isinstance(preparation, dict)
                        and preparation.get("interview_id") == interview_id
                    )
                    current_result_matches = (
                        isinstance(current_result, dict)
                        and history_id(current_result) == interview_id
                    )
                    result_slot_is_empty = (
                        not isinstance(preparation, dict)
                        and not isinstance(current_result, dict)
                    )
                    may_publish_current = (
                        preparation_matches or current_result_matches or result_slot_is_empty
                    )
                    if may_publish_current:
                        if (
                            isinstance(current_result, dict)
                            and history_id(current_result)
                            and history_id(current_result) != interview_id
                            and all(history_id(item) != history_id(current_result) for item in history)
                        ):
                            history.append(current_result)
                        next_data["realtime_interview"] = realtime_payload
                        next_data.pop("realtime_preparation", None)
                    elif interview_id and all(history_id(item) != interview_id for item in history):
                        history.append(realtime_payload)

                    if history:
                        next_data["realtime_interview_history"] = history

                updated_at = datetime.now()
                values: Dict[str, Any] = {
                    "data": next_data,
                    "updated_at": updated_at,
                }
                if status and (realtime_payload is None or may_publish_current):
                    values["status"] = status
                    if status != "completed":
                        values["completed_at"] = None

                result = session.exec(
                    update(InterviewSheetDB)
                    .where(
                        InterviewSheetDB.id == interview_sheet_id,
                        InterviewSheetDB.updated_at == observed_updated_at,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue

                try:
                    FileStorage.save_json_atomic(db_sheet.json_path, next_data)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                refreshed = session.get(InterviewSheetDB, interview_sheet_id)
                return InterviewSheetService._to_dict(refreshed) if refreshed else None

        raise RuntimeError(
            f"La fiche {interview_sheet_id} a changé pendant la projection realtime. Réessayez."
        )

    @staticmethod
    def finalize(interview_sheet_id: str) -> Optional[Dict[str, Any]]:
        """
        Finalise une fiche d'entretien (passe en status completed)

        Args:
            interview_sheet_id: ID de la fiche

        Returns:
            Données finalisées ou None
        """
        with get_session() as session:
            db_sheet = session.get(InterviewSheetDB, interview_sheet_id)

            if not db_sheet:
                return None

            db_sheet.status = "completed"
            db_sheet.completed_at = datetime.now()
            db_sheet.updated_at = datetime.now()

            session.add(db_sheet)
            session.commit()
            session.refresh(db_sheet)

            return InterviewSheetService._to_dict(db_sheet)

    @staticmethod
    def find_existing(candidate_id: str, job_id: str, matching_id: str) -> Optional[Dict[str, Any]]:
        """
        Recherche une fiche d'entretien existante pour ce trio (tous statuts)

        Args:
            candidate_id: ID du candidat
            job_id: ID de l'offre
            matching_id: ID du matching

        Returns:
            Fiche existante (la plus récente) ou None
        """
        with get_session() as session:
            query = select(InterviewSheetDB).where(
                InterviewSheetDB.candidate_id == candidate_id,
                InterviewSheetDB.job_id == job_id,
                InterviewSheetDB.matching_id == matching_id
            ).order_by(InterviewSheetDB.created_at.desc())

            db_sheet = session.exec(query).first()

            if not db_sheet:
                return None

            return InterviewSheetService._to_dict(db_sheet)

    @staticmethod
    def list_by_candidate(candidate_id: str) -> List[Dict[str, Any]]:
        """
        Liste toutes les fiches d'un candidat

        Args:
            candidate_id: ID du candidat

        Returns:
            Liste des fiches
        """
        with get_session() as session:
            query = select(InterviewSheetDB).where(
                InterviewSheetDB.candidate_id == candidate_id
            )
            db_sheets = session.exec(query).all()

            return [InterviewSheetService._to_dict(sheet) for sheet in db_sheets]

    @staticmethod
    def list_all(
        job_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Liste les fiches d'entretien avec filtres optionnels

        Args:
            job_id: Filtrer par projet (optionnel)
            limit: Limiter le nombre de résultats (optionnel)

        Returns:
            Liste des fiches d'entretien
        """
        with get_session() as session:
            query = select(InterviewSheetDB).order_by(InterviewSheetDB.created_at.desc())

            # Filtres
            if job_id:
                query = query.where(InterviewSheetDB.job_id == job_id)

            if limit:
                query = query.limit(limit)

            db_sheets = session.exec(query).all()
            return [InterviewSheetService._to_dict(sheet) for sheet in db_sheets]

    @staticmethod
    def _to_dict(db_sheet: InterviewSheetDB) -> Dict[str, Any]:
        """Convertit un objet DB en dictionnaire"""
        scheduling = (db_sheet.data or {}).get("scheduling") if isinstance(db_sheet.data, dict) else {}
        if not isinstance(scheduling, dict):
            scheduling = {}

        scheduler_notes = scheduling.get("notes")
        if scheduler_notes is None:
            scheduler_notes = scheduling.get("scheduler_notes")

        return {
            "id": db_sheet.id,
            "candidate_id": db_sheet.candidate_id,
            "job_id": db_sheet.job_id,
            "matching_id": db_sheet.matching_id,
            "interviewer_id": db_sheet.interviewer_id,
            "status": db_sheet.status,
            "data": db_sheet.data,
            "json_path": db_sheet.json_path,
            "created_at": db_sheet.created_at.isoformat(),
            "updated_at": db_sheet.updated_at.isoformat(),
            "completed_at": db_sheet.completed_at.isoformat() if db_sheet.completed_at else None,
            "pdf_url": db_sheet.pdf_url,
            # Champs virtuels extraits du JSONB
            "scheduled_at": scheduling.get("scheduled_at"),
            "location": scheduling.get("location"),
            "scheduler_notes": scheduler_notes,
            "interviewer": scheduling.get("interviewer"),
            "scheduling_provider": scheduling.get("provider"),
            "provider_booking": scheduling.get("provider_booking"),
            "booking_uid": scheduling.get("booking_uid"),
            "booking_status": scheduling.get("booking_status"),
            "meeting_url": scheduling.get("meeting_url"),
        }
