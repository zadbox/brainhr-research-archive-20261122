#!/usr/bin/env python3
"""
Gestionnaire d'entreprises clientes
Gère la création, lecture, mise à jour des entreprises
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import re


class EnterpriseManager:
    """Gestionnaire d'entreprises clientes"""

    def __init__(self, enterprises_folder: str = "enterprises"):
        self.enterprises_folder = Path(enterprises_folder)
        self.index_file = self.enterprises_folder / "_index.json"

        # Créer le dossier si nécessaire
        self.enterprises_folder.mkdir(exist_ok=True)

        # Créer l'index si nécessaire
        if not self.index_file.exists():
            self._write_index({"enterprises": []})

    def _read_index(self) -> Dict:
        """Lit l'index des entreprises"""
        if not self.index_file.exists():
            return {"enterprises": []}

        with open(self.index_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_index(self, data: Dict):
        """Écrit l'index des entreprises (atomic)"""
        tmp_file = self.index_file.with_suffix('.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(self.index_file)

    def _generate_enterprise_id(self, nom: str) -> str:
        """Génère un ID unique à partir du nom"""
        # Nettoyer le nom: minuscules, remplacer espaces par tirets
        id_base = re.sub(r'[^\w\s-]', '', nom.lower())
        id_base = re.sub(r'[-\s]+', '-', id_base).strip('-')
        return id_base

    def list_enterprises(self) -> List[Dict]:
        """
        Liste toutes les entreprises

        Returns:
            Liste d'entreprises [{id, nom, secteur, logo, created_at, ...}]
        """
        index = self._read_index()
        enterprises = index.get("enterprises", [])

        # Recalculer le nombre de projets pour chaque entreprise (dynamique)
        for enterprise in enterprises:
            projects_folder = self.enterprises_folder / enterprise["id"] / "projects"
            projects_index = projects_folder / "_index.json"

            if projects_index.exists():
                try:
                    with open(projects_index, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        enterprise["projects_count"] = len(data.get("projects", []))
                except Exception:
                    enterprise["projects_count"] = 0
            else:
                enterprise["projects_count"] = 0

        # Trier par dernière modification (plus récent en premier)
        enterprises.sort(key=lambda e: e.get("last_modified", e.get("created_at", "")), reverse=True)

        return enterprises

    def get_enterprise(self, enterprise_id: str) -> Optional[Dict]:
        """
        Récupère les détails d'une entreprise

        Args:
            enterprise_id: ID de l'entreprise

        Returns:
            Dictionnaire avec toutes les métadonnées, ou None si non trouvé
        """
        enterprise_dir = self.enterprises_folder / enterprise_id
        enterprise_file = enterprise_dir / "enterprise.json"

        if not enterprise_file.exists():
            return None

        with open(enterprise_file, 'r', encoding='utf-8') as f:
            enterprise = json.load(f)

        # Recalculer le nombre de projets (dynamique)
        projects_folder = enterprise_dir / "projects"
        projects_index = projects_folder / "_index.json"

        if projects_index.exists():
            try:
                with open(projects_index, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    enterprise["projects_count"] = len(data.get("projects", []))
            except Exception:
                enterprise["projects_count"] = 0
        else:
            enterprise["projects_count"] = 0

        return enterprise

    def create_enterprise(self, nom: str, site_web: str = "", secteur: str = "", notes: str = "", contacts: List[Dict] = None, logo_path: str = "") -> Dict:
        """
        Crée une nouvelle entreprise

        Args:
            nom: Nom de l'entreprise
            site_web: Site web
            secteur: Secteur d'activité
            notes: Notes
            contacts: Liste des contacts
            logo_path: Chemin vers le logo (optionnel)

        Returns:
            Dictionnaire de l'entreprise créée
        """
        if contacts is None:
            contacts = []

        # Générer un ID unique basé sur le nom
        enterprise_id = self._generate_enterprise_id(nom)

        # Vérifier que l'ID n'existe pas déjà
        if self.get_enterprise(enterprise_id):
            # Ajouter un suffix unique
            import uuid
            enterprise_id = f"{enterprise_id}-{uuid.uuid4().hex[:6]}"

        # Créer le dossier de l'entreprise
        enterprise_dir = self.enterprises_folder / enterprise_id
        enterprise_dir.mkdir(parents=True, exist_ok=True)

        # Créer le dossier projects pour cette entreprise
        projects_dir = enterprise_dir / "projects"
        projects_dir.mkdir(exist_ok=True)

        # Créer l'index des projets pour cette entreprise
        projects_index_file = projects_dir / "_index.json"
        if not projects_index_file.exists():
            with open(projects_index_file, 'w', encoding='utf-8') as f:
                json.dump({"projects": []}, f, ensure_ascii=False, indent=2)

        # Créer l'objet entreprise
        now = datetime.now().isoformat()
        enterprise = {
            "id": enterprise_id,
            "nom": nom,
            "site_web": site_web,
            "secteur": secteur,
            "notes": notes,
            "contacts": contacts,
            "logo": logo_path,
            "created_at": now,
            "last_modified": now,
            "projects_count": 0
        }

        # Sauvegarder l'entreprise
        enterprise_file = enterprise_dir / "enterprise.json"
        with open(enterprise_file, 'w', encoding='utf-8') as f:
            json.dump(enterprise, f, ensure_ascii=False, indent=4)

        # Ajouter à l'index
        index = self._read_index()
        index["enterprises"].append({
            "id": enterprise_id,
            "nom": nom,
            "site_web": site_web,
            "secteur": secteur,
            "notes": notes,
            "contacts": contacts,
            "logo": logo_path,
            "created_at": now,
            "last_modified": now,
            "projects_count": 0
        })
        self._write_index(index)

        return enterprise

    def update_enterprise(self, enterprise_id: str, updates: Dict) -> bool:
        """
        Met à jour une entreprise

        Args:
            enterprise_id: ID de l'entreprise
            updates: Dictionnaire des champs à mettre à jour

        Returns:
            True si succès, False sinon
        """
        enterprise = self.get_enterprise(enterprise_id)
        if not enterprise:
            return False

        # Mettre à jour les champs
        enterprise.update(updates)
        enterprise["last_modified"] = datetime.now().isoformat()

        # Sauvegarder
        enterprise_dir = self.enterprises_folder / enterprise_id
        enterprise_file = enterprise_dir / "enterprise.json"
        with open(enterprise_file, 'w', encoding='utf-8') as f:
            json.dump(enterprise, f, ensure_ascii=False, indent=4)

        # Mettre à jour l'index
        index = self._read_index()
        for i, e in enumerate(index["enterprises"]):
            if e["id"] == enterprise_id:
                index["enterprises"][i].update(updates)
                index["enterprises"][i]["last_modified"] = enterprise["last_modified"]
                break
        self._write_index(index)

        return True

    def delete_enterprise(self, enterprise_id: str) -> bool:
        """
        Supprime une entreprise et tous ses projets

        Args:
            enterprise_id: ID de l'entreprise

        Returns:
            True si succès, False sinon
        """
        enterprise_dir = self.enterprises_folder / enterprise_id
        if not enterprise_dir.exists():
            return False

        # Supprimer le dossier complet
        import shutil
        shutil.rmtree(enterprise_dir)

        # Retirer de l'index
        index = self._read_index()
        index["enterprises"] = [e for e in index["enterprises"] if e["id"] != enterprise_id]
        self._write_index(index)

        return True

    def get_projects_folder(self, enterprise_id: str) -> Optional[Path]:
        """
        Retourne le chemin du dossier projects pour une entreprise

        Args:
            enterprise_id: ID de l'entreprise

        Returns:
            Path du dossier projects, ou None si l'entreprise n'existe pas
        """
        enterprise_dir = self.enterprises_folder / enterprise_id
        if not enterprise_dir.exists():
            return None

        projects_dir = enterprise_dir / "projects"
        projects_dir.mkdir(exist_ok=True)
        return projects_dir

    def update_projects_count(self, enterprise_id: str):
        """
        Met à jour le compteur de projets pour une entreprise

        Args:
            enterprise_id: ID de l'entreprise
        """
        projects_folder = self.get_projects_folder(enterprise_id)
        if not projects_folder:
            return

        # Compter les projets
        projects_index = projects_folder / "_index.json"
        if projects_index.exists():
            with open(projects_index, 'r', encoding='utf-8') as f:
                data = json.load(f)
                count = len(data.get("projects", []))

            # Mettre à jour l'entreprise
            self.update_enterprise(enterprise_id, {"projects_count": count})
