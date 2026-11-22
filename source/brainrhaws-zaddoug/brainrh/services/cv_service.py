"""
CVService - Gestion des CV
Couche service : DB (index cv_meta) + JSON (données complètes)
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from sqlmodel import Session, select

from brainrh.database import get_session
from brainrh.models import CVMetaDB, ProjectDB
from brainrh.services.file_storage import FileStorage


class CVService:
    """Service pour gestion des CV (DB + JSON)"""

    @staticmethod
    def _normalize_cv_filename(filename: str) -> str:
        normalized = Path(str(filename).strip()).name
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            raise ValueError("filename est requis")
        if not normalized.endswith(".json"):
            normalized = f"{Path(normalized).stem}.json"
        return normalized

    @staticmethod
    def exists(project_id: str, filename: str) -> bool:
        """
        Vérifie si un CV existe déjà dans un projet

        Args:
            project_id: ID du projet
            filename: Nom du fichier CV tel qu'enregistré en base (généralement *.json)

        Returns:
            True si le CV existe, False sinon
        """
        with get_session() as session:
            existing = session.exec(
                select(CVMetaDB).where(
                    CVMetaDB.project_id == project_id,
                    CVMetaDB.filename == filename
                )
            ).first()
            return existing is not None

    @staticmethod
    def get_unique_filename(project_id: str, original_filename: str) -> Tuple[str, bool]:
        """
        Génère un nom de fichier unique pour éviter les collisions

        Si le filename existe déjà dans le projet, ajoute un suffixe horodaté
        au format: <base>__<timestamp><ext>

        Args:
            project_id: ID du projet
            original_filename: Nom de fichier original

        Returns:
            Tuple (filename_unique, collision_detected)
            - filename_unique: Nom de fichier final (original ou avec suffixe)
            - collision_detected: True si une collision a été détectée
        """
        path = Path(original_filename)
        base = path.stem  # Nom sans extension
        ext = path.suffix  # Extension avec le point (ou vide)

        # Les enregistrements en base utilisent l'extension .json
        json_filename = f"{base}.json"

        # Aucun conflit → on conserve le nom d'origine
        if not CVService.exists(project_id, json_filename):
            return original_filename, False

        # Collision détectée → générer un suffixe horodaté
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        counter = 0

        while True:
            suffix = f"{timestamp}" if counter == 0 else f"{timestamp}_{counter}"
            candidate_base = f"{base}__{suffix}"
            candidate_json = f"{candidate_base}.json"

            # Sortir dès que le nom JSON associé n'existe pas
            if not CVService.exists(project_id, candidate_json):
                unique_filename = f"{candidate_base}{ext}"
                return unique_filename, True

            counter += 1

    @staticmethod
    def list_all(limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Liste tous les CV indexés

        Args:
            limit: Limite le nombre de résultats (optionnel)

        Returns:
            Liste des métadonnées CV
        """
        cvs = []

        with get_session() as session:
            query = select(CVMetaDB).order_by(CVMetaDB.parsed_at.desc())

            if limit:
                query = query.limit(limit)

            db_cvs = session.exec(query).all()

            for db_cv in db_cvs:
                cvs.append({
                    "filename": db_cv.filename,
                    "project_id": db_cv.project_id,
                    "json_path": db_cv.json_path,
                    "file_path": db_cv.file_path,
                    "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                    "candidat_nom": db_cv.candidat_nom,
                    "candidat_titre": db_cv.candidat_titre,
                    "last_modified": db_cv.last_modified.isoformat() if db_cv.last_modified else None
                })

        return cvs

    @staticmethod
    def list_by_project(project_id: str) -> List[Dict[str, Any]]:
        """
        Liste les CV d'un projet

        Args:
            project_id: ID du projet

        Returns:
            Liste des métadonnées CV
        """
        cvs = []

        with get_session() as session:
            query = select(CVMetaDB).where(
                CVMetaDB.project_id == project_id
            ).order_by(CVMetaDB.parsed_at.desc())

            db_cvs = session.exec(query).all()

            for db_cv in db_cvs:
                cvs.append({
                    "filename": db_cv.filename,
                    "project_id": db_cv.project_id,
                    "json_path": db_cv.json_path,
                    "file_path": db_cv.file_path,
                    "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                    "candidat_nom": db_cv.candidat_nom,
                    "candidat_titre": db_cv.candidat_titre,
                    "last_modified": db_cv.last_modified.isoformat() if db_cv.last_modified else None
                })

        return cvs

    @staticmethod
    def list_by_enterprise(enterprise_id: str) -> List[Dict[str, Any]]:
        """
        Liste les CV d'une entreprise (tous projets confondus)

        Args:
            enterprise_id: ID de l'entreprise

        Returns:
            Liste des métadonnées CV
        """
        cvs = []

        with get_session() as session:
            from brainrh.repositories.enterprise_scoped_repository import EnterpriseScopedRepository
            cv_query = EnterpriseScopedRepository.query_linked_to_project(CVMetaDB, enterprise_id)
            cv_query = cv_query.order_by(CVMetaDB.parsed_at.desc())

            db_cvs = session.exec(cv_query).all()

            for db_cv in db_cvs:
                cvs.append({
                    "filename": db_cv.filename,
                    "project_id": db_cv.project_id,
                    "json_path": db_cv.json_path,
                    "file_path": db_cv.file_path,
                    "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                    "candidat_nom": db_cv.candidat_nom,
                    "candidat_titre": db_cv.candidat_titre,
                    "last_modified": db_cv.last_modified.isoformat() if db_cv.last_modified else None
                })

        return cvs

    @staticmethod
    def get_cv(project_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """
        Récupère un CV complet (métadonnées + JSON)

        Args:
            project_id: ID du projet
            filename: Nom du fichier CV

        Returns:
            Données complètes du CV ou None
        """
        with get_session() as session:
            normalized_filename = CVService._normalize_cv_filename(filename)
            db_cv = session.exec(
                select(CVMetaDB).where(
                    CVMetaDB.project_id == project_id,
                    CVMetaDB.filename == normalized_filename
                )
            ).first()

            if not db_cv:
                return None

            # Charger le JSON complet
            try:
                cv_data = FileStorage.load_json(db_cv.json_path)

                # Ajouter les métadonnées
                return {
                    "metadata": {
                        "filename": db_cv.filename,
                        "project_id": db_cv.project_id,
                        "json_path": db_cv.json_path,
                        "file_path": db_cv.file_path,
                        "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                        "candidat_nom": db_cv.candidat_nom,
                        "candidat_titre": db_cv.candidat_titre
                    },
                    "data": cv_data
                }

            except FileNotFoundError:
                # JSON manquant, retourner seulement les métadonnées
                return {
                    "metadata": {
                        "filename": db_cv.filename,
                        "project_id": db_cv.project_id,
                        "json_path": db_cv.json_path,
                        "file_path": db_cv.file_path,
                        "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                        "candidat_nom": db_cv.candidat_nom,
                        "candidat_titre": db_cv.candidat_titre
                    },
                    "data": None
                }

    @staticmethod
    def get_cv_metadata(project_id: str, filename: str) -> Optional[Dict[str, Any]]:
        normalized_filename = CVService._normalize_cv_filename(filename)
        with get_session() as session:
            db_cv = session.exec(
                select(CVMetaDB).where(
                    CVMetaDB.project_id == project_id,
                    CVMetaDB.filename == normalized_filename,
                )
            ).first()
            if not db_cv:
                return None
            return {
                "filename": db_cv.filename,
                "project_id": db_cv.project_id,
                "json_path": db_cv.json_path,
                "file_path": db_cv.file_path,
                "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                "candidat_nom": db_cv.candidat_nom,
                "candidat_titre": db_cv.candidat_titre,
                "last_modified": db_cv.last_modified.isoformat() if db_cv.last_modified else None,
            }

    @staticmethod
    def create_or_update_cv(cv_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée ou met à jour un CV dans cv_meta

        Args:
            cv_data: Métadonnées CV (filename, project_id, json_path, etc.)

        Returns:
            Métadonnées CV créées/mises à jour
        """
        with get_session() as session:
            # Vérifier si existe
            existing = session.exec(
                select(CVMetaDB).where(
                    CVMetaDB.project_id == cv_data["project_id"],
                    CVMetaDB.filename == cv_data["filename"]
                )
            ).first()

            now = datetime.now()

            if existing:
                # Mise à jour
                existing.json_path = cv_data.get("json_path", existing.json_path)
                existing.file_path = cv_data.get("file_path", existing.file_path)
                existing.parsed_at = cv_data.get("parsed_at", existing.parsed_at)
                existing.candidat_nom = cv_data.get("candidat_nom", existing.candidat_nom)
                existing.candidat_titre = cv_data.get("candidat_titre", existing.candidat_titre)
                existing.last_modified = now
                session.add(existing)
                session.commit()

                return {
                    "filename": existing.filename,
                    "project_id": existing.project_id,
                    "json_path": existing.json_path,
                    "file_path": existing.file_path,
                    "parsed_at": existing.parsed_at.isoformat() if existing.parsed_at else None,
                    "candidat_nom": existing.candidat_nom,
                    "candidat_titre": existing.candidat_titre,
                    "last_modified": existing.last_modified.isoformat()
                }
            else:
                # Création
                cv_db = CVMetaDB(
                    filename=cv_data["filename"],
                    project_id=cv_data["project_id"],
                    json_path=cv_data["json_path"],
                    file_path=cv_data.get("file_path"),
                    parsed_at=cv_data.get("parsed_at", now),
                    candidat_nom=cv_data.get("candidat_nom"),
                    candidat_titre=cv_data.get("candidat_titre")
                )
                session.add(cv_db)
                session.commit()

                return {
                    "filename": cv_db.filename,
                    "project_id": cv_db.project_id,
                    "json_path": cv_db.json_path,
                    "file_path": cv_db.file_path,
                    "parsed_at": cv_db.parsed_at.isoformat() if cv_db.parsed_at else None,
                    "candidat_nom": cv_db.candidat_nom,
                    "candidat_titre": cv_db.candidat_titre,
                    "last_modified": cv_db.last_modified.isoformat() if cv_db.last_modified else None
                }

    @staticmethod
    def delete_cv(filename: str) -> bool:
        """
        Supprime un CV de cv_meta ET le fichier JSON

        Args:
            filename: Nom du fichier (peut être .pdf/.docx ou .json)

        Returns:
            True si supprimé, False si introuvable
        """
        # Convertir le nom de fichier en .json si nécessaire
        # (le frontend envoie le nom original, mais la DB stocke le nom JSON)
        filename = CVService._normalize_cv_filename(filename)

        with get_session() as session:
            db_cv = session.exec(
                select(CVMetaDB).where(
                    CVMetaDB.filename == filename
                )
            ).first()

            if not db_cv:
                return False

            # Supprimer le fichier JSON si existe
            if db_cv.json_path:
                try:
                    FileStorage.delete_file(db_cv.json_path)
                except Exception as e:
                    print(f"Erreur suppression fichier {db_cv.json_path}: {e}")

            # Supprimer l'entrée DB
            session.delete(db_cv)
            session.commit()

        return True

    @staticmethod
    def search_cvs(
        query: Optional[str] = None,
        project_id: Optional[str] = None,
        enterprise_id: Optional[str] = None,
        limit: Optional[int] = 50
    ) -> List[Dict[str, Any]]:
        """
        Recherche de CV avec filtres

        Args:
            query: Recherche dans nom/titre (optionnel)
            project_id: Filtrer par projet (optionnel)
            enterprise_id: Filtrer par entreprise (optionnel)
            limit: Limite de résultats (défaut: 50)

        Returns:
            Liste des métadonnées CV correspondantes
        """
        cvs = []

        with get_session() as session:
            sql_query = select(CVMetaDB)

            # Filtrer par projet
            if project_id:
                sql_query = sql_query.where(CVMetaDB.project_id == project_id)

            # Filtrer par entreprise (via projets)
            # SQLModel retourne des scalaires string depuis select(ProjectDB.id), pas des tuples
            if enterprise_id:
                project_ids = session.exec(
                    select(ProjectDB.id).where(ProjectDB.enterprise_id == enterprise_id)
                ).all()
                if project_ids:
                    sql_query = sql_query.where(CVMetaDB.project_id.in_(project_ids))
                else:
                    return cvs

            # Recherche textuelle
            if query:
                search_pattern = f"%{query}%"
                sql_query = sql_query.where(
                    (CVMetaDB.candidat_nom.like(search_pattern)) |
                    (CVMetaDB.candidat_titre.like(search_pattern))
                )

            sql_query = sql_query.order_by(CVMetaDB.parsed_at.desc())

            if limit:
                sql_query = sql_query.limit(limit)

            db_cvs = session.exec(sql_query).all()

            for db_cv in db_cvs:
                cvs.append({
                    "filename": db_cv.filename,
                    "project_id": db_cv.project_id,
                    "json_path": db_cv.json_path,
                    "file_path": db_cv.file_path,
                    "parsed_at": db_cv.parsed_at.isoformat() if db_cv.parsed_at else None,
                    "candidat_nom": db_cv.candidat_nom,
                    "candidat_titre": db_cv.candidat_titre,
                    "last_modified": db_cv.last_modified.isoformat() if db_cv.last_modified else None
                })

        return cvs
