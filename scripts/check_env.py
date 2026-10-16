#!/usr/bin/env python3
"""Check a production configuration before deploying it.

    python scripts/check_env.py [path/to/.env]        # default: .env, plus the process environment on top

Prints one line per problem (ERROR stops a deployment, WARN is advice) and exits 1 if there is any ERROR.
It reads only the settings; it connects to nothing. Standard library only, so it runs anywhere.
The same rules are partly enforced by the application at start-up (`Settings.check_safe_for_production`); this
script is stricter and also looks at consistency (registration needs email, metrics need a token, ...).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

DEV_SECRET_KEY = "development-only-secret-change-me"
DEV_CREDENTIALS_KEY = "development-only-credentials-key-change-me"
WEAK_PASSWORDS = {"ziira", "password", "postgres", "admin", "secret", "changeme", "123456"}
EMAIL_PROVIDERS = {"smtp", "brevo", "resend", "sendgrid"}


@dataclass(frozen=True)
class Finding:
    level: str          # "ERROR" or "WARN"
    name: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:<5} {self.name}: {self.message}"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines of a .env file (comments and blank lines skipped, surrounding quotes removed)."""
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        name = key.strip()
        values[(name[len("export "):] if name.startswith("export ") else name).strip()] = value
    return values


def _is_true(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _weak_secret(value: str) -> bool:
    return len(set(value)) < 8                  # "aaaa...", "1212..." and other obviously patterned values


def check(env: dict[str, str]) -> list[Finding]:
    """All findings for these settings. Names are given without the ZIIRA_ prefix in `env` keys: with it."""
    out: list[Finding] = []

    def get(name: str, default: str = "") -> str:
        return env.get(f"ZIIRA_{name}", default).strip()

    def error(name: str, message: str) -> None:
        out.append(Finding("ERROR", f"ZIIRA_{name}", message))

    def warn(name: str, message: str) -> None:
        out.append(Finding("WARN", f"ZIIRA_{name}", message))

    if get("ENV") != "production":
        error("ENV", f"is '{get('ENV') or 'development'}': set ZIIRA_ENV=production "
                     "(development shortcuts stay on otherwise)")

    # --- secrets
    for name, dev in (("SECRET_KEY", DEV_SECRET_KEY), ("CREDENTIALS_KEY", DEV_CREDENTIALS_KEY)):
        value = get(name)
        if not value:
            error(name, "is not set (it has a development default that must never run in production)")
        elif value == dev:
            error(name, "still has the development value")
        elif len(value) < 32:
            error(name, f"is {len(value)} characters; use at least 32 random ones (python -c 'import secrets; "
                        "print(secrets.token_urlsafe(48))')")
        elif _weak_secret(value):
            error(name, "looks patterned, not random")
    if get("SECRET_KEY") and get("SECRET_KEY") == get("CREDENTIALS_KEY"):
        error("CREDENTIALS_KEY", "must differ from ZIIRA_SECRET_KEY (one signs tokens, the other encrypts "
                                 "database logins)")

    # --- development shortcuts
    if _is_true(get("DEV_TENANT_HEADER", "true")):
        error("DEV_TENANT_HEADER", "must be false: the X-Tenant-ID header would act with every permission")
    if get("DEV_DEFAULT_TENANT"):
        error("DEV_DEFAULT_TENANT", "must be empty in production")

    # --- databases
    for name in ("MASTER_DATABASE_URL", "TENANT_SERVER_URL"):
        value = get(name)
        if not value:
            error(name, "is not set (the default points at a local development database)")
            continue
        url = urlparse(value)
        password = unquote(url.password or "")
        if not password or password.lower() in WEAK_PASSWORDS or len(password) < 16:
            error(name, "the database password is missing, a known default, or shorter than 16 characters")
        if url.hostname in ("localhost", "127.0.0.1", "::1"):
            warn(name, "points at this machine; fine only if PostgreSQL runs on the same server")
        elif "sslmode" not in value:
            warn(name, "has no sslmode=...; use sslmode=require (or verify-full) when the database is on another host")
    if get("TENANT_DB_PREFIX", "ziira_t_") != "ziira_t_":
        warn("TENANT_DB_PREFIX", "changing the prefix after tenants exist orphans their databases")
    if _is_true(get("PGBOUNCER")) and not (get("PG_TOOL_HOST") or get("PG_TOOL_PORT")):
        warn("PGBOUNCER", "true: pg_dump must connect to PostgreSQL itself, not through PgBouncer; if the "
                          "database URLs point at the pooler, set ZIIRA_PG_TOOL_HOST / ZIIRA_PG_TOOL_PORT to "
                          "PostgreSQL's own address")

    if get("MFA_DEFAULT_POLICY", "off") not in ("privileged", "everyone"):
        error("MFA_DEFAULT_POLICY", "must be privileged or everyone: owners and finance roles need a second factor "
                                    "(the application refuses to start in production otherwise)")

    # --- platform staff (Super Admin) sign-in
    operator_mfa = get("OPERATOR_MFA", "off")
    if operator_mfa not in ("off", "totp"):
        error("OPERATOR_MFA", "must be off or totp")
    elif operator_mfa == "off":
        if not _is_true(get("OPERATOR_MFA_OFF_ACKNOWLEDGED")):
            error("OPERATOR_MFA", "off: platform staff sign in with a password only, and the application refuses to "
                                  "start in production unless you accept that on purpose "
                                  "(ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true) or choose ZIIRA_OPERATOR_MFA=totp")
        else:
            warn("OPERATOR_MFA", "off, acknowledged. Risk: one stolen or guessed Super Admin password gives control of "
                                 "every business (units, plans, prices, licences, payment settings, support access). "
                                 "Compensate with long unique passwords in a secrets manager, ZIIRA_OPERATOR_ALLOWED_"
                                 "NETWORKS, ZIIRA_OPERATOR_SIGNIN_EMAILS and reading the operator trail "
                                 "(docs/security.md)")
        if not get("OPERATOR_ALLOWED_NETWORKS"):
            warn("OPERATOR_ALLOWED_NETWORKS", "empty: the Super Admin is reachable from any address; with a password "
                                              "alone, restrict it to your office or VPN addresses "
                                              "(here and at the proxy)")
        if not _is_true(get("OPERATOR_SIGNIN_EMAILS")):
            warn("OPERATOR_SIGNIN_EMAILS", "false: operators are not told about a sign-in from a new address")
    for name, low, high in (("OPERATOR_SESSION_HOURS", 1, 24), ("OPERATOR_IDLE_MINUTES", 5, 240)):
        value = get(name)
        if value:
            try:
                if not low <= int(value) <= high:
                    warn(name, f"{value}: keep it between {low} and {high}; shorter limits protect a stolen session")
            except ValueError:
                error(name, "must be a whole number")
    for network in (n.strip() for n in get("OPERATOR_ALLOWED_NETWORKS").split(",") if n.strip()):
        try:
            ipaddress.ip_network(network, strict=False)
        except ValueError:
            error("OPERATOR_ALLOWED_NETWORKS", f"'{network}' is not a network such as 203.0.113.0/24")

    # --- public addresses
    for name in ("PUBLIC_BASE_URL", "PUBLIC_WEB_URL"):
        value = get(name)
        if not value or "localhost" in value or "127.0.0.1" in value:
            error(name, "is not set to the real public address (default is a local address)")
        elif not value.startswith("https://"):
            error(name, "must be https:// (payment callbacks and verification links)")

    # --- registration, email
    mode = get("REGISTRATION_MODE", "open")
    if mode not in ("open", "invite", "closed"):
        error("REGISTRATION_MODE", "must be open, invite or closed")
    elif mode != "closed":
        provider = get("PLATFORM_EMAIL_PROVIDER")
        if not provider:
            warn("PLATFORM_EMAIL_PROVIDER", f"registration is '{mode}' and no environment email is set: sign-up stays "
                                             "closed until email is set up in the Super Admin (Platform > Email)")
        elif provider not in EMAIL_PROVIDERS:
            error("PLATFORM_EMAIL_PROVIDER", f"'{provider}' is not one of: {', '.join(sorted(EMAIL_PROVIDERS))}")
        if provider and not get("PLATFORM_EMAIL_SECRET"):
            error("PLATFORM_EMAIL_SECRET", "is empty: the provider cannot send without its secret")
        for name in ("PLATFORM_EMAIL_SECRET", "PLATFORM_EMAIL_CONFIG"):
            value = get(name)
            if value:
                try:
                    json.loads(value)
                except ValueError:
                    error(name, "is not valid JSON")
        if provider and not get("PLATFORM_EMAIL_CONFIG"):
            warn("PLATFORM_EMAIL_CONFIG", "is empty: set at least from_address")
    if mode == "open":
        warn("REGISTRATION_MODE", "open: anyone can create a business; 'invite' is safer while you onboard customers")

    # --- metrics, logging, browser access
    token = get("METRICS_TOKEN")
    if not token:
        error("METRICS_TOKEN", "is not set: /metrics answers 403 in production, so monitoring would be blind")
    elif len(token) < 24 or _weak_secret(token):
        error("METRICS_TOKEN", "must be at least 24 random characters")
    elif token in (get("SECRET_KEY"), get("CREDENTIALS_KEY")):
        error("METRICS_TOKEN", "must not reuse another secret (it sits in your monitoring system's configuration)")
    if get("LOG_FORMAT", "text") not in ("text", "json"):
        error("LOG_FORMAT", "must be text or json")
    elif get("LOG_FORMAT", "text") != "json":
        warn("LOG_FORMAT", "text: use json so a log system can search by request id and tenant")
    if get("LOG_LEVEL", "INFO").upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        error("LOG_LEVEL", "must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    elif get("LOG_LEVEL", "INFO").upper() == "DEBUG":
        warn("LOG_LEVEL", "DEBUG in production logs a lot and may include more detail than you want to keep")
    origins = [o.strip() for o in get("CORS_ORIGINS").split(",") if o.strip()]
    for origin in origins:
        if origin == "*":
            error("CORS_ORIGINS", "never * (list the exact origins of your web app)")
        elif not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", origin):
            error("CORS_ORIGINS", f"'{origin}' must look like https://app.example.com (no path, https only)")
    web = get("PUBLIC_WEB_URL")
    web_host = urlparse(web).netloc
    if origins and web_host and not any(urlparse(o).netloc == web_host for o in origins):
        warn("CORS_ORIGINS", "does not include the web app's own origin (ZIIRA_PUBLIC_WEB_URL); only needed when the "
                             "web app and API are on different origins")
    try:
        if int(get("MAX_BODY_BYTES", "2000000")) > 20_000_000:
            warn("MAX_BODY_BYTES", "above 20 MB: large bodies are a cheap way to exhaust memory")
    except ValueError:
        error("MAX_BODY_BYTES", "must be a number")

    # --- proxy and backups
    if not _is_true(get("TRUST_FORWARDED_FOR")):
        warn("TRUST_FORWARDED_FOR", "false: behind a reverse proxy every audit-log entry will show the proxy's "
                                    "address; set true only if the proxy overwrites X-Forwarded-For")
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(".env")
    env: dict[str, str] = {}
    if path.exists():
        env.update(read_env_file(path))
    elif len(argv) > 1:
        print(f"ERROR no such file: {path}")
        return 1
    env.update({k: v for k, v in os.environ.items() if k.startswith("ZIIRA_")})
    findings = check(env)
    for f in findings:
        print(f)
    errors = sum(f.level == "ERROR" for f in findings)
    verdict = "" if errors else " - configuration is acceptable"
    print(f"\n{errors} error(s), {len(findings) - errors} warning(s){verdict}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
