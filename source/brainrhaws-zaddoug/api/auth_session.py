"""One session-cookie contract for password and federated authentication."""
from fastapi import Response

from brainrh.services.auth_service import create_access_token
from brainrh.settings import get_auth_cookie_domain, get_auth_cookie_samesite, get_auth_cookie_secure


def set_session_cookie(response: Response, user_id: str, *, token_version: int | None = None) -> None:
    max_age = 60 * 60 * 24 * 7
    claims = {"sub": user_id}
    if token_version is not None:
        claims["token_version"] = token_version
    response.set_cookie(
        key="access_token", value=create_access_token(data=claims),
        httponly=True, max_age=max_age, expires=max_age,
        samesite=get_auth_cookie_samesite(), secure=get_auth_cookie_secure(),
        domain=get_auth_cookie_domain(), path="/",
    )
