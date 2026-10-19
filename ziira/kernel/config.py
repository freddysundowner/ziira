"""Settings read from environment variables (prefix ZIIRA_) or a .env file."""

import ipaddress
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

    # The address other systems (the provider) use to reach this API, for callback URLs. Must be https in production.
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

    # Where the marketing site's build output lives on this server (the website assistant reads
    # `assistant-knowledge.json` from it; docs/ai.md "Website assistant"). Empty: a short built-in text is used.
    site_dist_dir: str = ""

    # Self-service registration (kernel/registration.py). Mode: "open" (anyone may register a business), "invite" (only
    # with an invitation code from `ziira invite create`) or "closed" (businesses are created by an operator only).
    registration_mode: str = "open"
    # Units switched on for every new business, comma separated (what they require comes along).
    registration_units: str = "pos,finance,crm,purchasing,people,imports,intel,command"
    # Units for a business that registers (or is created) in standalone mode: Ziira Intelligence watching the system it
    # already has (docs/standalone-mode.md). What they require comes along.
    standalone_units: str = "connect,intel,command,imports"
    # Optional TOML file of editions that replaces the built-in ziira/kernel/editions.toml (same shape).
    editions_file: str = ""
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
    # The folder `ziira backup --dir` writes to, so the operator console can show when the last backup was taken (it
    # only reads the manifests). Empty: the console says "not reported".
    backup_dir: str = ""
    # Platform staff must confirm with a fresh second-factor code before the console changes anything if their last
    # confirmation is older than this many minutes.
    operator_mfa_max_age_minutes: int = 10
    # How platform staff (Super Admin) sign in (docs/security.md, "Platform staff sign-in"). "off": email and password
    # only; "totp": password, then a code from an authenticator app. With "off" the same freshness window above applies
    # to re-entering the password before a change. Production refuses "off" unless the choice is acknowledged.
    operator_mfa: str = "off"
    operator_mfa_off_acknowledged: bool = False
    mfa_default_off_acknowledged: bool = False      # production: new businesses start without a forced second factor
    # With "off": a sign-in ends this many hours after it began, or after this many minutes without a request.
    operator_session_hours: int = 8
    operator_idle_minutes: int = 30
    # Comma separated CIDRs (e.g. "203.0.113.0/24,2001:db8::/32") allowed to reach /api/v1/operator; empty: no limit.
    operator_allowed_networks: str = ""
    # Host names of a production install (ziira/kernel/host_routing.py): the Super Admin host and the business web app
    # host. With operator_host set, /api/v1/operator answers only for that Host header (404 elsewhere); empty: no limit.
    operator_host: str = ""
    app_host: str = ""
    # Email the operator when a sign-in comes from an address not seen before (needs the platform email provider).
    operator_signin_emails: bool = False
    # Website content (docs/platform-admin-content.md; switched off when `deployment_mode` is "selfhosted"). The address
    # a publish calls so the static site rebuilds (a POST with a signed body; treat the address as a secret, it may
    # carry a token), the key that signs that body, and how many requests a minute one address may make to the public
    # content.
    site_build_hook_url: str = ""
    site_build_hook_secret: str = ""
    site_public_rate_per_minute: int = 120
    # Reading pictures (scanned statements, photos): self-hosted Tesseract, so statements never leave the server.
    ocr_command: str = "tesseract"           # the program (a full path if it is not on PATH)
    ocr_languages: str = "eng"               # language codes joined with + (e.g. "eng+swa"); packs installed
    ocr_max_pages: int = 30                  # most pages read from one scanned file
    pg_tool_port: int = 0

    # Private file storage for photos and documents attached to records (docs/files.md). A folder on this server that
    # only the application can read; empty in development means `var/files`. Production must set it (and back it up
    # together with the databases: `ziira backup` includes it). `files_max_upload_bytes` is the most one upload request
    # may carry; each business can set a smaller file size in its settings.
    files_dir: str = ""
    files_max_upload_bytes: int = 26_500_000

    # AI layer (docs/ai.md). The provider's name (a plugin implementing the `intel.llm` extension point; "fake" is for
    # development and tests and is refused in production), the platform's secret key for it, the model, the address of
    # its API, how long one call may take and how often a failed one is retried. A business turns AI on for itself with
    # an explicit consent; in production no call is made until the operator confirms the provider's data terms.
    ai_provider: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 2
    ai_terms_confirmed: bool = False
    # Development only (`ZIIRA_AI_FAKE=1`, ignored in production): use the fake provider, which answers Ask Ziira from
    # the real tools with canned sentences, so the chat can be seen without a key. `ai_fake_delay_seconds` makes each
    # fake model call take that long (to feel and measure the chat).
    ai_fake: bool = False
    ai_fake_delay_seconds: float = 0.0

    # Plans, subscriptions and licences (docs/platform-admin.md, docs/licensing.md). "saas": this deployment sells
    # subscriptions and enforces them; "selfhosted": a business runs its own copy, subscription rows are ignored and a
    # signed licence (installed with `ziira licence install`) decides units, limits and expiry. The licence is checked
    # with the vendor's public key (base64 of the 32 raw bytes). The vendor's own deployment keeps its signing key in a
    # file named by
    # `licence_signing_key_file`; self-hosted copies never have it. `licence_required` makes an instance without a valid
    # licence read-only (leave false for development).
    deployment_mode: str = "saas"
    licence_public_key: str = ""
    licence_signing_key_file: str = ""
    licence_required: bool = False
    instance_id: str = ""
    licence_clock_tolerance_hours: int = 24
    # Plan given to a business that registers (a plan code). Empty: the edition's own default plan if it has one, else
    # none (the business is unmanaged: no limits, no billing).
    default_plan_code: str = ""

    # Third-party plugins (docs/plugin-review.md). Folders (separated by ":") whose sub-folders are plugins to load in
    # addition to the built-in ones; `ziira plugin install-archive` unpacks into the first. In production a plugin from
    # these folders loads only if it is listed in `allowed_plugins` (comma separated: `name` or `name=SHA256`, the hash
    # being the checksum of its files that the reviewer approved) and its files still match their checksum.
    extra_unit_paths: str = ""
    allowed_plugins: str = ""

    # Public API and webhooks (docs/public-api.md, docs/webhooks.md). The default requests per minute of an API key that
    # has no limit of its own; how long a webhook delivery is retried; how long a delivery keeps its body (to retry and
    # redeliver) before only its hash and first bytes remain; and how long its log lines are kept.
    api_key_rate_limit_per_minute: int = 600
    webhook_max_attempts: int = 9
    webhook_retry_hours: int = 24
    webhook_timeout_seconds: float = 10.0
    webhook_body_days: int = 7
    webhook_log_days: int = 90

    def extra_unit_path_list(self) -> list[str]:
        """The extra plugin folders as a list."""
        return [p.strip() for p in self.extra_unit_paths.split(":") if p.strip()]

    def allowed_plugin_map(self) -> dict[str, str]:
        """Allowed plugins: name -> the approved checksum ("" when only the name was given)."""
        found: dict[str, str] = {}
        for item in self.allowed_plugins.split(","):
            name, _, digest = item.strip().partition("=")
            if name:
                found[name] = digest.strip().lower()
        return found

    def operator_network_list(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """The networks allowed to reach the operator API (empty: all). Raises ValueError on a bad entry."""
        return [ipaddress.ip_network(item.strip(), strict=False)
                for item in self.operator_allowed_networks.split(",") if item.strip()]

    def operator_password_only(self) -> bool:
        """True when platform staff sign in with email and password alone."""
        return self.operator_mfa == "off"

    def cors_origin_list(self) -> list[str]:
        """The allowed CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def check_safe_for_production(self) -> None:
        """Refuse to run in production with development shortcuts switched on."""
        if self.operator_mfa not in ("off", "totp"):
            raise RuntimeError("ZIIRA_OPERATOR_MFA must be off or totp")
        try:
            self.operator_network_list()
        except ValueError as error:
            raise RuntimeError(f"ZIIRA_OPERATOR_ALLOWED_NETWORKS must list CIDRs such as 203.0.113.0/24: {error}") \
                from None
        if self.env != "production":
            return
        if self.operator_mfa == "off" and not self.operator_mfa_off_acknowledged:
            raise RuntimeError("Platform staff sign in with a password only (ZIIRA_OPERATOR_MFA=off): one stolen or "
                               "guessed password then gives control of every business. Set ZIIRA_OPERATOR_MFA=totp, "
                               "or accept the risk on purpose with ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true "
                               "(docs/security.md)")
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
        if self.mfa_default_policy == "off" and not self.mfa_default_off_acknowledged:
            raise RuntimeError("Set ZIIRA_MFA_DEFAULT_POLICY to privileged or everyone: owners, finance and admin "
                               "roles must use a second factor before real customer data. To let new businesses start "
                               "without it on purpose (each can switch it on in Settings), set "
                               "ZIIRA_MFA_DEFAULT_OFF_ACKNOWLEDGED=true")
        if self.registration_mode not in ("open", "invite", "closed"):
            raise RuntimeError("ZIIRA_REGISTRATION_MODE must be open, invite or closed")
        # Open registration without email is allowed: with no working email a new owner goes straight in after
        # choosing a password; with email, a link is sent first (registration.register).
        if self.deployment_mode not in ("saas", "selfhosted"):
            raise RuntimeError("ZIIRA_DEPLOYMENT_MODE must be saas or selfhosted")
        if self.deployment_mode == "selfhosted" and self.licence_required and not self.licence_public_key:
            raise RuntimeError("A self-hosted instance that requires a licence needs ZIIRA_LICENCE_PUBLIC_KEY")


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
