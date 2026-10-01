import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes.auth import _verified_oidc_identity
from app.core.config import Settings, get_settings
from app.core.security import (
    AuthenticatedUser,
    SlidingWindowLimiter,
    create_session,
    hash_password,
    read_session,
    require_admin,
    require_reviewer,
    verify_password,
)
from app.main import app


def secured_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        operator_username="operator",
        operator_password_hash=hash_password("a strong test password"),
        session_secret="unit-test-session-secret-with-32-plus-characters",
    )


def test_password_and_signed_session_reject_tampering() -> None:
    settings = secured_settings()
    assert verify_password("a strong test password", settings.operator_password_hash or "")
    assert not verify_password("wrong password", settings.operator_password_hash or "")
    token, csrf = create_session("operator", settings)
    assert read_session(token, settings)["csrf"] == csrf
    assert read_session(token + "x", settings) is None


def test_production_requires_security_configuration() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production")


def test_managed_postgres_url_uses_installed_psycopg_driver() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@example.neon.tech/complaintops?sslmode=require",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_production_accepts_oidc_configuration_without_local_password() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_mode="oidc",
        public_origin="https://complaintops.example",
        oidc_issuer="https://identity.example",
        oidc_client_id="complaintops",
        oidc_client_secret="client-secret",
        session_secret="unit-test-session-secret-with-32-plus-characters",
    )
    assert settings.auth_required
    assert settings.auth_mode == "oidc"


def test_render_hostname_supplies_production_origin() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_mode="oidc",
        render_external_hostname="complaintops.onrender.com",
        oidc_issuer="https://identity.example",
        oidc_client_id="complaintops",
        oidc_client_secret="client-secret",
        session_secret="unit-test-session-secret-with-32-plus-characters",
    )
    assert settings.public_origin == "https://complaintops.onrender.com"


def test_oidc_identity_requires_explicitly_verified_email() -> None:
    assert _verified_oidc_identity(
        {"sub": "auth0|123", "email": " Operator@Example.com ", "email_verified": True}
    ) == ("auth0|123", "operator@example.com")

    for claims in (
        {"sub": "auth0|123", "email": "operator@example.com"},
        {"sub": "auth0|123", "email": "operator@example.com", "email_verified": False},
    ):
        with pytest.raises(HTTPException) as error:
            _verified_oidc_identity(claims)
        assert error.value.status_code == 403


def test_roles_are_enforced_server_side() -> None:
    operator = AuthenticatedUser(None, "operator@example.com", "Operator", "operator", "oidc")
    reviewer = AuthenticatedUser(None, "reviewer@example.com", "Reviewer", "reviewer", "oidc")
    admin = AuthenticatedUser(None, "admin@example.com", "Admin", "admin", "oidc")

    with pytest.raises(Exception) as review_error:
        require_reviewer(operator)
    assert review_error.value.status_code == 403
    assert require_reviewer(reviewer) == reviewer
    with pytest.raises(Exception) as admin_error:
        require_admin(reviewer)
    assert admin_error.value.status_code == 403
    assert require_admin(admin) == admin


def test_production_login_uses_secure_host_only_cookie() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        public_origin="https://complaintops.example",
        operator_username="operator",
        operator_password_hash=hash_password("a strong test password"),
        session_secret="unit-test-session-secret-with-32-plus-characters",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app, base_url="https://complaintops.example") as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "operator", "password": "a strong test password"},
            )
            assert login.status_code == 200
            cookie = login.headers["set-cookie"]
            assert "__Host-complaintops_session=" in cookie
            assert "Secure" in cookie
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie
            assert client.get("/api/v1/evaluation/mock-baseline").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_authentication_and_csrf_protect_api() -> None:
    settings = secured_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/evaluation/mock-baseline").status_code == 401
            status = client.get("/api/v1/auth/session").json()
            assert status["auth_required"] is True
            assert status["authenticated"] is False
            assert client.post(
                "/api/v1/auth/login", json={"username": "operator", "password": "wrong"}
            ).status_code == 401
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "operator", "password": "a strong test password"},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            assert client.get("/api/v1/evaluation/mock-baseline").status_code == 200
            assert client.post("/api/v1/auth/logout").status_code == 403
            assert client.post(
                "/api/v1/auth/logout",
                headers={"X-CSRF-Token": csrf, "Origin": "https://untrusted.example"},
            ).status_code == 403
            assert client.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
            ).status_code == 200
            assert client.get("/api/v1/evaluation/mock-baseline").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_rate_limiter_stops_excess_requests() -> None:
    limiter = SlidingWindowLimiter(maximum=2, window_seconds=60)
    assert limiter.allow("operator")
    assert limiter.allow("operator")
    assert not limiter.allow("operator")
    assert limiter.allow("other")
