#!/usr/bin/env python3
"""
Gestionnaire de projets de recrutement
Gère la création, lecture, mise à jour des projets multi-recrutement
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import uuid


class ProjectManager:
    """Gestionnaire de projets de recrutement"""

    def __init__(self, projects_folder: str = "projects"):
        self.projects_folder = Path(projects_folder)
        self.index_file = self.projects_folder / "_index.json"

        # Créer le dossier si nécessaire
        self.projects_folder.mkdir(exist_ok=True)

        # Créer l'index si nécessaire
        if not self.index_file.exists():
            self._write_index({"projects": []})

    def _read_index(self) -> Dict:
        """Lit l'index des projets"""
        if not self.index_file.exists():
            return {"projects": []}

        with open(self.index_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_index(self, data: Dict):
        """Écrit l'index des projets (atomic)"""
        tmp_file = self.index_file.with_suffix('.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(self.index_file)

    def list_projects(self, status: Optional[str] = None) -> List[Dict]:
        """
        Liste tous les projets

        Args:
            status: Filtrer par statut ('actif', 'archive', None=tous)

        Returns:
            Liste de projets [{id, nom, created_at, status, ...}]
        """
        index = self._read_index()
        projects = index.get("projects", [])

        if status:
            projects = [p for p in projects if p.get("status") == status]

        # Trier par dernière modification (plus récent en premier)
        projects.sort(key=lambda p: p.get("last_modified", p.get("created_at", "")), reverse=True)

        return projects

    def get_project(self, project_id: str) -> Optional[Dict]:
        """
        Récupère les détails d'un projet

        Args:
            project_id: ID du projet

        Returns:
            Dictionnaire avec toutes les métadonnées, ou None si non trouvé
        """
        project_dir = self.projects_folder / project_id
        projet_file = project_dir / "projet.json"

        if not projet_file.exists():
            return None

        with open(projet_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def create_project(self, nom: str, description: str = "") -> Dict:
        """
        Crée un nouveau projet

        Args:
            nom: Nom du projet
            description: Description optionnelle

        Returns:
            Dictionnaire du projet créé
        """
        # Générer un ID unique basé sur le nom
        project_id = self._generate_project_id(nom)

        # Vérifier que l'ID n'existe pas déjà
        if self.get_project(project_id):
            # Ajouter un suffix unique
            project_id = f"{project_id}-{uuid.uuid4().hex[:6]}"

        # Créer la structure du projet
        project_dir = self.projects_folder / project_id
        project_dir.mkdir(exist_ok=True)
        (project_dir / "historique").mkdir(exist_ok=True)

        # Métadonnées du projet
        now = datetime.now().isoformat()
        projet_data = {
            "id": project_id,
            "nom": nom,
            "description": description,
            "created_at": now,
            "last_modified": now,
            "status": "actif",
            "offre_saved": False,
            "matchings_count": 0
        }

        # Sauvegarder le fichier projet
        self._write_project(project_id, projet_data)

        # Ajouter à l'index
        self._add_to_index(projet_data)

        return projet_data

    def update_project(self, project_id: str, updates: Dict):
        """
        Met à jour un projet

        Args:
            project_id: ID du projet
            updates: Dictionnaire des champs à mettre à jour
        """
        projet = self.get_project(project_id)
        if not projet:
            raise ValueError(f"Projet {project_id} introuvable")

        # Mettre à jour les champs
        projet.update(updates)
        projet["last_modified"] = datetime.now().isoformat()

        # Sauvegarder
        self._write_project(project_id, projet)

        # Mettre à jour l'index
        self._update_index_entry(projet)

    def delete_project(self, project_id: str):
        """
        Archive un projet (ne supprime pas physiquement)

        Args:
            project_id: ID du projet
        """
        self.update_project(project_id, {"status": "archive"})

    def save_offer(self, project_id: str, offre_data: Dict):
        """
        Sauvegarde l'offre parsée dans le projet

        Args:
            project_id: ID du projet
            offre_data: Données de l'offre parsée
        """
        project_dir = self.projects_folder / project_id
        offre_file = project_dir / "offre_parsed.json"

        with open(offre_file, 'w', encoding='utf-8') as f:
            json.dump(offre_data, f, ensure_ascii=False, indent=2)

        # Mettre à jour le projet
        self.update_project(project_id, {"offre_saved": True})

    def load_offer(self, project_id: str) -> Optional[Dict]:
        """
        Charge l'offre parsée du projet

        Args:
            project_id: ID du projet

        Returns:
            Données de l'offre, ou None si pas trouvée
        """
        project_dir = self.projects_folder / project_id
        offre_file = project_dir / "offre_parsed.json"

        if not offre_file.exists():
            return None

        with open(offre_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_matching_result(self, project_id: str, results: Dict, timestamp: Optional[str] = None) -> str:
        """
        Sauvegarde les résultats d'un matching

        Args:
            project_id: ID du projet
            results: Résultats du matching (scorecard)
            timestamp: Timestamp optionnel (auto si None)

        Returns:
            Timestamp du matching sauvegardé
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        project_dir = self.projects_folder / project_id
        historique_dir = project_dir / "historique"

        # Sauvegarder JSON
        result_file = historique_dir / f"{timestamp}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        # Incrémenter le compteur
        projet = self.get_project(project_id)
        matchings_count = projet.get("matchings_count", 0) + 1
        self.update_project(project_id, {
            "matchings_count": matchings_count,
            "last_matching": timestamp
        })

        return timestamp

    def list_matchings(self, project_id: str) -> List[Dict]:
        """
        Liste l'historique des matchings d'un projet

        Args:
            project_id: ID du projet

        Returns:
            Liste des matchings [{timestamp, candidats_count, ...}]
        """
        project_dir = self.projects_folder / project_id
        historique_dir = project_dir / "historique"

        if not historique_dir.exists():
            return []

        matchings = []
        for file in sorted(historique_dir.glob("*.json"), reverse=True):
            timestamp = file.stem

            # Lire le fichier pour obtenir les métadonnées
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Compter les candidats: priorité reranked_cvs > scored_cvs
            candidats_count = 0
            if "reranked_cvs" in data:
                reranked = data["reranked_cvs"]
                if isinstance(reranked, list):
                    candidats_count = len(reranked)
                elif isinstance(reranked, dict):
                    candidats_count = len(reranked.get("ranked_cvs", []))
            elif "scored_cvs" in data:
                candidats_count = len(data.get("scored_cvs", []))

            matchings.append({
                "timestamp": timestamp,
                "candidats_count": candidats_count,
                "file_path": str(file)
            })

        return matchings

    def load_matching(self, project_id: str, timestamp: str) -> Optional[Dict]:
        """
        Charge un matching spécifique

        Args:
            project_id: ID du projet
            timestamp: Timestamp du matching

        Returns:
            Résultats du matching, ou None
        """
        project_dir = self.projects_folder / project_id
        result_file = project_dir / "historique" / f"{timestamp}.json"

        if not result_file.exists():
            return None

        with open(result_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_project_path(self, project_id: str) -> Path:
        """Retourne le chemin du dossier projet"""
        return self.projects_folder / project_id

    # Méthodes privées

    def _generate_project_id(self, nom: str) -> str:
        """Génère un ID projet à partir du nom"""
        import re
        # Normaliser: minuscules, espaces -> tirets, garder alphanum
        slug = nom.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug.strip('-')[:50]  # Max 50 chars
        return slug or "projet"

    def _write_project(self, project_id: str, data: Dict):
        """Écrit le fichier projet.json (atomic)"""
        project_dir = self.projects_folder / project_id
        projet_file = project_dir / "projet.json"
        tmp_file = projet_file.with_suffix('.tmp')

        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        tmp_file.replace(projet_file)

    def _add_to_index(self, projet_data: Dict):
        """Ajoute un projet à l'index"""
        index = self._read_index()

        # Créer une entrée légère pour l'index
        index_entry = {
            "id": projet_data["id"],
            "nom": projet_data["nom"],
            "created_at": projet_data["created_at"],
            "last_modified": projet_data["last_modified"],
            "status": projet_data["status"]
        }

        index["projects"].append(index_entry)
        self._write_index(index)

    def _update_index_entry(self, projet_data: Dict):
        """Met à jour une entrée dans l'index"""
        index = self._read_index()

        # Trouver et mettre à jour l'entrée
        for i, p in enumerate(index["projects"]):
            if p["id"] == projet_data["id"]:
                index["projects"][i] = {
                    "id": projet_data["id"],
                    "nom": projet_data["nom"],
                    "created_at": projet_data["created_at"],
                    "last_modified": projet_data["last_modified"],
                    "status": projet_data["status"]
                }
                break

        self._write_index(index)
