"""
MatchingFileService
Centralise les lectures/ecritures JSON des resultats de matching.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from brainrh.paths import ENTERPRISES_DIR
from brainrh.services.file_storage import FileStorage


class MatchingFileService:
    """Service d'acces aux fichiers de matching projet."""

    @staticmethod
    def _get_project_dir(
        project_id: str,
        enterprise_id: Optional[str] = None,
        enterprises_folder: Optional[Path] = None,
    ) -> Optional[Path]:
        """Retourne le dossier projet via le resolver historique compatible."""
        if enterprise_id:
            enterprise_root = Path(enterprises_folder) if enterprises_folder else ENTERPRISES_DIR
            enterprise_project_dir = enterprise_root / enterprise_id / "projects" / project_id
            if enterprise_project_dir.exists():
                return enterprise_project_dir
            if enterprises_folder:
                if FileStorage.is_local_storage():
                    return None
                return enterprise_project_dir
            return enterprise_project_dir

        try:
            from project_manager import ProjectManager

            project_dir = ProjectManager(projects_folder="projects").get_project_path(project_id)
        except Exception:
            return None

        if project_dir is None:
            return None
        return project_dir

    @staticmethod
    def _write_atomic(file_path: Path, data: Dict[str, Any]) -> None:
        FileStorage.save_json_atomic(str(file_path), data)

    @staticmethod
    def save_matching_json(
        project_id: str,
        timestamp: str,
        results: Dict[str, Any],
        enterprise_id: Optional[str] = None,
        enterprises_folder: Optional[Path] = None,
    ) -> bool:
        """Sauvegarde un matching au format actuel matchings/<timestamp>/results.json."""
        project_dir = MatchingFileService._get_project_dir(project_id, enterprise_id, enterprises_folder)
        if not project_dir:
            return False

        result_file = project_dir / "matchings" / timestamp / "results.json"
        try:
            MatchingFileService._write_atomic(result_file, results)
            return True
        except Exception:
            return False

    @staticmethod
    def load_matching_json(
        project_id: str,
        timestamp: str,
        enterprise_id: Optional[str] = None,
        enterprises_folder: Optional[Path] = None,
    ) -> Optional[Dict[str, Any]]:
        """Charge le format actuel, puis le format legacy historique/<timestamp>.json."""
        project_dir = MatchingFileService._get_project_dir(project_id, enterprise_id, enterprises_folder)
        if not project_dir:
            return None

        for result_file in (
            project_dir / "matchings" / timestamp / "results.json",
            project_dir / "historique" / f"{timestamp}.json",
        ):
            if not FileStorage.file_exists(str(result_file)):
                continue
            try:
                return MatchingFileService._normalize_payload(FileStorage.load_json(str(result_file)), timestamp)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue

        return None

    @staticmethod
    def list_matchings_metadata(
        project_id: str,
        enterprise_id: Optional[str] = None,
        enterprises_folder: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Liste les matchings actuels et legacy, du plus recent au plus ancien."""
        project_dir = MatchingFileService._get_project_dir(project_id, enterprise_id, enterprises_folder)
        if not project_dir:
            return []

        matchings: List[Dict[str, Any]] = []
        matchings.extend(MatchingFileService._list_current_matchings(project_dir))
        matchings.extend(MatchingFileService._list_legacy_matchings(project_dir))
        matchings.sort(key=lambda item: item["timestamp"], reverse=True)
        return matchings

    @staticmethod
    def _normalize_payload(data: Dict[str, Any], timestamp: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(data, dict) or isinstance(data.get("results"), list):
            return data

        legacy_results = MatchingFileService._extract_legacy_results(data)
        if legacy_results is None:
            return data

        normalized = dict(data)
        normalized["results"] = [
            MatchingFileService._normalize_result_item(item)
            for item in legacy_results
            if isinstance(item, dict)
        ]

        metadata = dict(data.get("metadata") or {})
        metadata.setdefault("total_cvs", data.get("total_cvs", len(normalized["results"])))
        metadata.setdefault("filtered_must_have", data.get("filtered_count", len(normalized["results"])))
        metadata.setdefault("top_reranked", data.get("reranked_count", len(normalized["results"])))
        metadata.setdefault("qualified_pool_count", len(normalized["results"]))
        metadata.setdefault("duree_totale_s", data.get("duree_totale_s", 0))
        if timestamp:
            metadata.setdefault("timestamp", timestamp)
        normalized["metadata"] = metadata
        return normalized

    @staticmethod
    def _extract_legacy_results(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        reranked_cvs = data.get("reranked_cvs")
        if isinstance(reranked_cvs, list):
            return reranked_cvs
        if isinstance(reranked_cvs, dict):
            ranked_cvs = reranked_cvs.get("ranked_cvs")
            if isinstance(ranked_cvs, list):
                return ranked_cvs

        scored_cvs = data.get("scored_cvs")
        if isinstance(scored_cvs, list):
            return scored_cvs
        return None

    @staticmethod
    def _normalize_result_item(item: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(item)
        score = normalized.get("score_final", normalized.get("score", normalized.get("score_base", 0.0)))
        normalized.setdefault("cv", normalized.get("filename", "inconnu"))
        normalized.setdefault("score_final", score)
        normalized.setdefault("score_base", normalized.get("score", score))
        normalized.setdefault("bonus_nice_have_multiplicateur", normalized.get("malus", 1.0))
        normalized.setdefault("coefficient_qualite_experience", 1.0)
        normalized.setdefault("nice_have_manquants", [])
        normalized.setdefault("commentaire_scoring", normalized.get("commentaire", ""))
        normalized.setdefault("appreciation_globale", "")
        normalized.setdefault("matrix_summary", "")
        normalized.setdefault("recommendation_level", "")
        normalized.setdefault("relevant_experience_years", None)
        normalized.setdefault("top_strengths", [])
        normalized.setdefault("watchouts", [])
        normalized.setdefault("interview_focus", [])
        normalized.setdefault("must_have_assessment", [])
        normalized.setdefault("nice_have_assessment", [])
        normalized.setdefault("algorithmic_rank", None)
        normalized.setdefault("reranked", None)
        normalized.setdefault("algorithmic_breakdown", None)
        return normalized

    @staticmethod
    def _candidate_count(data: Dict[str, Any]) -> int:
        if "metadata" in data and isinstance(data["metadata"], dict):
            return int(data["metadata"].get("top_reranked", 0) or 0)
        if isinstance(data.get("results"), list):
            return len(data["results"])
        if isinstance(data.get("reranked_cvs"), list):
            return len(data["reranked_cvs"])
        if isinstance(data.get("reranked_cvs"), dict):
            return len(data["reranked_cvs"].get("ranked_cvs", []))
        if isinstance(data.get("scored_cvs"), list):
            return len(data["scored_cvs"])
        return 0

    @staticmethod
    def _list_current_matchings(project_dir: Path) -> List[Dict[str, Any]]:
        matchings_dir = project_dir / "matchings"
        items: List[Dict[str, Any]] = []
        for key in sorted(FileStorage.list_keys(str(matchings_dir)), reverse=True):
            results_path = Path(key)
            if results_path.name != "results.json":
                continue
            try:
                data = FileStorage.load_json(str(results_path))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue

            items.append(
                {
                    "timestamp": results_path.parent.name,
                    "candidats_count": MatchingFileService._candidate_count(data),
                    "file_path": str(results_path),
                }
            )
        return items

    @staticmethod
    def _list_legacy_matchings(project_dir: Path) -> List[Dict[str, Any]]:
        historique_dir = project_dir / "historique"
        items: List[Dict[str, Any]] = []
        for key in sorted(FileStorage.list_keys(str(historique_dir)), reverse=True):
            result_file = Path(key)
            if result_file.suffix != ".json":
                continue
            try:
                data = FileStorage.load_json(str(result_file))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue

            items.append(
                {
                    "timestamp": result_file.stem,
                    "candidats_count": MatchingFileService._candidate_count(data),
                    "file_path": str(result_file),
                }
            )
        return items
