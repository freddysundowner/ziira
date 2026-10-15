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

    # Connection pools (docs/operations.md). Each cached tenant database has its own pool of `db_pool_size` connections
    # plus up to `db_max_overflow` extra under load. Behind PgBouncer in transaction pooling mode set `pgbouncer=true`
    # (turns off server-side prepared statements, which a transaction pooler cannot keep per connection).
    db_pool_size: int = 2
    db_max_overflow: int = 8
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    master_pool_size: int = 5
    pgbouncer: bool = False
    # Longest a statement of a tenant transaction may run (SET LOCAL, so it is safe behind PgBouncer). 0 = no limit.
    # Migrations and provisioning use the admin login and are not limited.
    statement_timeout_ms: int = 60000

    # How many tenant databases keep an open connection pool at once. Each pool holds a few connections, and PostgreSQL
    # allows a limited number in total, so the least recently used pools are closed beyond this (they reopen on demand).
    max_cached_tenant_engines: int = 25

    # The address other systems (Safaricom) use to reach this API, for callback URLs. Must be https in production.
    public_base_url: str = "http://localhost:8000"

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

    # Self-service registration (kernel/registration.py). Mode: "open" (anyone may register a business), "invite" (only
    # with an invitation code from `ziira invite create`) or "closed" (businesses are created by an operator only).
    registration_mode: str = "open"
    # Units switched on for every new business, comma separated (what they require comes along).
    registration_units: str = "pos,finance,crm,purchasing,people,imports,intel,command"
    # Units for a business that registers (or is created) in standalone mode: Ziira Intelligence watching the system it
    # already has (docs/standalone-mode.md). What they require comes along.
    standalone_units: str = "connect,intel,command,imports"
    registration_per_email_per_hour: int = 3
    registration_per_ip_per_hour: int = 10
    registration_token_hours: int = 24
    # Where the emailed verification link points (the web app), and how the platform sends that email: a provider name
    # from the messaging plugin (smtp, brevo, resend, sendgrid) with its secret and config as JSON. Empty provider:
    # development and tests use a fake one; production refuses to start with open registration and no way to send mail.
    public_web_url: str = "http://localhost:5173"
    platform_email_provider: str = ""
    platform_email_secret: str = ""
    platform_email_config: str = ""

    # Sign-in protection (kernel/throttle.py): this many wrong passwords for one login from one address, for one login
    # from anywhere, or from one address for any login, within the window, lock that key for the lock time.
    throttle_login_ip_failures: int = 5
    throttle_login_failures: int = 20
    throttle_ip_failures: int = 60
    throttle_window_minutes: int = 15
    throttle_lock_minutes: int = 15
    # Second factor: the default for a new business ("off", "privileged": people with powerful roles, "everyone"), the
    # name shown in authenticator apps, and how long a password reset link works.
    mfa_default_policy: str = "off"
    mfa_issuer: str = "Ziira"
    password_reset_hours: int = 2

    # Signs access tokens. Must be set to a long random value outside development.
    secret_key: str = DEV_SECRET_KEY
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # A session not refreshed for this long must sign in again.
    session_idle_hours: int = 12

    # Operations and application security (docs/operations.md).
    # Token for GET /metrics (Authorization: Bearer ...). Production refuses /metrics while this is empty.
    metrics_token: str = ""
    metrics_cache_seconds: int = 15
    log_format: str = "text"                # "text" or "json" (one JSON object per line, for log shippers)
    log_level: str = "INFO"
    # Browser origins allowed to call the API from another site, comma separated (empty: none). Never "*" in production.
    cors_origins: str = ""
    max_body_bytes: int = 2_000_000         # larger requests are refused with 413
    max_upload_bytes: int = 10_500_000      # the same for a statement or export upload (a file is the body)
    hsts_max_age: int = 31_536_000          # Strict-Transport-Security, production only
    # Backups (docs/operations.md). Empty: use pg_dump / pg_restore from PATH. Set when the local client is older than
    # the server, e.g. "docker exec -i -e PGPASSWORD ziira-core-db-1 pg_dump" (the command reads/writes stdin/stdout).
    pg_dump_command: str = ""
    pg_restore_command: str = ""
    pg_tool_host: str = ""                  # host/port the tool above uses to reach the server (inside the container)
    # Reading pictures (scanned statements, photos): self-hosted Tesseract, so statements never leave the server.
    ocr_command: str = "tesseract"           # the program (a full path if it is not on PATH)
    ocr_languages: str = "eng"               # language codes joined with + (e.g. "eng+swa"); packs installed
    ocr_max_pages: int = 30                  # most pages read from one scanned file
    pg_tool_port: int = 0

    # AI layer (docs/ai.md). The provider's name (a plugin implementing the `intel.llm` extension point; "fake" is for
    # development and tests and is refused in production), the platform's secret key for it, the model, the address of
    # its API, how long one call may take and how often a failed one is retried. A business turns AI on for itself with
    # an explicit consent; in production no call is made until the operator confirms the provider's data terms.
    ai_provider: str = "anthropic"
    ai_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    ai_base_url: str = "https://api.anthropic.com"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 2
    ai_terms_confirmed: bool = False

    def cors_origin_list(self) -> list[str]:
        """The allowed CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
        if "*" in self.cors_origin_list():
            raise RuntimeError("ZIIRA_CORS_ORIGINS must list origins, never *")
        if self.log_format not in ("text", "json"):
            raise RuntimeError("ZIIRA_LOG_FORMAT must be text or json")
        if self.metrics_token and len(self.metrics_token) < 24:
            raise RuntimeError("ZIIRA_METRICS_TOKEN must be at least 24 characters (or empty to switch /metrics off)")
        if self.mfa_default_policy not in ("off", "privileged", "everyone"):
            raise RuntimeError("ZIIRA_MFA_DEFAULT_POLICY must be off, privileged or everyone")
        if self.mfa_default_policy == "off":
            raise RuntimeError("Set ZIIRA_MFA_DEFAULT_POLICY to privileged or everyone: owners, finance and admin "
                               "roles must use a second factor before real customer data")
        if self.registration_mode not in ("open", "invite", "closed"):
            raise RuntimeError("ZIIRA_REGISTRATION_MODE must be open, invite or closed")
        if self.registration_mode != "closed" and not self.platform_email_provider:
            raise RuntimeError("Registration needs ZIIRA_PLATFORM_EMAIL_PROVIDER (and its secret) to send the "
                               "verification email; or set ZIIRA_REGISTRATION_MODE=closed")


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
