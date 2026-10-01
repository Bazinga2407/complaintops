"""Authentication, authorization, CSRF protection, and local rate limits."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

COOKIE_DEV = "complaintops_session"
COOKIE_PROD = "__Host-complaintops_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
Role = Literal["operator", "reviewer", "admin"]


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID | None
    email: str
    display_name: str
    role: Role
    auth_mode: str

    @property
    def key(self) -> str:
        return str(self.id) if self.id else self.email

    @property
    def can_review(self) -> bool:
        return self.role in {"reviewer", "admin"}

    @property
    def can_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Operator password must be at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt:16384:8:1:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split(":")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        expected = bytes.fromhex(expected_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=16384,
            r=8,
            p=1,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def cookie_name(settings: Settings) -> str:
    return COOKIE_PROD if settings.app_env.lower() == "production" else COOKIE_DEV


def create_session(
    subject: str,
    settings: Settings,
    *,
    email: str | None = None,
    display_name: str | None = None,
    role: Role = "admin",
    auth_mode: str | None = None,
) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(32)
    mode = auth_mode or settings.auth_mode
    payload = {
        "sub": subject,
        "user": subject,
        "email": email or subject,
        "name": display_name or subject,
        "role": role,
        "auth_mode": mode,
        "expires": int(time.time()) + settings.session_hours * 3600,
        "csrf": csrf,
    }
    message = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _encode(
        hmac.digest((settings.session_secret or "").encode("utf-8"), message.encode(), "sha256")
    )
    return f"{message}.{signature}", csrf


def read_session(token: str | None, settings: Settings) -> dict | None:
    if not token or len(token) > 4096:
        return None
    try:
        message, signature = token.split(".", maxsplit=1)
        expected = _encode(
            hmac.digest((settings.session_secret or "").encode("utf-8"), message.encode(), "sha256")
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_decode(message))
        if (
            not isinstance(payload.get("sub"), str)
            or not isinstance(payload.get("csrf"), str)
            or int(payload.get("expires", 0)) <= time.time()
            or payload.get("auth_mode") != settings.auth_mode
        ):
            return None
        if settings.auth_mode == "local" and payload.get("sub") != settings.operator_username:
            return None
        return payload
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None


class SlidingWindowLimiter:
    def __init__(self, maximum: int, window_seconds: int):
        self.maximum = maximum
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if len(self.events) > 10_000:
                self.events = defaultdict(deque)
            events = self.events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.maximum:
                return False
            events.append(now)
            return True


login_limiter = SlidingWindowLimiter(5, 15 * 60)
write_limiter = SlidingWindowLimiter(60, 60)
analysis_limiter = SlidingWindowLimiter(5, 60)
daily_analysis_limiter = SlidingWindowLimiter(20, 24 * 3600)
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def resolve_session_user(
    request: Request, settings: Settings, db: Session
) -> tuple[AuthenticatedUser, dict] | None:
    if not settings.auth_required:
        return (
            AuthenticatedUser(None, "demo@local", "Demo Operator", "admin", "demo"),
            {"csrf": ""},
        )
    session = read_session(request.cookies.get(cookie_name(settings)), settings)
    if session is None:
        return None
    if settings.auth_mode == "local":
        return (
            AuthenticatedUser(
                None,
                str(session.get("email") or session["sub"]),
                str(session.get("name") or session["sub"]),
                "admin",
                "local",
            ),
            session,
        )
    try:
        user_id = uuid.UUID(session["sub"])
    except (ValueError, TypeError):
        return None
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    return (
        AuthenticatedUser(user.id, user.email, user.display_name or user.email, user.role, "oidc"),
        session,
    )


def _protect_write(request: Request, settings: Settings, user: AuthenticatedUser, session: dict) -> None:
    if request.method not in UNSAFE_METHODS or not settings.auth_required:
        return
    supplied = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(supplied, session["csrf"]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    origin = request.headers.get("origin")
    allowed_origins = {str(request.base_url).rstrip("/")}
    if settings.public_origin:
        allowed_origins.add(settings.public_origin.rstrip("/"))
    if settings.app_env.lower() != "production":
        allowed_origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})
    if origin and origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="Cross-origin write denied")
    if not write_limiter.allow(user.key):
        raise HTTPException(status_code=429, detail="Too many write requests")


def require_user(request: Request, settings: SettingsDep, db: DbDep) -> AuthenticatedUser:
    resolved = resolve_session_user(request, settings, db)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    user, session = resolved
    _protect_write(request, settings, user, session)
    request.state.operator = user.display_name
    request.state.identity = user
    return user


UserDep = Annotated[AuthenticatedUser, Depends(require_user)]
OperatorDep = UserDep
require_operator = require_user


def require_reviewer(user: UserDep) -> AuthenticatedUser:
    if not user.can_review:
        raise HTTPException(status_code=403, detail="Reviewer or administrator role required")
    return user


def require_admin(user: UserDep) -> AuthenticatedUser:
    if not user.can_admin:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user


ReviewerDep = Annotated[AuthenticatedUser, Depends(require_reviewer)]
AdminDep = Annotated[AuthenticatedUser, Depends(require_admin)]


def limit_analysis(request: Request, operator: OperatorDep) -> None:
    key = f"{operator.key}:{request.client.host if request.client else 'unknown'}"
    if not analysis_limiter.allow(key):
        raise HTTPException(status_code=429, detail="Analysis rate limit exceeded")
    if not daily_analysis_limiter.allow(key):
        raise HTTPException(status_code=429, detail="Daily analysis limit exceeded")


if __name__ == "__main__":
    import getpass

    print(hash_password(getpass.getpass("New operator password: ")))
