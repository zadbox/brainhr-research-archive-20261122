"""Google sign-in API; all redirect destinations are server-owned constants."""
from typing import Literal
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from api.auth_session import set_session_cookie
from api.dependencies import get_current_user
from brainrh.database import get_session_dependency
from brainrh.models.auth import UserDB
from brainrh.services import google_auth_service as google
from brainrh.services.request_limiter import InMemoryRateLimiter
from brainrh.settings import get_auth_cookie_secure, get_google_auth_config, get_google_auth_trusted_proxies

router = APIRouter(prefix="/google")
logger = logging.getLogger(__name__)


class GoogleStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["login", "invite"] = "login"
    invitation_token: str | None = Field(default=None, min_length=1, max_length=512)


class GoogleLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthorizationResponse(BaseModel):
    authorization_url: str


def _cookie_name() -> str:
    return "__Host-brainrh_google" if get_auth_cookie_secure() else "brainrh_google"


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def _client_key(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        trusted = get_google_auth_trusted_proxies()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="GOOGLE_UNAVAILABLE") from exc
    try:
        address = ipaddress.ip_address(peer)
        forwarded = request.headers.get("x-forwarded-for", "")
        if len(forwarded) > 2048:
            return peer
        # Walk right-to-left, stopping at the first untrusted hop. The trusted
        # ingress must overwrite incoming X-Forwarded-For (Caddy default).
        for hop in reversed(forwarded.split(",")):
            if not any(address in network for network in trusted):
                break
            address = ipaddress.ip_address(hop.strip())
        return str(address)
    except ValueError:
        return peer


def _rate_limit(request: Request, bucket: str, limit: int) -> None:
    allowed, retry_after = InMemoryRateLimiter.consume(
        bucket=bucket, key=_client_key(request),
        limit=limit, window_seconds=60,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="GOOGLE_RETRY_LATER", headers={"Retry-After": str(retry_after)})


def _validate_start(request: Request) -> None:
    config = google.configuration()
    # Unlike the legacy cookie guard, check even logged-out browsers. Never trust
    # a caller-supplied Host, Referer or return URL as the OAuth authority.
    if request.headers.get("origin") != config["frontend_url"]:
        raise HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")
    _rate_limit(request, "google-start", 10)


def _start_response(response: Response, result: tuple[str, str]) -> GoogleAuthorizationResponse:
    url, browser = result
    _private(response)
    response.set_cookie(
        _cookie_name(), browser, httponly=True, secure=get_auth_cookie_secure(),
        samesite="lax", path="/", max_age=google.ATTEMPT_TTL_SECONDS,
    )
    return GoogleAuthorizationResponse(authorization_url=url)


@router.get("/config")
def google_config(response: Response) -> dict[str, bool]:
    _private(response)
    return {"enabled": get_google_auth_config() is not None}


@router.post("/start", response_model=GoogleAuthorizationResponse)
def start(body: GoogleStartRequest, request: Request, response: Response,
          session: Session = Depends(get_session_dependency)):
    _validate_start(request)
    return _start_response(response, google.start_attempt(
        session, purpose=body.purpose, invitation_token=body.invitation_token,
    ))


@router.post("/link", response_model=GoogleAuthorizationResponse)
def link(body: GoogleLinkRequest, request: Request, response: Response,
         user: UserDB = Depends(get_current_user), session: Session = Depends(get_session_dependency)):
    _validate_start(request)
    return _start_response(response, google.start_attempt(
        session, purpose="link", user=user, password=body.password,
    ))


@router.get("/callback")
def callback(request: Request, session: Session = Depends(get_session_dependency)):
    config = google.configuration()
    error_page = "/login"
    try:
        get_current_user(request)
        error_page = "/profile"
    except HTTPException:
        pass
    target = f"{error_page}?google=denied"
    user_id = None
    token_version = None
    stage = "consume_attempt"
    try:
        attempt = google.consume_attempt(
            session, state=request.query_params.get("state", ""),
            browser=request.cookies.get(_cookie_name(), ""),
        )
        stage = "rate_limit"
        _rate_limit(request, "google-callback", 30)
        error = request.query_params.get("error")
        code = request.query_params.get("code", "")
        if error:
            logger.warning("Google callback rejected at provider_result")
            target = f"{error_page}?google=cancelled" if error == "access_denied" else f"{error_page}?google=denied"
        elif not code or len(code) > 4096:
            logger.warning("Google callback rejected at missing_code")
            target = f"{error_page}?google=denied"
        else:
            stage = "exchange_code"
            claims = google.exchange_code(code, attempt)
            stage = "authenticate"
            user, token_version = google.authenticate(session, attempt=attempt, claims=claims)
            user_id = str(user.id)
            target = "/profile" if attempt.purpose == "link" else "/enterprises"
    except HTTPException as exc:
        session.rollback()
        logger.warning("Google callback rejected at %s (HTTP %s)", stage, exc.status_code)
        target = f"{error_page}?google=unavailable" if exc.status_code in {429, 503} else f"{error_page}?google=denied"
    response = RedirectResponse(f"{config['frontend_url']}{target}", status_code=303)
    response.delete_cookie(_cookie_name(), path="/", secure=get_auth_cookie_secure(), httponly=True, samesite="lax")
    _private(response)
    if user_id:
        set_session_cookie(response, user_id, token_version=token_version)
    return response
