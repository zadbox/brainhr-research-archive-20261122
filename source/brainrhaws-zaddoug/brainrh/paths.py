"""
Gestion des chemins du projet
Calcul du PROJECT_ROOT pour éliminer les hacks sys.path
"""

from pathlib import Path
import subprocess
from typing import Optional


def _existing_non_empty_file(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def _get_git_common_dir(project_root: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None

    raw_path = result.stdout.strip()
    if not raw_path:
        return None

    common_dir = Path(raw_path)
    if not common_dir.is_absolute():
        common_dir = (project_root / common_dir).resolve()
    return common_dir


def _resolve_storage_root(project_root: Path) -> Path:
    local_db = project_root / "brainrh.db"
    if _existing_non_empty_file(local_db):
        return project_root

    common_dir = _get_git_common_dir(project_root)
    if common_dir is None:
        return project_root

    shared_repo_root = common_dir.parent
    shared_db = shared_repo_root / "brainrh.db"
    if _existing_non_empty_file(shared_db):
        return shared_repo_root

    return project_root


# PROJECT_ROOT = racine du code/config actif (où se trouve config.yaml)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# STORAGE_ROOT = racine canonique du namespace de stockage réellement utilisé
STORAGE_ROOT = _resolve_storage_root(PROJECT_ROOT)

# Chemins principaux
CONFIG_FILE = PROJECT_ROOT / "config.yaml"
ENV_FILE = PROJECT_ROOT / ".env"
DATABASE_FILE = STORAGE_ROOT / "brainrh.db"

# Dossiers de données
# PROJECTS_DIR (LEGACY - supprimé) = STORAGE_ROOT / "projects"
ENTERPRISES_DIR = STORAGE_ROOT / "enterprises"
# CV_JSON_DIR (LEGACY - supprimé) = STORAGE_ROOT / "cv_json"
CACHE_DIR = PROJECT_ROOT / "cache"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"


def get_relative_path(absolute_path: Path) -> str:
    """
    Convertit un chemin absolu en chemin relatif au PROJECT_ROOT

    Args:
        absolute_path: Chemin absolu

    Returns:
        Chemin relatif sous forme de string
    """
    try:
        return str(absolute_path.resolve().relative_to(STORAGE_ROOT.resolve()))
    except ValueError:
        # Si le chemin n'est pas sous STORAGE_ROOT, retourner tel quel
        return str(absolute_path)


def get_absolute_path(relative_path: str) -> Path:
    """
    Convertit un chemin relatif (depuis json_path) en chemin absolu

    Args:
        relative_path: Chemin relatif au PROJECT_ROOT

    Returns:
        Chemin absolu (Path)
    """
    return STORAGE_ROOT / relative_path
