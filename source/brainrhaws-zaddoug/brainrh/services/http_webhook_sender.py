"""HTTP webhook sender implementation using httpx (INTEG-007)."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Dict, Iterable, Tuple
from urllib.parse import urlparse

import httpx

from brainrh.settings import get_webhook_allowed_hosts

logger = logging.getLogger(__name__)

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


class UnsafeWebhookTargetError(ValueError):
    """Raised when a webhook URL resolves to an unsafe network target."""


def _redacted_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.netloc}/..."


def _resolve_target_ips(hostname: str, port: int) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(hostname.strip("[]"))]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeWebhookTargetError("host cannot be resolved") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        raw_address = info[4][0]
        if raw_address in seen:
            continue
        seen.add(raw_address)
        try:
            addresses.append(ipaddress.ip_address(raw_address))
        except ValueError as exc:
            raise UnsafeWebhookTargetError("host resolved to an invalid IP address") from exc

    if not addresses:
        raise UnsafeWebhookTargetError("host resolved to no IP addresses")

    return addresses


def _reject_private_or_reserved_ips(addresses: Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> None:
    for address in addresses:
        if not address.is_global:
            raise UnsafeWebhookTargetError("host resolves to a non-public IP address")


def _host_matches_allowed_pattern(hostname: str, pattern: str) -> bool:
    normalized = pattern.strip().lower().rstrip(".")
    if not normalized:
        return False
    if normalized.startswith("*."):
        suffix = normalized[1:]
        return hostname.endswith(suffix) and hostname != normalized[2:]
    if normalized.startswith("."):
        return hostname == normalized[1:] or hostname.endswith(normalized)
    return hostname == normalized


def _enforce_optional_host_allowlist(hostname: str) -> None:
    allowed_hosts = get_webhook_allowed_hosts()
    if not allowed_hosts:
        return
    if not any(_host_matches_allowed_pattern(hostname, pattern) for pattern in allowed_hosts):
        raise UnsafeWebhookTargetError("target host is not in the webhook allowlist")


def validate_webhook_target_url(url: str) -> str:
    """Validate a webhook URL before storing or sending it.

    The sender is an outbound network primitive. It must not be allowed to reach
    loopback, private networks, link-local metadata services, or reserved ranges.
    """

    normalized = url.strip()
    if not normalized:
        raise UnsafeWebhookTargetError("target URL is required")

    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https":
        raise UnsafeWebhookTargetError("target URL must use https")
    if not parsed.hostname:
        raise UnsafeWebhookTargetError("target URL host is required")
    if parsed.username or parsed.password:
        raise UnsafeWebhookTargetError("target URL must not contain credentials")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise UnsafeWebhookTargetError("target host is not allowed")
    _enforce_optional_host_allowlist(hostname)

    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise UnsafeWebhookTargetError("target URL port is invalid") from exc
    if port != 443:
        raise UnsafeWebhookTargetError("target URL must use the default https port")

    _reject_private_or_reserved_ips(_resolve_target_ips(hostname, port))
    return normalized


def httpx_sender(url: str, headers: Dict[str, str], body: str) -> Tuple[int, str]:
    """Send a webhook payload after validating the target URL."""

    redacted_url = _redacted_url(url)
    try:
        safe_url = validate_webhook_target_url(url)
    except UnsafeWebhookTargetError as exc:
        logger.warning("Blocked unsafe webhook target %s: %s", redacted_url, exc)
        return 400, "Unsafe webhook target"

    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            response = client.post(safe_url, headers=headers, content=body)
            return response.status_code, response.text
    except httpx.TimeoutException as exc:
        logger.warning("Timeout (10s) sending webhook to %s: %s", redacted_url, exc)
        return 408, f"Timeout: {exc}"
    except httpx.RequestError as exc:
        logger.warning("Network error sending webhook to %s: %s", redacted_url, exc)
        return 502, f"Target unreachable: {exc}"
    except Exception as exc:
        logger.error("Unexpected error sending webhook to %s: %s", redacted_url, exc)
        return 500, f"Internal Error: {exc}"
