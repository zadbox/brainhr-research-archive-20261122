from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional

import httpx

from brainrh.settings import (
    get_crustdata_api_key,
    get_crustdata_api_version,
    get_crustdata_base_url,
    get_crustdata_max_retries,
    get_crustdata_timeout_seconds,
)


ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "INVALID_API_KEY",
    402: "INSUFFICIENT_CREDITS",
    403: "PERMISSION_DENIED",
    429: "RATE_LIMITED",
}


class CrustdataError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502,
                 credits_used: Decimal | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.credits_used = credits_used


@dataclass(frozen=True)
class CrustdataResponse:
    data: Any
    credits_used: Optional[Decimal]
    rate_limit: dict[str, str]


class CrustdataClient:
    def __init__(self, *, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.api_key = api_key if api_key is not None else get_crustdata_api_key()
        self.base_url = get_crustdata_base_url()
        self.api_version = get_crustdata_api_version()
        self.max_retries = get_crustdata_max_retries()
        self.sleep = sleep
        self._enabled_endpoints: set[str] = set()
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=get_crustdata_timeout_seconds(), transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: Any):
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, payload: dict[str, Any]) -> CrustdataResponse:
        return await self._request("POST", "/person/search", json=payload)

    async def autocomplete(self, field: str, query: str) -> CrustdataResponse:
        return await self._request("POST", "/person/search/autocomplete", json={"field": field, "query": query})

    async def enrich(self, profile_urls: list[str]) -> CrustdataResponse:
        if not 1 <= len(profile_urls) <= 25:
            raise ValueError("Person Enrich accepte entre 1 et 25 URLs")
        return await self._request("POST", "/person/enrich", json={
            "professional_network_profile_urls": profile_urls,
            "fields": ["basic_profile", "social_handles", "professional_network", "experience", "education", "skills"],
        })

    async def get_credits(self) -> CrustdataResponse:
        return await self._request("GET", "/account/credits")

    async def get_endpoint_capability(self, path: str) -> CrustdataResponse:
        return await self._request("GET", "/account/endpoints", params={"path": path})

    async def ensure_endpoint_enabled(self, path: str) -> None:
        if path in self._enabled_endpoints:
            return
        response = await self.get_endpoint_capability(path)
        data = response.data
        entries: list[Any]
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict) and isinstance(data.get("endpoint"), dict):
            entries = [data["endpoint"]]
        elif isinstance(data, dict) and isinstance(data.get("endpoints"), list):
            entries = data["endpoints"]
        elif isinstance(data, dict) and isinstance(data.get("data"), list):
            entries = data["data"]
        elif isinstance(data, dict) and data:
            entries = [data]
        else:
            entries = []
        enabled = False
        for entry in entries:
            if not isinstance(entry, dict):
                enabled = True
                continue
            entry_path = str(entry.get("path") or path)
            status = str(entry.get("status") or "").lower()
            explicitly_disabled = entry.get("enabled") is False or status in {"disabled", "denied", "inactive"}
            if entry_path == path and not explicitly_disabled:
                enabled = True
        if not enabled:
            raise CrustdataError("PERMISSION_DENIED", f"Endpoint Crustdata non activé: {path}", status_code=403)
        self._enabled_endpoints.add(path)

    async def _request(self, method: str, path: str, **kwargs: Any) -> CrustdataResponse:
        if not self.api_key:
            raise CrustdataError("NOT_CONFIGURED", "Crustdata n'est pas configuré.", status_code=503)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-api-version": self.api_version,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(method, path, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise CrustdataError("PROVIDER_TIMEOUT", "Crustdata ne répond pas.", status_code=503) from exc
            error_credits_used = self._decimal_header(response.headers.get("x-credits-used"))
            if response.status_code == 429 or response.status_code >= 500:
                retry_is_safe = (
                    error_credits_used == Decimal("0")
                    or (response.status_code == 429 and error_credits_used is None)
                )
                if retry_is_safe and attempt < self.max_retries:
                    await self.sleep(self._delay(response.headers.get("x-ratelimit-reset"), attempt))
                    continue
            if response.status_code >= 400:
                code = ERROR_CODES.get(response.status_code, "PROVIDER_TEMPORARY_FAILURE" if response.status_code >= 500 else "PROVIDER_ERROR")
                try:
                    body = response.json()
                    error = body.get("error") if isinstance(body, dict) else None
                    error_dict = error if isinstance(error, dict) else {}
                    provider_type = str(error_dict.get("type") or (body.get("type") if isinstance(body, dict) else "") or "").lower()
                    message = str(error_dict.get("message") or (error if isinstance(error, str) else None)
                                  or (body.get("message") if isinstance(body, dict) else None) or code)
                except Exception:
                    provider_type, message = "", code
                if "credit" in provider_type or (response.status_code == 403 and "credit" in message.lower()):
                    code = "INSUFFICIENT_CREDITS"
                raise CrustdataError(
                    code, message, status_code=response.status_code,
                    credits_used=error_credits_used,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise CrustdataError("INVALID_PROVIDER_RESPONSE", "Réponse Crustdata invalide.") from exc
            return CrustdataResponse(
                data=data,
                credits_used=self._decimal_header(response.headers.get("x-credits-used")),
                rate_limit={key: response.headers[key] for key in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset") if key in response.headers},
            )
        raise AssertionError("unreachable")

    @staticmethod
    def _decimal_header(value: str | None) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    @staticmethod
    def _delay(reset: str | None, attempt: int) -> float:
        if reset:
            try:
                numeric = float(reset)
                if numeric > 1_000_000_000:
                    numeric -= __import__("time").time()
                return max(0.0, min(numeric, 60.0))
            except ValueError:
                try:
                    seconds = (parsedate_to_datetime(reset).timestamp() - __import__("time").time())
                    return max(0.0, min(seconds, 60.0))
                except Exception:
                    pass
        return min(8.0, (2 ** attempt) + random.uniform(0, 0.25))
