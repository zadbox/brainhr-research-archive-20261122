from __future__ import annotations

import json
import mimetypes
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from brainrh import paths as brainrh_paths
from brainrh.settings import (
    get_aws_region,
    get_s3_bucket_data,
    get_s3_data_prefix,
    get_storage_backend,
    get_storage_signed_url_ttl_seconds,
)


@dataclass(frozen=True)
class StorageEntry:
    key: str
    size_bytes: int | None = None
    last_modified: datetime | None = None


def _normalize_storage_key(path_like: str | Path) -> str:
    raw_value = str(path_like).strip()
    if not raw_value:
        raise ValueError("Storage key vide")

    candidate = Path(raw_value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            key = brainrh_paths.get_relative_path(resolved)
        except Exception as exc:
            raise ValueError(f"Chemin absolu hors scope stockage: {raw_value}") from exc
        return key.replace("\\", "/").lstrip("/")

    normalized_parts = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"Path traversal detecte, acces refuse: {raw_value}")
        normalized_parts.append(part)

    if not normalized_parts:
        raise ValueError("Storage key vide")

    return "/".join(normalized_parts)


class StorageService(ABC):
    @abstractmethod
    def load_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def save_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_entries(self, prefix: str) -> list[StorageEntry]:
        raise NotImplementedError

    @abstractmethod
    def open_local_path(self, key: str) -> Path | None:
        raise NotImplementedError

    @abstractmethod
    def generate_download_url(
        self,
        key: str,
        *,
        filename: str | None = None,
        disposition: str = "attachment",
        expires_seconds: int | None = None,
    ) -> str | None:
        raise NotImplementedError

    def normalize_key(self, path_like: str | Path) -> str:
        return _normalize_storage_key(path_like)

    def load_json(self, key: str) -> dict[str, Any]:
        payload = self.load_bytes(key)
        return json.loads(payload.decode("utf-8"))

    def save_json(self, key: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.save_bytes(key, payload, content_type="application/json")

    def copy_from_local_path(self, key: str, source_path: Path, *, content_type: str | None = None) -> None:
        self.save_bytes(key, source_path.read_bytes(), content_type=content_type)


class LocalStorageService(StorageService):
    def _path_for_key(self, key: str) -> Path:
        storage_root = brainrh_paths.STORAGE_ROOT.resolve()
        absolute_path = (storage_root / key).resolve()
        try:
            absolute_path.relative_to(storage_root)
        except ValueError as exc:
            raise ValueError(f"Path traversal detecte, acces refuse: {key}") from exc
        return absolute_path

    def load_bytes(self, key: str) -> bytes:
        return self._path_for_key(key).read_bytes()

    def save_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        del content_type
        absolute_path = self._path_for_key(key)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = absolute_path.parent / f"{absolute_path.name}.tmp"
        tmp_path.write_bytes(data)
        tmp_path.replace(absolute_path)

    def exists(self, key: str) -> bool:
        try:
            return self._path_for_key(key).exists()
        except ValueError:
            return False

    def delete(self, key: str) -> None:
        absolute_path = self._path_for_key(key)
        if absolute_path.exists():
            absolute_path.unlink()

    def list_entries(self, prefix: str) -> list[StorageEntry]:
        base_dir = self._path_for_key(self.normalize_key(prefix))
        if base_dir.is_file():
            return [StorageEntry(key=self.normalize_key(prefix), size_bytes=base_dir.stat().st_size)]
        if not base_dir.exists():
            return []

        entries: list[StorageEntry] = []
        for candidate in sorted(base_dir.rglob("*")):
            if not candidate.is_file():
                continue
            entries.append(
                StorageEntry(
                    key=brainrh_paths.get_relative_path(candidate),
                    size_bytes=candidate.stat().st_size,
                    last_modified=datetime.fromtimestamp(candidate.stat().st_mtime),
                )
            )
        return entries

    def open_local_path(self, key: str) -> Path | None:
        return self._path_for_key(key)

    def generate_download_url(
        self,
        key: str,
        *,
        filename: str | None = None,
        disposition: str = "attachment",
        expires_seconds: int | None = None,
    ) -> str | None:
        del key, filename, disposition, expires_seconds
        return None

    def copy_from_local_path(self, key: str, source_path: Path, *, content_type: str | None = None) -> None:
        del content_type
        absolute_path = self._path_for_key(key)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, absolute_path)


class S3StorageService(StorageService):
    def __init__(self, *, bucket: str, region: str | None, key_prefix: str = "") -> None:
        import boto3

        self.bucket = bucket
        self.region = region
        self.key_prefix = key_prefix.strip("/")
        self.client = boto3.client("s3", region_name=region)

    def _object_key(self, key: str) -> str:
        normalized = self.normalize_key(key)
        if self.key_prefix:
            return f"{self.key_prefix}/{normalized}"
        return normalized

    def load_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        return response["Body"].read()

    def save_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra_args: dict[str, Any] = {}
        guessed_content_type = content_type or mimetypes.guess_type(key)[0]
        if guessed_content_type:
            extra_args["ContentType"] = guessed_content_type
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(key),
            Body=data,
            **extra_args,
        )

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(key))

    def list_entries(self, prefix: str) -> list[StorageEntry]:
        normalized_prefix = self.normalize_key(prefix).rstrip("/")
        object_prefix = self._object_key(normalized_prefix)
        paginator = self.client.get_paginator("list_objects_v2")
        entries: list[StorageEntry] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=object_prefix):
            for item in page.get("Contents", []):
                object_key = str(item["Key"])
                key = object_key
                if self.key_prefix and object_key.startswith(f"{self.key_prefix}/"):
                    key = object_key[len(self.key_prefix) + 1 :]
                entries.append(
                    StorageEntry(
                        key=key,
                        size_bytes=item.get("Size"),
                        last_modified=item.get("LastModified"),
                    )
                )
        return entries

    def open_local_path(self, key: str) -> Path | None:
        del key
        return None

    def generate_download_url(
        self,
        key: str,
        *,
        filename: str | None = None,
        disposition: str = "attachment",
        expires_seconds: int | None = None,
    ) -> str | None:
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self._object_key(key),
        }
        if filename:
            params["ResponseContentDisposition"] = f'{disposition}; filename="{filename}"'
        return self.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_seconds or get_storage_signed_url_ttl_seconds(),
        )


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    backend = get_storage_backend()
    if backend == "s3":
        return S3StorageService(
            bucket=get_s3_bucket_data(required=True),
            region=get_aws_region(),
            key_prefix=get_s3_data_prefix(),
        )
    return LocalStorageService()


def reset_storage_service_cache() -> None:
    get_storage_service.cache_clear()
