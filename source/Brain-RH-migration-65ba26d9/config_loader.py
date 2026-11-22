"""
Module de chargement de configuration pour le système de matching CV/RH
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

class Config:
    """Classe pour gérer la configuration centralisée"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialise la configuration

        Args:
            config_path: Chemin vers le fichier config.yaml
        """
        self.config_path = config_path
        self._config = self._load_yaml_config()
        self._validate_env_vars()
        self._create_directories()

    def _load_yaml_config(self) -> Dict[str, Any]:
        """Charge le fichier YAML de configuration"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"⚠️ Fichier {self.config_path} introuvable. Utilisation de la config par défaut.")
            return self._default_config()
        except yaml.YAMLError as e:
            print(f"❌ Erreur lors du chargement du YAML: {e}")
            return self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """Configuration par défaut si le fichier YAML est absent"""
        return {
            "llm": {
                "model": "gpt-5-mini",
                "temperature_extraction": 0.1,
                "temperature_reranking": 0.2,
                "timeout": 30000,
                "max_retries": 3
            },
            "rome": {
                "enabled": False,
                "base_url": "https://api.francetravail.io/rome/v1",
                "timeout": 10000,
                "max_retries": 3
            },
            "paths": {
                "cv_input_folder": "cv_input",
                "cv_json_folder": "cv_json",
                "offres_folder": "offres",
                "output_folder": "output",
                "logs_folder": "logs",
                "cache_folder": "cache"
            },
            "scoring": {
                "top_k": 50,
                "top_rerank": 10,
                "min_similarity": 0.3,
                "nice_have_malus_factor": 0.9,
                "bonus_experience_exacte": 0.15,
                "bonus_experience_tres_proche": 0.10,
                "bonus_experience_proche": 0.05,
                "score_min": 0.0,
                "score_max": 1.0
            }
        }

    def _validate_env_vars(self):
        """Valide que les variables d'environnement critiques sont présentes"""
        required_vars = ["OPENAI_API_KEY"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            print(f"⚠️ Variables d'environnement manquantes: {', '.join(missing_vars)}")
            print("Assurez-vous que le fichier .env contient ces variables.")

        # Vérifier ROME si activé
        if self.get("rome.enabled", False):
            rome_vars = ["ROME_CLIENT_ID", "ROME_CLIENT_SECRET"]
            missing_rome = [var for var in rome_vars if not os.getenv(var)]
            if missing_rome:
                print(f"⚠️ ROME activé mais variables manquantes: {', '.join(missing_rome)}")

    def _create_directories(self):
        """Crée les répertoires nécessaires s'ils n'existent pas"""
        paths = self._config.get("paths", {})

        dirs_to_create = [
            paths.get("cv_input_folder", "cv_input"),
            paths.get("cv_json_folder", "cv_json"),
            paths.get("offres_folder", "offres"),
            paths.get("output_folder", "output"),
            paths.get("logs_folder", "logs"),
            paths.get("cache_folder", "cache")
        ]

        for dir_path in dirs_to_create:
            Path(dir_path).mkdir(parents=True, exist_ok=True)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Récupère une valeur de configuration avec notation pointée

        Args:
            key_path: Chemin de la clé (ex: "llm.model" ou "scoring.top_k")
            default: Valeur par défaut si la clé n'existe pas

        Returns:
            La valeur de configuration ou la valeur par défaut

        Example:
            config.get("llm.model") → "gpt-5-nano"
            config.get("scoring.top_k") → 50
        """
        keys = key_path.split(".")
        value = self._config

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default

        return value

    def get_env(self, var_name: str, default: str = None) -> str:
        """
        Récupère une variable d'environnement

        Args:
            var_name: Nom de la variable
            default: Valeur par défaut

        Returns:
            La valeur de la variable d'environnement
        """
        return os.getenv(var_name, default)

    def get_openai_api_key(self) -> str:
        """Récupère la clé API OpenAI"""
        return self.get_env("OPENAI_API_KEY", "")

    def get_rome_credentials(self) -> Dict[str, str]:
        """Récupère les credentials ROME"""
        return {
            "client_id": self.get_env("ROME_CLIENT_ID", ""),
            "client_secret": self.get_env("ROME_CLIENT_SECRET", "")
        }

    def is_rome_enabled(self) -> bool:
        """Vérifie si l'enrichissement ROME est activé"""
        return self.get("rome.enabled", False)

    def get_llm_model(self) -> str:
        """Récupère le nom du modèle LLM"""
        return self.get("llm.model", "gpt-5-mini")

    def get_paths(self) -> Dict[str, str]:
        """Récupère tous les chemins configurés"""
        return self.get("paths", {})

    def get_scoring_config(self) -> Dict[str, Any]:
        """Récupère la configuration de scoring"""
        return self.get("scoring", {})

    def __repr__(self) -> str:
        return f"Config(model={self.get_llm_model()}, rome_enabled={self.is_rome_enabled()})"


# Instance globale de configuration (singleton)
_config_instance = None

def get_config(config_path: str = "config.yaml") -> Config:
    """
    Récupère l'instance de configuration (singleton)

    Args:
        config_path: Chemin vers le fichier de configuration

    Returns:
        Instance de Config
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_path)
    return _config_instance


# Pour faciliter l'usage direct
if __name__ == "__main__":
    # Test de la configuration
    config = get_config()

    print("📋 Configuration chargée:")
    print(f"  - Modèle LLM: {config.get_llm_model()}")
    print(f"  - ROME activé: {config.is_rome_enabled()}")
    print(f"  - Top K: {config.get('scoring.top_k')}")
    print(f"  - Top rerank: {config.get('scoring.top_rerank')}")
    print(f"  - API Key présente: {'Oui' if config.get_openai_api_key() else 'Non'}")

    print("\n📁 Chemins:")
    for name, path in config.get_paths().items():
        print(f"  - {name}: {path}")
