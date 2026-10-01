from datetime import UTC, datetime

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.security import (
    DbDep,
    OperatorDep,
    SettingsDep,
    cookie_name,
    create_session,
    login_limiter,
    resolve_session_user,
    verify_password,
)
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


def _verified_oidc_identity(claims: dict) -> tuple[str, str]:
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not subject or not email or claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="A verified email address is required")
    return subject, email


def _session_response(user, csrf_token: str | None, auth_required: bool = True) -> dict:
    return {
        "auth_required": auth_required,
        "authenticated": True,
        "auth_mode": user.auth_mode,
        "username": user.display_name,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "can_review": user.can_review,
        "can_admin": user.can_admin,
        "csrf_token": csrf_token,
    }


def _set_session_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        key=cookie_name(settings),
        value=token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.app_env.lower() == "production",
        samesite="strict",
        path="/",
    )


def _oidc_client(settings):
    oauth = OAuth()
    oauth.register(
        name="complaintops",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=(
            f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": settings.oidc_scope},
    )
    return oauth.complaintops


@router.get("/session")
def session_status(request: Request, settings: SettingsDep, db: DbDep) -> dict:
    resolved = resolve_session_user(request, settings, db)
    if resolved is None:
        return {
            "auth_required": settings.auth_required,
            "authenticated": False,
            "auth_mode": settings.auth_mode,
            "username": None,
            "email": None,
            "display_name": None,
            "role": None,
            "can_review": False,
            "can_admin": False,
            "csrf_token": None,
        }
    user, session = resolved
    return _session_response(user, session.get("csrf") or None, settings.auth_required)


@router.post("/login")
def login(
    payload: LoginInput,
    request: Request,
    response: Response,
    settings: SettingsDep,
) -> dict:
    if settings.auth_mode != "local":
        raise HTTPException(status_code=400, detail="Use company sign-in")
    if not settings.auth_required:
        raise HTTPException(status_code=400, detail="Login is not enabled in local demo mode")
    ip = request.client.host if request.client else "unknown"
    if not login_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts; try later")
    if (
        payload.username != settings.operator_username
        or not verify_password(payload.password, settings.operator_password_hash or "")
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, csrf = create_session(
        payload.username,
        settings,
        email=payload.username,
        display_name=payload.username,
        role="admin",
        auth_mode="local",
    )
    _set_session_cookie(response, token, settings)
    return {
        "auth_required": True,
        "authenticated": True,
        "auth_mode": "local",
        "username": payload.username,
        "email": payload.username,
        "display_name": payload.username,
        "role": "admin",
        "can_review": True,
        "can_admin": True,
        "csrf_token": csrf,
    }


@router.get("/oidc/login")
async def oidc_login(request: Request, settings: SettingsDep):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC sign-in is not configured")
    redirect_uri = (
        f"{settings.public_origin.rstrip('/')}/api/v1/auth/oidc/callback"
        if settings.public_origin
        else str(request.url_for("oidc_callback"))
    )
    return await _oidc_client(settings).authorize_redirect(request, redirect_uri)


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, settings: SettingsDep, db: DbDep):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC sign-in is not configured")
    try:
        token = await _oidc_client(settings).authorize_access_token(request)
    except OAuthError as error:
        raise HTTPException(status_code=401, detail="Company sign-in failed") from error
    claims = token.get("userinfo")
    if not claims:
        raise HTTPException(status_code=401, detail="Identity provider did not return user claims")
    subject, email = _verified_oidc_identity(claims)

    provider_subject = f"{settings.oidc_issuer.rstrip('/')}|{subject}"
    user = db.scalar(select(User).where(User.provider_subject == provider_subject))
    if user is None:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None and email in settings.bootstrap_admin_emails:
        user = User(email=email, display_name=claims.get("name") or email, role="admin")
        db.add(user)
    if user is None:
        raise HTTPException(status_code=403, detail="Your account has not been invited")
    if user.status == "disabled":
        raise HTTPException(status_code=403, detail="Your ComplaintOps access is disabled")
    if user.provider_subject and user.provider_subject != provider_subject:
        raise HTTPException(status_code=403, detail="This invitation is linked to another identity")

    user.provider_subject = provider_subject
    user.email = email
    user.display_name = str(claims.get("name") or user.display_name or email)[:200]
    user.status = "active"
    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    session_token, _ = create_session(
        str(user.id),
        settings,
        email=user.email,
        display_name=user.display_name or user.email,
        role=user.role,
        auth_mode="oidc",
    )
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, session_token, settings)
    return response


@router.post("/logout")
def logout(response: Response, _: OperatorDep, settings: SettingsDep) -> dict[str, bool]:
    response.delete_cookie(
        key=cookie_name(settings),
        path="/",
        secure=settings.app_env.lower() == "production",
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}
