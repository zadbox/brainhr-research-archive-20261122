"""
CVFileService
Service d'acces I/O pour les fichiers JSON de CV.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from brainrh.services.file_storage import FileStorage

class CVFileService:
    """Service abstrait pour le stockage des JSON de CV."""

    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        """Résout le chemin absolu en utilisant la validation sécurisée de FileStorage."""
        return FileStorage.validate_and_resolve_path(path_str)

    @staticmethod
    def load_cv_json(cv_json_path: str) -> Optional[Dict[str, Any]]:
        """
        Charge un fichier JSON de CV.

        Args:
            cv_json_path: Le chemin absolu ou relatif du fichier JSON.

        Returns:
            Le dict JSON ou None si introuvable/invalide.
        """
        try:
            return FileStorage.load_json(cv_json_path)
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def load_cv_json_batch(
        cv_json_paths: Sequence[str],
        *,
        max_workers: int = 8,
    ) -> list[Optional[Dict[str, Any]]]:
        """Charge plusieurs CV en parallèle, dans le même ordre que les chemins reçus."""
        paths = list(cv_json_paths)
        if not paths:
            return []

        unique_paths = list(dict.fromkeys(paths))

        def load_safely(path: str) -> Optional[Dict[str, Any]]:
            try:
                return CVFileService.load_cv_json(path)
            except Exception:
                return None

        worker_count = max(1, min(max_workers, len(unique_paths)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            loaded_values = list(executor.map(load_safely, unique_paths))

        loaded_by_path = dict(zip(unique_paths, loaded_values))
        return [loaded_by_path.get(path) for path in paths]

    @staticmethod
    def save_cv_json(cv_json_path: str, cv_data: Dict[str, Any]) -> None:
        """
        Sauvegarde un dictionnaire dans un fichier JSON de CV.

        Args:
            cv_json_path: Le chemin cible pour le JSON.
            cv_data: Les données complètes du CV.
        """
        FileStorage.save_json_atomic(cv_json_path, cv_data)

    @staticmethod
    def delete_cv_json(cv_json_path: str) -> bool:
        """
        Supprime le fichier JSON correspondant au CV.

        Args:
            cv_json_path: Le chemin du fichier JSON.

        Returns:
            True si supprimé, False si introuvable.
        """
        try:
            FileStorage.delete_file(cv_json_path)
            return True
        except FileNotFoundError:
            return False
