"""scripts/check_env.py (production configuration check) and scripts/secret_scan.py."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_env, secret_scan = load("check_env"), load("secret_scan")

GOOD = {
    "ZIIRA_ENV": "production", "ZIIRA_SECRET_KEY": "k9Qz3vB7nLp2XsWm8TgYd5HaCe4RuJ6fVo1iNb0AqZx",
    "ZIIRA_CREDENTIALS_KEY": "Zt5Gm2YhPq8WcKd1RvLs7NxEb3UaJf9OiTy4HwCe6Mn",
    "ZIIRA_DEV_TENANT_HEADER": "false", "ZIIRA_MFA_DEFAULT_POLICY": "privileged",
    "ZIIRA_MASTER_DATABASE_URL": "postgresql+psycopg://ziira:Vf8mQ2xLr9TnWc4Zh7Kd@db.internal:5432/ziira_master?sslmode=require",
    "ZIIRA_TENANT_SERVER_URL": "postgresql+psycopg://ziira:Vf8mQ2xLr9TnWc4Zh7Kd@db.internal:5432/postgres?sslmode=require",
    "ZIIRA_PUBLIC_BASE_URL": "https://api.example.com", "ZIIRA_PUBLIC_WEB_URL": "https://app.example.com",
    "ZIIRA_REGISTRATION_MODE": "invite", "ZIIRA_PLATFORM_EMAIL_PROVIDER": "smtp",
    "ZIIRA_PLATFORM_EMAIL_SECRET": '{"password": "x"}', "ZIIRA_PLATFORM_EMAIL_CONFIG": '{"from_address": "a@example.com"}',
    "ZIIRA_METRICS_TOKEN": "mT7qW2eR9yU4iO1pA6sD3fG8hJ5kL0zX", "ZIIRA_LOG_FORMAT": "json",
    "ZIIRA_CORS_ORIGINS": "https://app.example.com", "ZIIRA_TRUST_FORWARDED_FOR": "true",
    "ZIIRA_OPERATOR_MFA": "totp",
}


def errors(env: dict[str, str]) -> list[str]:
    return [f.name for f in check_env.check(env) if f.level == "ERROR"]


def test_a_complete_production_configuration_has_no_errors() -> None:
    assert errors(GOOD) == []
    assert [f for f in check_env.check(GOOD) if f.level == "WARN"] == []


@pytest.mark.parametrize("change, expected", [
    ({"ZIIRA_ENV": "development"}, "ZIIRA_ENV"),
    ({"ZIIRA_SECRET_KEY": ""}, "ZIIRA_SECRET_KEY"),
    ({"ZIIRA_SECRET_KEY": "development-only-secret-change-me"}, "ZIIRA_SECRET_KEY"),
    ({"ZIIRA_SECRET_KEY": "short"}, "ZIIRA_SECRET_KEY"),
    ({"ZIIRA_CREDENTIALS_KEY": "a" * 40}, "ZIIRA_CREDENTIALS_KEY"),
    ({"ZIIRA_CREDENTIALS_KEY": GOOD["ZIIRA_SECRET_KEY"]}, "ZIIRA_CREDENTIALS_KEY"),
    ({"ZIIRA_DEV_TENANT_HEADER": "true"}, "ZIIRA_DEV_TENANT_HEADER"),
    ({"ZIIRA_MFA_DEFAULT_POLICY": "off"}, "ZIIRA_MFA_DEFAULT_POLICY"),
    ({"ZIIRA_DEV_DEFAULT_TENANT": "3f2b8c1e-1234-4abc-9def-123456789012"}, "ZIIRA_DEV_DEFAULT_TENANT"),
    ({"ZIIRA_MASTER_DATABASE_URL": "postgresql+psycopg://ziira:ziira@db.internal/ziira_master"}, "ZIIRA_MASTER_DATABASE_URL"),
    ({"ZIIRA_TENANT_SERVER_URL": ""}, "ZIIRA_TENANT_SERVER_URL"),
    ({"ZIIRA_PUBLIC_BASE_URL": "http://api.example.com"}, "ZIIRA_PUBLIC_BASE_URL"),
    ({"ZIIRA_PUBLIC_WEB_URL": "https://localhost:5173"}, "ZIIRA_PUBLIC_WEB_URL"),
    ({"ZIIRA_PLATFORM_EMAIL_PROVIDER": ""}, "ZIIRA_PLATFORM_EMAIL_PROVIDER"),
    ({"ZIIRA_PLATFORM_EMAIL_PROVIDER": "carrier-pigeon"}, "ZIIRA_PLATFORM_EMAIL_PROVIDER"),
    ({"ZIIRA_PLATFORM_EMAIL_SECRET": ""}, "ZIIRA_PLATFORM_EMAIL_SECRET"),
    ({"ZIIRA_PLATFORM_EMAIL_CONFIG": "{not json"}, "ZIIRA_PLATFORM_EMAIL_CONFIG"),
    ({"ZIIRA_REGISTRATION_MODE": "everyone"}, "ZIIRA_REGISTRATION_MODE"),
    ({"ZIIRA_METRICS_TOKEN": ""}, "ZIIRA_METRICS_TOKEN"),
    ({"ZIIRA_METRICS_TOKEN": "short"}, "ZIIRA_METRICS_TOKEN"),
    ({"ZIIRA_METRICS_TOKEN": GOOD["ZIIRA_SECRET_KEY"]}, "ZIIRA_METRICS_TOKEN"),
    ({"ZIIRA_CORS_ORIGINS": "*"}, "ZIIRA_CORS_ORIGINS"),
    ({"ZIIRA_CORS_ORIGINS": "http://app.example.com"}, "ZIIRA_CORS_ORIGINS"),
    ({"ZIIRA_CORS_ORIGINS": "https://app.example.com/path"}, "ZIIRA_CORS_ORIGINS"),
    ({"ZIIRA_LOG_FORMAT": "xml"}, "ZIIRA_LOG_FORMAT"),
    ({"ZIIRA_MAX_BODY_BYTES": "lots"}, "ZIIRA_MAX_BODY_BYTES"),
    ({"ZIIRA_OPERATOR_MFA": "sms"}, "ZIIRA_OPERATOR_MFA"),
    ({"ZIIRA_OPERATOR_MFA": "off"}, "ZIIRA_OPERATOR_MFA"),                       # not acknowledged
    ({"ZIIRA_OPERATOR_ALLOWED_NETWORKS": "10.0.0.0/8, not-a-network"}, "ZIIRA_OPERATOR_ALLOWED_NETWORKS"),
    ({"ZIIRA_OPERATOR_IDLE_MINUTES": "soon"}, "ZIIRA_OPERATOR_IDLE_MINUTES"),
])
def test_each_unsafe_setting_is_an_error(change: dict[str, str], expected: str) -> None:
    assert expected in errors({**GOOD, **change})


def test_password_only_operators_are_a_visible_choice() -> None:
    off = {**GOOD, "ZIIRA_OPERATOR_MFA": "off"}
    assert "ZIIRA_OPERATOR_MFA" in errors(off)                                    # the default is refused in production
    accepted = {**off, "ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED": "true"}
    assert errors(accepted) == []
    warnings = {f.name: f.message for f in check_env.check(accepted) if f.level == "WARN"}
    assert "every business" in warnings["ZIIRA_OPERATOR_MFA"]                      # the risk is spelled out
    assert {"ZIIRA_OPERATOR_ALLOWED_NETWORKS", "ZIIRA_OPERATOR_SIGNIN_EMAILS"} <= set(warnings)
    covered = {**accepted, "ZIIRA_OPERATOR_ALLOWED_NETWORKS": "203.0.113.0/24", "ZIIRA_OPERATOR_SIGNIN_EMAILS": "true"}
    assert [f.name for f in check_env.check(covered) if f.level == "WARN"] == ["ZIIRA_OPERATOR_MFA"]


def test_closed_registration_needs_no_email_provider() -> None:
    env = {k: v for k, v in GOOD.items() if "EMAIL" not in k}
    assert errors({**env, "ZIIRA_REGISTRATION_MODE": "closed"}) == []
    assert errors({**env, "ZIIRA_REGISTRATION_MODE": "open"}) == ["ZIIRA_PLATFORM_EMAIL_PROVIDER"]


def test_the_env_file_reader_handles_comments_quotes_and_export(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text('# comment\n\nZIIRA_A=1\nexport ZIIRA_B="two words"\nZIIRA_C=\'x\'\nnot a setting\n')
    assert check_env.read_env_file(f) == {"ZIIRA_A": "1", "ZIIRA_B": "two words", "ZIIRA_C": "x"}


def test_the_application_agrees_the_good_configuration_is_safe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import Settings

    for key, value in GOOD.items():
        monkeypatch.setenv(key, value)
    Settings().check_safe_for_production()


# --------------------------------------------------------------------------- secret scan
def test_secret_scan_finds_real_looking_secrets_and_a_tracked_env(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text(
        'ok = "nothing here"\n'
        'API_KEY = "' + "Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7" + '"\n'
        'url = "postgresql://svc:Sup3rS3cretPw@db.example.com/x"\n'
        "token = 'ghp_" + "a" * 36 + "'\n"
        "# -----BEGIN RSA PRIVATE KEY-----\n"
        'fine = "password=changeme"  # secret-scan: ignore\n')
    (tmp_path / ".env").write_text("X=1\n")
    problems = secret_scan.scan([Path("app.py"), Path(".env")])
    text = "\n".join(problems)
    assert "app.py:2" in text and "app.py:3" in text and "app.py:4" in text and "app.py:5" in text
    assert "app.py:6" not in text and "app.py:1:" not in text
    assert ".env: an environment file is tracked" in text


def test_the_repository_itself_is_clean() -> None:
    assert secret_scan.scan(secret_scan.tracked_files()) == []


def test_the_application_refuses_password_only_operators_in_production_unless_acknowledged(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import Settings

    for key, value in GOOD.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ZIIRA_OPERATOR_MFA", "off")
    with pytest.raises(RuntimeError, match="ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED"):
        Settings().check_safe_for_production()
    monkeypatch.setenv("ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED", "true")
    Settings().check_safe_for_production()                                        # starts, by explicit choice
    monkeypatch.setenv("ZIIRA_OPERATOR_MFA", "sms")
    with pytest.raises(RuntimeError, match="off or totp"):
        Settings().check_safe_for_production()
    monkeypatch.setenv("ZIIRA_OPERATOR_MFA", "totp")
    monkeypatch.setenv("ZIIRA_OPERATOR_ALLOWED_NETWORKS", "203.0.113.0/24, nonsense")
    with pytest.raises(RuntimeError, match="CIDR"):
        Settings().check_safe_for_production()


def test_development_does_not_need_the_acknowledgement(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import Settings

    monkeypatch.setenv("ZIIRA_ENV", "development")
    monkeypatch.setenv("ZIIRA_OPERATOR_MFA", "off")
    monkeypatch.delenv("ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED", raising=False)
    Settings().check_safe_for_production()
