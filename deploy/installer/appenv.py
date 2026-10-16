"""The production environment file, built from the choices and the secrets."""
from __future__ import annotations

import json

from installer.config import Config


def build(cfg: Config, *, secret_key: str, credentials_key: str, metrics_token: str, master_url: str, server_url: str,
          hook_secret: str, hook_token: str, pg_major: int, rebuild: bool) -> dict[str, str]:
    """Every ZIIRA_* value the installer sets. Existing files are merged with this (missing keys only)."""
    env: dict[str, str] = {
        "ZIIRA_ENV": "production",
        "ZIIRA_DEPLOYMENT_MODE": "saas",
        "ZIIRA_DEV_TENANT_HEADER": "false",
        "ZIIRA_MASTER_DATABASE_URL": master_url,
        "ZIIRA_TENANT_SERVER_URL": server_url,
        "ZIIRA_SECRET_KEY": secret_key,
        "ZIIRA_CREDENTIALS_KEY": credentials_key,
        "ZIIRA_METRICS_TOKEN": metrics_token,
        "ZIIRA_PUBLIC_BASE_URL": f"https://{cfg.app_host}",
        "ZIIRA_PUBLIC_WEB_URL": f"https://{cfg.app_host}",
        "ZIIRA_APP_HOST": cfg.app_host,
        "ZIIRA_OPERATOR_HOST": cfg.admin_host,
        "ZIIRA_TRUST_FORWARDED_FOR": "true",
        "ZIIRA_LOG_FORMAT": "json",
        "ZIIRA_LOG_LEVEL": "INFO",
        # Kept equal to the nginx limits in nginxconf.py (2 MB bodies, 11 MB for statement uploads).
        "ZIIRA_MAX_BODY_BYTES": "2000000",
        "ZIIRA_MAX_UPLOAD_BYTES": "10500000",
        "ZIIRA_HSTS_MAX_AGE": "0" if cfg.hsts == "off" else "31536000",
        "ZIIRA_MFA_DEFAULT_POLICY": "privileged",
        "ZIIRA_REGISTRATION_MODE": cfg.registration_mode,
        "ZIIRA_OPERATOR_MFA": cfg.operator_mfa,
        "ZIIRA_BACKUP_DIR": cfg.backup_dir,
        "ZIIRA_TEMPLATE_DATABASE": cfg.template_db,
        "ZIIRA_TENANT_DB_PREFIX": cfg.tenant_db_prefix,
        "ZIIRA_TENANT_ROLE_PREFIX": cfg.tenant_role_prefix,
        "ZIIRA_PG_DUMP_COMMAND": f"/usr/lib/postgresql/{pg_major}/bin/pg_dump",
        "ZIIRA_PG_RESTORE_COMMAND": f"/usr/lib/postgresql/{pg_major}/bin/pg_restore",
    }
    if cfg.operator_mfa == "off":
        # The owner chose email + password for platform staff. The application refuses this in production unless
        # the choice is acknowledged on purpose; the installer prints the warning and sets the flag (docs/security.md).
        env["ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED"] = "true"
    if cfg.operator_networks.strip():
        env["ZIIRA_OPERATOR_ALLOWED_NETWORKS"] = cfg.operator_networks.replace(" ", "")
    if cfg.default_plan:
        env["ZIIRA_DEFAULT_PLAN_CODE"] = cfg.default_plan
    if cfg.smtp_host:
        env["ZIIRA_PLATFORM_EMAIL_PROVIDER"] = "smtp"
        env["ZIIRA_PLATFORM_EMAIL_SECRET"] = json.dumps(
            {"host": cfg.smtp_host, "port": cfg.smtp_port, "username": cfg.smtp_user, "password": cfg.smtp_password},
            separators=(",", ":"))
        env["ZIIRA_PLATFORM_EMAIL_CONFIG"] = json.dumps(
            {"from_address": cfg.smtp_from, "from_name": cfg.smtp_from_name}, separators=(",", ":"))
    if rebuild:
        # The application only calls https addresses in production, so the receiver sits behind the admin host.
        env["ZIIRA_SITE_BUILD_HOOK_URL"] = f"https://{cfg.admin_host}/_hooks/site-rebuild/{hook_token}"
        env["ZIIRA_SITE_BUILD_HOOK_SECRET"] = hook_secret
    return env


def rebuild_env(cfg: Config, *, hook_secret: str, hook_token: str) -> dict[str, str]:
    """The environment of the website rebuild receiver and of every site build (public values plus the signing secret)."""
    return {
        "ZIIRA_REBUILD_PORT": str(cfg.rebuild_port),
        "ZIIRA_REBUILD_SECRET": hook_secret,
        "ZIIRA_REBUILD_TOKEN": hook_token,
        "ZIIRA_INSTALL_DIR": cfg.install_dir,
        "ZIIRA_WEB_ROOT": cfg.web_root,
        "ZIIRA_STATE_DIR": cfg.state_dir,
        "PUBLIC_SITE_URL": f"https://{cfg.root_domain}",
        "PUBLIC_APP_URL": f"https://{cfg.app_host}",
        # Build-time only: the build fetches the published content from the API on this same server.
        "PUBLIC_PLATFORM_API_URL": f"http://127.0.0.1:{cfg.api_port}",
        "SITE_STRICT": "1" if cfg.site_strict else "",
    }
