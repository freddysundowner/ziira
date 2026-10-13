"""Settings read from environment variables (prefix ZIIRA_) or a .env file."""

from functools import lru_cache
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "development-only-secret-change-me"
DEV_CREDENTIALS_KEY = "development-only-credentials-key-change-me"


class Settings(BaseSettings):
    """Runtime configuration for Ziira Core."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ZIIRA_", extra="ignore")

    env: str = "development"

    # Master database: the list of tenants and how to reach each tenant's own database,
    # the platform's installed units, and migration status. Owner connection.
    master_database_url: str = "postgresql+psycopg://ziira:ziira@localhost:5432/ziira_master"

    # Server where new tenant databases are created: a role allowed to create databases and
    # roles, connected to any existing database (e.g. postgres). Tenants can later be moved
    # to other servers by changing their connection in the master database.
    tenant_server_url: str = "postgresql+psycopg://ziira:ziira@localhost:5432/postgres"
    # Names on that server: <prefix><workspace code> for databases and per-tenant logins,
    # and the kernel-only template every new tenant database is copied from.
    tenant_db_prefix: str = "ziira_t_"
    tenant_role_prefix: str = "zt_"
    template_database: str = "ziira_template"

    # Encrypts tenant database credentials stored in the master database.
    credentials_key: str = DEV_CREDENTIALS_KEY

    # Development only: take the tenant from the X-Tenant-ID header, with every permission.
    # Requests with a bearer token or API key are always authenticated properly.
    # Must be false in production.
    dev_tenant_header: bool = True

    # Development only: tenant used when a request has no X-Tenant-ID header,
    # so the API can be browsed directly. Set by scripts/run_local.sh.
    dev_default_tenant: UUID | None = None

    # Behind a reverse proxy, take the client address (for the audit log) from the last entry of
    # X-Forwarded-For, which the proxy appends. Leave false unless a proxy you control sets it.
    trust_forwarded_for: bool = False

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
        if self.credentials_key == DEV_CREDENTIALS_KEY or len(self.credentials_key) < 32:
            raise RuntimeError("Set ZIIRA_CREDENTIALS_KEY to a random value of at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
