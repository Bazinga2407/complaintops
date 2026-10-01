from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ComplaintOps API"
    app_env: str = "development"
    agent_provider: str = "mock"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+psycopg://complaintops:complaintops@localhost:5432/complaintops"
    cfpb_api_base_url: str = (
        "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
    )
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    openai_max_agent_turns: int = 3
    openai_agent_max_output_tokens: int = 1200
    auth_mode: str = "local"
    operator_username: str | None = None
    operator_password_hash: str | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_scope: str = "openid profile email"
    oidc_admin_emails: str = ""
    session_secret: str | None = None
    session_hours: int = 12
    public_origin: str | None = None
    render_external_hostname: str | None = None

    @property
    def auth_required(self) -> bool:
        return (
            self.auth_mode.lower() == "oidc"
            or self.app_env.lower() == "production"
            or bool(self.operator_password_hash)
        )

    @property
    def bootstrap_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.oidc_admin_emails.split(",")
            if email.strip()
        }

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        self.auth_mode = self.auth_mode.strip().lower()
        if self.auth_mode not in {"local", "oidc"}:
            raise ValueError("AUTH_MODE must be local or oidc")
        if self.auth_mode == "local" and self.auth_required and not all(
            (self.operator_username, self.operator_password_hash, self.session_secret)
        ):
            raise ValueError(
                "Local authentication requires OPERATOR_USERNAME, OPERATOR_PASSWORD_HASH, "
                "and SESSION_SECRET"
            )
        if self.auth_mode == "oidc" and not all(
            (self.oidc_issuer, self.oidc_client_id, self.oidc_client_secret, self.session_secret)
        ):
            raise ValueError(
                "OIDC authentication requires OIDC_ISSUER, OIDC_CLIENT_ID, "
                "OIDC_CLIENT_SECRET, and SESSION_SECRET"
            )
        if self.auth_required and len(self.session_secret or "") < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters")
        if self.session_hours < 1 or self.session_hours > 24:
            raise ValueError("SESSION_HOURS must be between 1 and 24")
        render_hostname = (self.render_external_hostname or "").strip().rstrip("/")
        if not self.public_origin and render_hostname:
            self.public_origin = f"https://{render_hostname}"
        if self.app_env.lower() == "production" and not (
            self.public_origin and self.public_origin.startswith("https://")
        ):
            raise ValueError("Production requires PUBLIC_ORIGIN starting with https://")
        return self

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
