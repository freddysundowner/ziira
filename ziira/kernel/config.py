"""Settings read from environment variables (prefix ZIIRA_) or a .env file."""

from functools import lru_cache
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "development-only-secret-change-me"


class Settings(BaseSettings):
    """Runtime configuration for Ziira Core."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ZIIRA_", extra="ignore")

    env: str = "development"

    # Owner connection: used only for migrations and admin commands.
    admin_database_url: str = "postgresql+psycopg://ziira:ziira@localhost:5432/ziira"

    # Application connection: a role that does NOT own the tables,
    # so PostgreSQL row-level security applies to every query.
    app_database_url: str = "postgresql+psycopg://ziira_app:ziira_app@localhost:5432/ziira"
    app_db_role: str = "ziira_app"

    # Development only: take the tenant from the X-Tenant-ID header, with every permission.
    # Requests with a bearer token or API key are always authenticated properly.
    # Must be false in production.
    dev_tenant_header: bool = True

    # Development only: tenant used when a request has no X-Tenant-ID header,
    # so the API can be browsed directly. Set by scripts/run_local.sh.
    dev_default_tenant: UUID | None = None

    # Signs access tokens. Must be set to a long random value outside development.
    secret_key: str = DEV_SECRET_KEY
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # A session not refreshed for this long must sign in again.
    session_idle_hours: int = 12

    def check_safe_for_production(self) -> None:
        """Refuse to run in production with development shortcuts switched on."""
        if self.env != "production":
            return
        if self.dev_tenant_header:
            raise RuntimeError("ZIIRA_DEV_TENANT_HEADER must be false in production")
        if self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32:
            raise RuntimeError("Set ZIIRA_SECRET_KEY to a random value of at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
