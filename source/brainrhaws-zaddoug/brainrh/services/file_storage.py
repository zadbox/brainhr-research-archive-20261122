"""
Centralise l'acces aux fichiers BrainRH en deleguant au backend local ou S3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brainrh import paths as brainrh_paths
from brainrh.services.storage_service import get_storage_service


class FileStorage:
    @staticmethod
    def normalize_path_key(path_like: str | Path) -> str:
        return get_storage_service().normalize_key(path_like)

    @staticmethod
    def validate_and_resolve_path(relative_path: str) -> Path:
        key = FileStorage.normalize_path_key(relative_path)
        absolute_path = get_storage_service().open_local_path(key)
        if absolute_path is None:
            raise ValueError("Le backend storage actif ne fournit pas de chemin local resolvable.")
        return absolute_path

    @staticmethod
    def load_json(path_like: str | Path) -> dict[str, Any]:
        key = FileStorage.normalize_path_key(path_like)
        payload = get_storage_service().load_bytes(key)
        return json.loads(payload.decode("utf-8"))

    @staticmethod
    def save_json(relative_path: str | Path, data: dict[str, Any]) -> None:
        FileStorage.save_json_atomic(relative_path, data)

    @staticmethod
    def save_json_atomic(path_like: str | Path, data: dict[str, Any]) -> None:
        key = FileStorage.normalize_path_key(path_like)
        get_storage_service().save_json(key, data)

    @staticmethod
    def load_json_if_exists(path_like: str | Path) -> dict[str, Any] | None:
        try:
            return FileStorage.load_json(path_like)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def file_exists(relative_path: str | Path) -> bool:
        try:
            key = FileStorage.normalize_path_key(relative_path)
            return get_storage_service().exists(key)
        except ValueError:
            return False

    @staticmethod
    def delete_file(relative_path: str | Path) -> None:
        key = FileStorage.normalize_path_key(relative_path)
        get_storage_service().delete(key)

    @staticmethod
    def save_bytes(path_like: str | Path, data: bytes, *, content_type: str | None = None) -> str:
        key = FileStorage.normalize_path_key(path_like)
        get_storage_service().save_bytes(key, data, content_type=content_type)
        return key

    @staticmethod
    def save_local_file(
        path_like: str | Path,
        source_path: str | Path,
        *,
        content_type: str | None = None,
    ) -> str:
        key = FileStorage.normalize_path_key(path_like)
        get_storage_service().copy_from_local_path(key, Path(source_path), content_type=content_type)
        return key

    @staticmethod
    def load_bytes(path_like: str | Path) -> bytes:
        key = FileStorage.normalize_path_key(path_like)
        return get_storage_service().load_bytes(key)

    @staticmethod
    def list_keys(prefix: str | Path) -> list[str]:
        normalized_prefix = FileStorage.normalize_path_key(prefix)
        return [entry.key for entry in get_storage_service().list_entries(normalized_prefix)]

    @staticmethod
    def generate_download_url(
        path_like: str | Path,
        *,
        filename: str | None = None,
        disposition: str = "attachment",
        expires_seconds: int | None = None,
    ) -> str | None:
        key = FileStorage.normalize_path_key(path_like)
        return get_storage_service().generate_download_url(
            key,
            filename=filename,
            disposition=disposition,
            expires_seconds=expires_seconds,
        )

    @staticmethod
    def resolve_relative_path(path_like: str | Path) -> str:
        key = FileStorage.normalize_path_key(path_like)
        local_path = get_storage_service().open_local_path(key)
        if local_path is not None:
            return brainrh_paths.get_relative_path(local_path)
        return key

    @staticmethod
    def is_local_storage() -> bool:
        return get_storage_service().open_local_path("healthcheck.tmp") is not None

    @staticmethod
    def storage_root() -> Path:
        return brainrh_paths.STORAGE_ROOT
