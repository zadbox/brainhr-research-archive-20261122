#!/usr/bin/env python3
"""
Unified Project Manager - Gestionnaire unifié pour la structure enterprises/{id}/projects/
Remplace project_manager.py avec support complet de la hiérarchie entreprises
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import uuid


class UnifiedProjectManager:
    """Gestionnaire unifié de projets dans la structure enterprises"""

    def __init__(self, enterprises_folder: str = "enterprises"):
        self.enterprises_folder = Path(enterprises_folder)

        # Créer le dossier si nécessaire
        self.enterprises_folder.mkdir(exist_ok=True)

    def _write_atomic(self, file_path: Path, data: Dict):
        """Écrit un fichier JSON de manière atomique"""
        tmp_file = file_path.with_suffix('.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(file_path)

    def _get_projects_folder(self, enterprise_id: str) -> Path:
        """Retourne le chemin du dossier projects pour une entreprise"""
        return self.enterprises_folder / enterprise_id / "projects"

    def _get_project_index(self, enterprise_id: str) -> Dict:
        """Lit l'index des projets d'une entreprise"""
        projects_folder = self._get_projects_folder(enterprise_id)
        index_file = projects_folder / "_index.json"

        if not index_file.exists():
            return {"projects": []}

        with open(index_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_project_index(self, enterprise_id: str, data: Dict):
        """Écrit l'index des projets d'une entreprise"""
        projects_folder = self._get_projects_folder(enterprise_id)
        projects_folder.mkdir(parents=True, exist_ok=True)
        index_file = projects_folder / "_index.json"
        self._write_atomic(index_file, data)

    def list_projects(self, enterprise_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
        """
        Liste tous les projets (optionnellement filtrés)

        Args:
            enterprise_id: Filtrer par entreprise (None = toutes les entreprises)
            status: Filtrer par statut ('actif', 'archive', None=tous)

        Returns:
            Liste de projets [{id, nom, enterprise_id, created_at, status, ...}]
        """
        all_projects = []

        # Déterminer les entreprises à scanner
        if enterprise_id:
            enterprises_to_scan = [enterprise_id]
        else:
            # Scanner toutes les entreprises
            enterprises_to_scan = [
                d.name for d in self.enterprises_folder.iterdir()
                if d.is_dir() and not d.name.startswith('_')
            ]

        # Collecter les projets de toutes les entreprises
        for ent_id in enterprises_to_scan:
            try:
                index = self._get_project_index(ent_id)
                projects = index.get("projects", [])

                # Ajouter enterprise_id à chaque projet si pas déjà présent
                for p in projects:
                    if "enterprise_id" not in p:
                        p["enterprise_id"] = ent_id

                all_projects.extend(projects)
            except Exception:
                continue

        # Filtrer par status si demandé
        if status:
            all_projects = [p for p in all_projects if p.get("status") == status]

        # Trier par dernière modification (plus récent en premier)
        all_projects.sort(
            key=lambda p: p.get("last_modified", p.get("created_at", "")),
            reverse=True
        )

        return all_projects

    def get_project(self, project_id: str, enterprise_id: Optional[str] = None) -> Optional[Dict]:
        """
        Récupère les détails d'un projet

        Args:
            project_id: ID du projet
            enterprise_id: ID de l'entreprise (optionnel, cherche dans toutes si None)

        Returns:
            Dictionnaire avec toutes les métadonnées, ou None si non trouvé
        """
        # Si enterprise_id fourni, chercher directement
        if enterprise_id:
            project_dir = self._get_projects_folder(enterprise_id) / project_id
            projet_file = project_dir / "projet.json"

            if projet_file.exists():
                with open(projet_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return None

        # Sinon, chercher dans toutes les entreprises
        for enterprise_dir in self.enterprises_folder.iterdir():
            if not enterprise_dir.is_dir() or enterprise_dir.name.startswith('_'):
                continue

            project_dir = enterprise_dir / "projects" / project_id
            projet_file = project_dir / "projet.json"

            if projet_file.exists():
                with open(projet_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # S'assurer que enterprise_id est présent
                    if "enterprise_id" not in data:
                        data["enterprise_id"] = enterprise_dir.name
                    return data

        return None

    def create_project(self, nom: str, enterprise_id: str, description: str = "",
                      service_demandeur: Optional[str] = None, responsable_offre: Optional[str] = None,
                      contact_responsable: Optional[str] = None, notes: Optional[str] = None) -> Dict:
        """
        Crée un nouveau projet

        Args:
            nom: Nom du projet
            enterprise_id: ID de l'entreprise parente
            description: Description optionnelle
            service_demandeur: Service demandeur
            responsable_offre: Responsable de l'offre
            contact_responsable: Contact du responsable
            notes: Notes

        Returns:
            Dictionnaire du projet créé
        """
        # Vérifier que l'entreprise existe
        enterprise_dir = self.enterprises_folder / enterprise_id
        if not enterprise_dir.exists():
            raise ValueError(f"Entreprise {enterprise_id} introuvable")

        # Générer un ID unique basé sur le nom
        project_id = self._generate_project_id(nom)

        # Vérifier que l'ID n'existe pas déjà dans cette entreprise
        if self.get_project(project_id, enterprise_id):
            # Ajouter un suffix unique
            project_id = f"{project_id}-{uuid.uuid4().hex[:6]}"

        # Créer la structure du projet
        projects_folder = self._get_projects_folder(enterprise_id)
        project_dir = projects_folder / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "historique").mkdir(exist_ok=True)
        (project_dir / "matchings").mkdir(exist_ok=True)
        (project_dir / "cvs").mkdir(exist_ok=True)

        # Métadonnées du projet
        now = datetime.now().isoformat()
        projet_data = {
            "id": project_id,
            "nom": nom,
            "description": description,
            "enterprise_id": enterprise_id,
            "service_demandeur": service_demandeur or "",
            "responsable_offre": responsable_offre or "",
            "contact_responsable": contact_responsable or "",
            "notes": notes or "",
            "created_at": now,
            "last_modified": now,
            "status": "actif",
            "offre_saved": False,
            "matchings_count": 0
        }

        # Sauvegarder le fichier projet
        projet_file = project_dir / "projet.json"
        self._write_atomic(projet_file, projet_data)

        # Ajouter à l'index de l'entreprise
        self._add_to_index(enterprise_id, projet_data)

        return projet_data

    def update_project(self, project_id: str, updates: Dict, enterprise_id: Optional[str] = None):
        """
        Met à jour un projet

        Args:
            project_id: ID du projet
            updates: Dictionnaire des champs à mettre à jour
            enterprise_id: ID de l'entreprise (optionnel)
        """
        # Récupérer le projet
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            raise ValueError(f"Projet {project_id} introuvable")

        # Déterminer l'enterprise_id
        ent_id = projet.get("enterprise_id") or enterprise_id
        if not ent_id:
            raise ValueError(f"Impossible de déterminer l'enterprise_id pour le projet {project_id}")

        # Mettre à jour les champs
        projet.update(updates)
        projet["last_modified"] = datetime.now().isoformat()

        # Sauvegarder
        project_dir = self._get_projects_folder(ent_id) / project_id
        projet_file = project_dir / "projet.json"
        self._write_atomic(projet_file, projet)

        # Mettre à jour l'index
        self._update_index_entry(ent_id, projet)

    def delete_project(self, project_id: str, enterprise_id: Optional[str] = None):
        """
        Archive un projet (soft delete)

        Args:
            project_id: ID du projet
            enterprise_id: ID de l'entreprise (optionnel)
        """
        self.update_project(project_id, {"status": "archive"}, enterprise_id)

    def save_offer(self, project_id: str, offre_data: Dict, enterprise_id: Optional[str] = None):
        """
        Sauvegarde l'offre parsée dans le projet

        Args:
            project_id: ID du projet
            offre_data: Données de l'offre parsée
            enterprise_id: ID de l'entreprise (optionnel)
        """
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            raise ValueError(f"Projet {project_id} introuvable")

        ent_id = projet.get("enterprise_id") or enterprise_id
        project_dir = self._get_projects_folder(ent_id) / project_id
        offre_file = project_dir / "offre_parsed.json"

        self._write_atomic(offre_file, offre_data)

        # Mettre à jour le projet
        self.update_project(project_id, {"offre_saved": True}, ent_id)

    def load_offer(self, project_id: str, enterprise_id: Optional[str] = None) -> Optional[Dict]:
        """
        Charge l'offre parsée du projet

        Args:
            project_id: ID du projet
            enterprise_id: ID de l'entreprise (optionnel)

        Returns:
            Données de l'offre, ou None si pas trouvée
        """
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            return None

        ent_id = projet.get("enterprise_id") or enterprise_id
        project_dir = self._get_projects_folder(ent_id) / project_id
        offre_file = project_dir / "offre_parsed.json"

        if not offre_file.exists():
            return None

        with open(offre_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_matching_result(self, project_id: str, results: Dict,
                            timestamp: Optional[str] = None,
                            enterprise_id: Optional[str] = None) -> str:
        """
        Sauvegarde les résultats d'un matching

        Args:
            project_id: ID du projet
            results: Résultats du matching (scorecard)
            timestamp: Timestamp optionnel (auto si None)
            enterprise_id: ID de l'entreprise (optionnel)

        Returns:
            Timestamp du matching sauvegardé
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            raise ValueError(f"Projet {project_id} introuvable")

        ent_id = projet.get("enterprise_id") or enterprise_id
        project_dir = self._get_projects_folder(ent_id) / project_id
        matchings_dir = project_dir / "matchings"
        matching_folder = matchings_dir / timestamp
        matching_folder.mkdir(parents=True, exist_ok=True)

        # Sauvegarder JSON
        result_file = matching_folder / "results.json"
        self._write_atomic(result_file, results)

        # Incrémenter le compteur
        matchings_count = projet.get("matchings_count", 0) + 1
        self.update_project(project_id, {
            "matchings_count": matchings_count,
            "last_matching": timestamp
        }, ent_id)

        return timestamp

    def list_matchings(self, project_id: str, enterprise_id: Optional[str] = None) -> List[Dict]:
        """
        Liste l'historique des matchings d'un projet

        Args:
            project_id: ID du projet
            enterprise_id: ID de l'entreprise (optionnel)

        Returns:
            Liste des matchings [{timestamp, candidats_count, ...}]
        """
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            return []

        ent_id = projet.get("enterprise_id") or enterprise_id
        project_dir = self._get_projects_folder(ent_id) / project_id
        matchings = []

        # Lire les nouveaux matchings (dossier matchings/)
        matchings_dir = project_dir / "matchings"
        if matchings_dir.exists():
            for matching_folder in sorted(matchings_dir.iterdir(), reverse=True):
                if not matching_folder.is_dir():
                    continue

                timestamp = matching_folder.name
                results_file = matching_folder / "results.json"

                if results_file.exists():
                    try:
                        with open(results_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        # Récupérer le nombre de candidats depuis metadata ou results
                        candidats_count = 0
                        if "metadata" in data:
                            candidats_count = data["metadata"].get("top_reranked", 0)
                        elif "results" in data:
                            candidats_count = len(data.get("results", []))

                        matchings.append({
                            "timestamp": timestamp,
                            "candidats_count": candidats_count,
                            "file_path": str(results_file)
                        })
                    except Exception as e:
                        print(f"Erreur lecture {results_file}: {e}")

        # Lire les anciens matchings (dossier historique/)
        historique_dir = project_dir / "historique"
        if historique_dir.exists():
            for file in sorted(historique_dir.glob("*.json"), reverse=True):
                timestamp = file.stem

                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # Compter les candidats
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
                except Exception as e:
                    print(f"Erreur lecture {file}: {e}")

        # Trier par timestamp (plus récent en premier)
        matchings.sort(key=lambda m: m["timestamp"], reverse=True)

        return matchings

    def load_matching(self, project_id: str, timestamp: str,
                     enterprise_id: Optional[str] = None) -> Optional[Dict]:
        """
        Charge un matching spécifique

        Args:
            project_id: ID du projet
            timestamp: Timestamp du matching
            enterprise_id: ID de l'entreprise (optionnel)

        Returns:
            Résultats du matching, ou None
        """
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            return None

        ent_id = projet.get("enterprise_id") or enterprise_id
        project_dir = self._get_projects_folder(ent_id) / project_id

        # Essayer nouveau format d'abord (matchings/)
        new_result_file = project_dir / "matchings" / timestamp / "results.json"
        if new_result_file.exists():
            with open(new_result_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        # Essayer ancien format (historique/)
        old_result_file = project_dir / "historique" / f"{timestamp}.json"
        if old_result_file.exists():
            with open(old_result_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        return None

    def get_project_path(self, project_id: str, enterprise_id: Optional[str] = None) -> Optional[Path]:
        """
        Retourne le chemin du dossier projet

        Args:
            project_id: ID du projet
            enterprise_id: ID de l'entreprise (optionnel)

        Returns:
            Path du dossier projet, ou None
        """
        projet = self.get_project(project_id, enterprise_id)
        if not projet:
            return None

        ent_id = projet.get("enterprise_id") or enterprise_id
        if not ent_id:
            return None

        return self._get_projects_folder(ent_id) / project_id

    # Méthodes privées

    def _generate_project_id(self, nom: str) -> str:
        """Génère un ID projet à partir du nom"""
        import re
        slug = nom.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug.strip('-')[:50]
        return slug or "projet"

    def _add_to_index(self, enterprise_id: str, projet_data: Dict):
        """Ajoute un projet à l'index d'une entreprise"""
        index = self._get_project_index(enterprise_id)

        # Créer une entrée légère pour l'index
        index_entry = {
            "id": projet_data["id"],
            "nom": projet_data["nom"],
            "created_at": projet_data["created_at"],
            "last_modified": projet_data["last_modified"],
            "status": projet_data["status"],
            "enterprise_id": projet_data.get("enterprise_id")
        }

        index["projects"].append(index_entry)
        self._write_project_index(enterprise_id, index)

    def _update_index_entry(self, enterprise_id: str, projet_data: Dict):
        """Met à jour une entrée dans l'index d'une entreprise"""
        index = self._get_project_index(enterprise_id)

        # Trouver et mettre à jour l'entrée
        for i, p in enumerate(index["projects"]):
            if p["id"] == projet_data["id"]:
                index["projects"][i] = {
                    "id": projet_data["id"],
                    "nom": projet_data["nom"],
                    "created_at": projet_data["created_at"],
                    "last_modified": projet_data["last_modified"],
                    "status": projet_data["status"],
                    "enterprise_id": projet_data.get("enterprise_id")
                }
                break

        self._write_project_index(enterprise_id, index)
