"""Settings read from environment variables (prefix ZIIRA_) or a .env file."""

from functools import lru_cache
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Development only: take the tenant from the X-Tenant-ID header.
    # Replaced by authentication in a later phase.
    dev_tenant_header: bool = True

    # Development only: tenant used when a request has no X-Tenant-ID header,
    # so the API can be browsed directly. Set by scripts/run_local.sh.
    dev_default_tenant: UUID | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
