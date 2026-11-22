"""
ProjectFileService - Service dédié à la persistance des fichiers du projet (JSON offres, etc.)
"""

from typing import Dict, Any, Optional

from brainrh.services.file_storage import FileStorage
from brainrh.services.project_path_resolver import ProjectPathResolver
from brainrh.services.project_service import ProjectService


class ProjectFileService:
    """Service pour la manipulation des fichiers générés dans les projets"""

    @staticmethod
    def load_offer(project_id: str, enterprise_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Charge l'offre depuis le fichier JSON"""
        try:
            offer_path = ProjectPathResolver.get_offer_path(project_id, enterprise_id)
        except ValueError:
            return None

        try:
            return FileStorage.load_json(str(offer_path))
        except FileNotFoundError:
            return None

    @staticmethod
    def save_offer(
        project_id: str,
        offre_data: Dict[str, Any],
        enterprise_id: Optional[str] = None,
    ) -> None:
        """Sauvegarde l'offre et met à jour le statut du projet"""
        offer_path = ProjectPathResolver.get_offer_path(project_id, enterprise_id)
        FileStorage.save_json_atomic(str(offer_path), offre_data)

        # Mettre à jour l'indicateur d'offre
        ProjectService.update_project(project_id, {"offre_saved": True})

    @staticmethod
    def delete_offer(project_id: str, enterprise_id: Optional[str] = None) -> None:
        """Supprime le fichier d'offre s'il existe et met à jour le projet"""
        try:
            offer_path = ProjectPathResolver.get_offer_path(project_id, enterprise_id)
            if FileStorage.file_exists(str(offer_path)):
                FileStorage.delete_file(str(offer_path))
            ProjectService.update_project(project_id, {"offre_saved": False})
        except ValueError:
            pass
