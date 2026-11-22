"""
ProjectPathResolver - Service pour la résolution des chemins spécifiques des projets
"""

from pathlib import Path
from typing import Optional

from brainrh import paths as brainrh_paths


class ProjectPathResolver:
    """Helper pour router l'accès aux fichiers du projet canoniquement"""
    
    @staticmethod
    def get_project_dir(project_id: str, enterprise_id: Optional[str] = None) -> Path:
        """
        Résout le répertoire canonique d'un projet via le gestionnaire de projets.

        Args:
            project_id: ID du projet
            enterprise_id: ID entreprise attendu, si déjà résolu par RBAC
            
        Returns:
            Path absolu du répertoire
            
        Raises:
            ValueError: Si le projet n'existe pas
        """
        from brainrh.services.project_service import ProjectService

        project = ProjectService.get_project(project_id)
        if not project:
            raise ValueError(f"Projet {project_id} introuvable")

        project_enterprise_id = project.get("enterprise_id")
        if enterprise_id and project_enterprise_id and enterprise_id != project_enterprise_id:
            raise ValueError(f"Projet {project_id} introuvable")

        resolved_enterprise_id = project_enterprise_id or enterprise_id
        if resolved_enterprise_id:
            return (
                brainrh_paths.ENTERPRISES_DIR
                / resolved_enterprise_id
                / "projects"
                / project_id
            )

        from project_manager import ProjectManager
        project_dir = ProjectManager().get_project_path(project_id)
        if not project_dir:
            raise ValueError(f"Projet {project_id} introuvable")
        return project_dir

    @staticmethod
    def get_offer_path(project_id: str, enterprise_id: Optional[str] = None) -> Path:
        """Renvoie le chemin canonique de offre_parsed.json"""
        return ProjectPathResolver.get_project_dir(project_id, enterprise_id) / "offre_parsed.json"
