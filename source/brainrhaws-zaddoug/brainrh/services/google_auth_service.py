"""Invite-only Google OIDC. No account creation, Google token storage or role inference."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from brainrh.models.audit_log import AuditLogDB
from brainrh.models.auth import GoogleAuthAttemptDB, GoogleIdentityDB, UserDB
from brainrh.services.auth_service import get_user_token_version, verify_password
from brainrh.services.invitation_service import InvitationService
from brainrh.settings import get_google_auth_config

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ATTEMPT_TTL_SECONDS = 600
_jwks_lock = threading.Lock()
_jwks: dict = {}
_jwks_expires = 0.0
logger = logging.getLogger(__name__)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _deny() -> HTTPException:
    return HTTPException(status_code=403, detail="GOOGLE_ACCESS_DENIED")


def configuration() -> dict[str, str]:
    config = get_google_auth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="GOOGLE_UNAVAILABLE")
    return config


def start_attempt(session: Session, *, purpose: str, invitation_token: str | None = None,
                  user: UserDB | None = None, password: str | None = None) -> tuple[str, str]:
    config = configuration()
    invitation_digest = None
    version = None
    if purpose == "invite":
        if not invitation_token or InvitationService().inspect(invitation_token).status != "ready":
            raise _deny()
        invitation_digest = digest(invitation_token)
    elif purpose == "link":
        if (
            user is None or not user.is_active or not user.hashed_password
            or not password or len(password.encode("utf-8")) > 72
            or not verify_password(password, user.hashed_password)
        ):
            raise _deny()
        if session.get(GoogleIdentityDB, user.id):
            raise _deny()
        version = get_user_token_version(session, str(user.id))
    elif purpose != "login":
        raise _deny()
    state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    session.execute(delete(GoogleAuthAttemptDB).where(GoogleAuthAttemptDB.expires_at <= _now()))
    session.add(GoogleAuthAttemptDB(
        state_digest=digest(state), browser_digest=digest(browser), nonce_digest=digest(nonce),
        code_verifier=verifier, purpose=purpose, user_id=str(user.id) if user else None,
        token_version=version, invitation_digest=invitation_digest,
        expires_at=_now() + timedelta(seconds=ATTEMPT_TTL_SECONDS),
    ))
    session.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return AUTHORIZATION_URL + "?" + urlencode({
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": "openid email profile", "state": state,
        "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account",
    }), browser


def consume_attempt(session: Session, *, state: str, browser: str) -> GoogleAuthAttemptDB:
    if not state or not browser or len(state) > 512 or len(browser) > 512:
        raise _deny()
    attempt = session.get(GoogleAuthAttemptDB, digest(state))
    if (
        attempt is None or _utc(attempt.expires_at) <= _now()
        or not hmac.compare_digest(attempt.browser_digest, digest(browser))
    ):
        raise _deny()
    # Atomic compare-and-delete: only one callback can claim this attempt, even
    # across workers. Consume before network IO, including cancellation/errors.
    session.expunge(attempt)
    claimed = session.execute(delete(GoogleAuthAttemptDB).where(
        GoogleAuthAttemptDB.state_digest == attempt.state_digest,
        GoogleAuthAttemptDB.browser_digest == digest(browser),
        GoogleAuthAttemptDB.expires_at > _now(),
    )).rowcount
    session.commit()
    if claimed != 1:
        raise _deny()
    return attempt


def _google_keys(client: httpx.Client, *, refresh: bool = False) -> dict:
    global _jwks, _jwks_expires
    with _jwks_lock:
        if refresh or time.monotonic() >= _jwks_expires:
            response = client.get(JWKS_URL)
            response.raise_for_status()
            keys = response.json()
            if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list):
                raise ValueError("Invalid key set")
            _jwks = keys
            _jwks_expires = time.monotonic() + 300
        return _jwks


def verify_id_token(token: str, keys: dict, *, client_id: str, nonce_digest: str,
                    access_token: str | None = None) -> dict:
    try:
        claims = jwt.decode(
            token, keys, algorithms=["RS256"], audience=client_id, access_token=access_token,
            options={"require_exp": True, "require_iat": True, "require_sub": True, "require_aud": True},
        )
        if (
            claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
            or claims.get("aud") != client_id
            or claims.get("azp", client_id) != client_id
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("email"), str) or len(claims["email"]) > 320
            or "@" not in claims["email"]
            or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255
            or not isinstance(claims.get("nonce"), str)
            or not hmac.compare_digest(digest(claims["nonce"]), nonce_digest)
            or not isinstance(claims.get("iat"), (int, float)) or claims["iat"] > time.time() + 60
        ):
            raise _deny()
        return claims
    except (JWTError, ValueError, TypeError, KeyError) as exc:
        raise _deny() from exc


def exchange_code(code: str, attempt: GoogleAuthAttemptDB) -> dict:
    config = configuration()
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.post(TOKEN_URL, data={
                "code": code, "client_id": config["client_id"], "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"], "grant_type": "authorization_code",
                "code_verifier": attempt.code_verifier,
            })
            response.raise_for_status()
            token_response = response.json()
            token = token_response.get("id_token")
            access_token = token_response.get("access_token")
            if (
                not isinstance(token, str) or len(token) > 16384
                or not isinstance(access_token, str) or not access_token
            ):
                raise _deny()
            keys = _google_keys(client)
            header = jwt.get_unverified_header(token)
            if header.get("kid") not in {key.get("kid") for key in keys["keys"]}:
                keys = _google_keys(client, refresh=True)
            return verify_id_token(
                token, keys, client_id=config["client_id"], nonce_digest=attempt.nonce_digest,
                access_token=access_token,
            )
    except (httpx.HTTPError, JWTError, ValueError, TypeError, AttributeError) as exc:
        # Do not log HTTP bodies, codes, state, credentials or claims.
        raise HTTPException(status_code=503, detail="GOOGLE_UNAVAILABLE") from exc


def authenticate(session: Session, *, attempt: GoogleAuthAttemptDB, claims: dict) -> tuple[UserDB, int]:
    subject = claims["sub"]
    email = claims["email"].strip().lower()
    identity = session.exec(select(GoogleIdentityDB).where(GoogleIdentityDB.subject == subject)).first()
    if attempt.purpose == "invite":
        user = InvitationService().accept_google(session, digest=attempt.invitation_digest or "", verified_email=email)
    elif attempt.purpose == "link":
        user = session.exec(select(UserDB).where(UserDB.id == attempt.user_id).with_for_update()).first()
        if user is None or attempt.token_version != get_user_token_version(session, str(user.id)):
            raise _deny()
    else:
        # No lookup or automatic linking by email. Unknown Google IDs are refused.
        user = session.exec(select(UserDB).where(UserDB.id == identity.user_id).with_for_update()).first() if identity else None
    if user is None or not user.is_active or not hmac.compare_digest(user.email.strip().lower().encode("utf-8"), email.encode("utf-8")):
        logger.warning("Google authentication rejected: account_mismatch")
        raise _deny()
    current = session.get(GoogleIdentityDB, str(user.id))
    if (identity and identity.user_id != str(user.id)) or (current and current.subject != subject):
        logger.warning("Google authentication rejected: identity_conflict")
        raise _deny()
    if not current:
        if attempt.purpose not in {"invite", "link"}:
            raise _deny()
        current = GoogleIdentityDB(user_id=str(user.id), subject=subject)
    name = claims.get("name")
    current.display_name = " ".join(name.split())[:200] if isinstance(name, str) else None
    session.add(current)
    session.add(AuditLogDB(
        enterprise_id="SYSTEM", actor_user_id=str(user.id), action="auth.google.success",
        resource_type="user", resource_id=str(user.id), metadata_json=json.dumps({"purpose": attempt.purpose}),
    ))
    try:
        session.flush()
        version = get_user_token_version(session, str(user.id))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        logger.warning("Google authentication rejected: identity_integrity_conflict")
        raise _deny() from exc
    session.refresh(user)
    return user, version
