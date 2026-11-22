"""Request security helpers shared by API routers and middleware."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from brainrh.settings import get_frontend_url, get_public_api_base_url

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SAFE_FETCH_SITES = {"same-origin", "same-site", "none"}


def origin_from_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def allowed_request_origins(request: Request) -> set[str]:
    origins = {origin_from_url(str(request.url))}

    host = request.headers.get("host") or request.url.netloc
    if host:
        origins.add(f"{request.url.scheme}://{host}")

    frontend_url = get_frontend_url()
    if frontend_url:
        origins.add(origin_from_url(frontend_url))

    public_api_base_url = get_public_api_base_url()
    if public_api_base_url:
        origins.add(origin_from_url(public_api_base_url))

    return {origin for origin in origins if origin}


def is_bearer_authenticated(request: Request) -> bool:
    authorization = request.headers.get("Authorization") or ""
    return authorization.startswith("Bearer ")


def validate_cookie_authenticated_mutation_origin(
    request: Request,
    *,
    action_label: str = "cette action",
    force: bool = False,
) -> None:
    """Reject cross-site browser mutations when auth is carried by cookie.

    Bearer-token API clients are intentionally bypassed. Browser requests that
    include the auth cookie must come from the configured app/API origin or a
    same-site fetch context.
    """

    if not force and request.method.upper() not in MUTATING_METHODS:
        return
    if not request.cookies.get("access_token"):
        return
    if is_bearer_authenticated(request):
        return

    allowed_origins = allowed_request_origins(request)
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    sec_fetch_site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()

    if origin and origin not in allowed_origins:
        raise HTTPException(status_code=403, detail=f"Origin non autorisee pour {action_label}.")

    if referer:
        referer_origin = origin_from_url(referer)
        if referer_origin and referer_origin not in allowed_origins:
            raise HTTPException(status_code=403, detail=f"Referer non autorise pour {action_label}.")

    if not origin and not referer and sec_fetch_site and sec_fetch_site not in SAFE_FETCH_SITES:
        raise HTTPException(status_code=403, detail=f"Contexte navigateur non autorise pour {action_label}.")
