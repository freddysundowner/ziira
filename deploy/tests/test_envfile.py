"""The environment file: quoting, merging, masking, and that what we generate passes the project's own checker."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from installer import appenv, config, envfile

REPO = Path(__file__).resolve().parents[2]
SECRET = "Kq3vZ8wLmN2xT7yUe9RbHc4JdFa6GsPo1QiXtVn0"  # secret-scan: ignore (test fixture)
CREDENTIALS = "W5eRtY7uIoP9aSdF2gHjK4lZxC6vBnM1qAwSzXe8"
DBPW = "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4z"


def check_env_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("check_env", REPO / "scripts" / "check_env.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["check_env"] = module               # dataclasses with postponed annotations look the module up here
    spec.loader.exec_module(module)                 # type: ignore[union-attr]
    return module


def generated(*extra: str) -> dict[str, str]:
    cfg, _ = config.load(["--root-domain", "ziira.io", "--email", "o@z.io", "--admin-email", "m@z.io", "--smtp-host", "smtp.z.io",
                          "--smtp-from", "no-reply@z.io", *extra], {"ZIIRA_INSTALL_SMTP_PASSWORD": "mail-pass"})
    cfg.resolve_defaults()
    return appenv.build(
        cfg, secret_key=SECRET, credentials_key=CREDENTIALS, metrics_token="Tk3Jd9Lq2Xw8Rn5Vb7Cm4Zs6",
        master_url=f"postgresql+psycopg://ziira:{DBPW}@127.0.0.1:5432/ziira_master",
        server_url=f"postgresql+psycopg://ziira:{DBPW}@127.0.0.1:5432/postgres",
        hook_secret="Zq8Xw3Er5Ty7Ui9Op1As2Df4Gh6JkLm", hook_token="Tok3nAbCdEf1234567", pg_major=16, rebuild=True)  # secret-scan: ignore (test fixture)


def test_generated_environment_passes_the_projects_own_checker() -> None:
    env = generated()
    findings = check_env_module().check(env)
    errors = [str(f) for f in findings if f.level == "ERROR"]
    assert errors == []


def test_generated_environment_values_are_the_documented_ones() -> None:
    env = generated()
    assert env["ZIIRA_ENV"] == "production" and env["ZIIRA_DEV_TENANT_HEADER"] == "false"
    assert env["ZIIRA_TRUST_FORWARDED_FOR"] == "true" and env["ZIIRA_MFA_DEFAULT_POLICY"] == "off" and env["ZIIRA_MFA_DEFAULT_OFF_ACKNOWLEDGED"] == "true"
    assert env["ZIIRA_PUBLIC_BASE_URL"] == env["ZIIRA_PUBLIC_WEB_URL"] == "https://app.ziira.io"
    assert env["ZIIRA_OPERATOR_HOST"] == "admin.ziira.io" and env["ZIIRA_APP_HOST"] == "app.ziira.io"
    assert env["ZIIRA_OPERATOR_MFA"] == "off" and env["ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED"] == "true"
    assert env["ZIIRA_MAX_BODY_BYTES"] == "2000000" and env["ZIIRA_MAX_UPLOAD_BYTES"] == "10500000"
    assert env["ZIIRA_PG_DUMP_COMMAND"] == "/usr/lib/postgresql/16/bin/pg_dump"
    assert env["ZIIRA_SITE_BUILD_HOOK_URL"] == "https://admin.ziira.io/_hooks/site-rebuild/Tok3nAbCdEf1234567"
    assert json.loads(env["ZIIRA_PLATFORM_EMAIL_SECRET"])["password"] == "mail-pass"
    assert json.loads(env["ZIIRA_PLATFORM_EMAIL_CONFIG"])["from_address"] == "no-reply@z.io"
    assert "ZIIRA_OPERATOR_ALLOWED_NETWORKS" not in env


def test_totp_choice_and_networks() -> None:
    env = generated("--operator-mfa", "totp", "--operator-networks", "203.0.113.0/24, 2001:db8::/32")
    assert env["ZIIRA_OPERATOR_MFA"] == "totp" and "ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED" not in env
    assert env["ZIIRA_OPERATOR_ALLOWED_NETWORKS"] == "203.0.113.0/24,2001:db8::/32"


def test_hsts_off_sets_the_api_header_to_zero() -> None:
    assert generated("--staging")["ZIIRA_HSTS_MAX_AGE"] == "0"


def test_render_parse_round_trip_with_awkward_values() -> None:
    values = {"A": "x", "B": '{"host":"smtp","pw":"a b $c %d \\\\ e"}', "C": "postgresql+psycopg://u:p%40@h/db", "D": ""}
    assert envfile.parse(envfile.render(values)) == values


@given(st.dictionaries(st.from_regex(r"ZIIRA_[A-Z_]{1,12}", fullmatch=True),
                       st.text(alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"), blacklist_characters="'"), max_size=40),
                       max_size=8))
def test_round_trip_property(values: dict[str, str]) -> None:
    parsed = envfile.parse(envfile.render(values))
    # a value that is only whitespace or starts/ends with a quote character is normalised by the permissive parser; compare stripped
    assert {k: v.strip() for k, v in values.items()} == {k: v.strip() for k, v in parsed.items()}


def test_quote_refuses_what_cannot_be_stored() -> None:
    with pytest.raises(ValueError):
        envfile.quote("it's")
    with pytest.raises(ValueError):
        envfile.quote("a\nb")


def test_merge_adds_missing_keys_never_overwrites_and_reports_differences() -> None:
    existing = {"ZIIRA_SECRET_KEY": "old-secret", "ZIIRA_LOG_LEVEL": "DEBUG"}
    wanted = {"ZIIRA_SECRET_KEY": "new-secret", "ZIIRA_LOG_LEVEL": "INFO", "ZIIRA_NEW": "1"}
    merged, added, differing = envfile.merge(existing, wanted)
    assert merged == {"ZIIRA_SECRET_KEY": "old-secret", "ZIIRA_LOG_LEVEL": "DEBUG", "ZIIRA_NEW": "1"}
    assert added == ["ZIIRA_NEW"] and differing == ["ZIIRA_LOG_LEVEL", "ZIIRA_SECRET_KEY"]
    lines = "\n".join(envfile.diff_lines(existing, wanted, differing))
    assert "old-secret" not in lines and "new-secret" not in lines          # secrets are never printed
    assert "DEBUG" in lines and "INFO" in lines


def test_mask() -> None:
    assert envfile.mask("ZIIRA_SECRET_KEY", "abc") == "[hidden]"
    assert envfile.mask("ZIIRA_X", "postgresql://u:pw@h/db") == "[hidden]"
    assert envfile.mask("ZIIRA_LOG_LEVEL", "INFO") == "INFO"


def test_photos_and_files_have_a_private_folder_in_the_state_directory() -> None:
    env = generated()
    assert env["ZIIRA_FILES_DIR"].endswith("/files") and env["ZIIRA_FILES_DIR"] != env["ZIIRA_BACKUP_DIR"]
    assert env["ZIIRA_FILES_MAX_UPLOAD_BYTES"] == "26500000"
