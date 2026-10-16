"""Inputs: flags, answers file, defaults and validation."""
from __future__ import annotations

import pytest

from installer import config, util


def load(*argv: str, environ: dict[str, str] | None = None, text: str | None = None) -> config.Config:
    cfg, _ = config.load(list(argv), environ or {}, text)
    cfg.resolve_defaults()
    return cfg


GOOD = ("--root-domain", "ziira.io", "--email", "ops@ziira.io", "--admin-email", "me@ziira.io", "--registration-mode", "closed")


def test_hosts_default_from_the_root_domain() -> None:
    cfg = load(*GOOD)
    assert (cfg.app_host, cfg.admin_host) == ("app.ziira.io", "admin.ziira.io")
    assert cfg.hosts() == ["ziira.io", "www.ziira.io", "app.ziira.io", "admin.ziira.io"]
    assert cfg.validate() == []


def test_custom_hosts_and_no_www() -> None:
    cfg = load(*GOOD, "--app-host", "erp.example.com", "--admin-host", "staff.example.com", "--no-www")
    assert cfg.hosts() == ["ziira.io", "erp.example.com", "staff.example.com"]


def test_nothing_is_hard_coded_to_one_domain() -> None:
    cfg = load("--root-domain", "Example.ORG.", "--email", "a@b.co", "--admin-email", "c@d.co", "--registration-mode", "closed")
    assert cfg.root_domain == "example.org" and cfg.app_host == "app.example.org"


def test_cert_lineages() -> None:
    assert load(*GOOD).lineages() == {"ziira-ziira.io": ["ziira.io", "www.ziira.io"], "ziira-app.ziira.io": ["app.ziira.io"],
                                      "ziira-admin.ziira.io": ["admin.ziira.io"]}
    single = load(*GOOD, "--cert-mode", "single").lineages()
    assert list(single) == ["ziira-ziira.io"] and len(single["ziira-ziira.io"]) == 4
    assert load(*GOOD).lineage_of("www.ziira.io") == "ziira-ziira.io"       # always ziira-<host>: never an existing lineage


def test_registration_is_closed_by_default_even_with_a_mailer() -> None:
    assert load("--root-domain", "ziira.io").registration_mode == "closed"
    assert load("--root-domain", "ziira.io", "--smtp-host", "smtp.example.com").registration_mode == "closed"
    assert load("--root-domain", "ziira.io", "--registration-mode", "invite").registration_mode == "invite"    # advanced flag still works


def test_staging_and_self_signed_switch_hsts_off() -> None:
    assert load(*GOOD, "--staging").hsts == "off" and load(*GOOD, "--self-signed").hsts == "off"
    assert load(*GOOD).hsts == "on"


@pytest.mark.parametrize("args,needle", [
    (("--root-domain", "nodot", "--email", "a@b.co", "--admin-email", "c@d.co"), "root domain"),
    (("--root-domain", "ziira.io", "--email", "bad", "--admin-email", "c@d.co"), "contact email"),
    (("--root-domain", "ziira.io", "--email", "a@b.co", "--admin-email", "bad"), "super admin"),
    (("--root-domain", "ziira.io", "--app-host", "ziira.io", "--email", "a@b.co", "--admin-email", "c@d.co"), "three different"),
    (("--root-domain", "ziira.io", "--email", "a@b.co", "--admin-email", "c@d.co", "--operator-networks", "nonsense"), "network"),
    (("--root-domain", "ziira.io", "--email", "a@b.co", "--admin-email", "c@d.co", "--install-dir", "relative"), "absolute"),
    (("--root-domain", "ziira.io", "--email", "a@b.co", "--admin-email", "c@d.co", "--db-prefix", "Bad-Prefix"), "db-prefix"),
    (("--root-domain", "ziira.io", "--email", "a@b.co", "--admin-email", "c@d.co", "--repo", "x", "--from-dir", "/y"), "only one"),
])
def test_validation_names_the_problem(args: tuple[str, ...], needle: str) -> None:
    cfg = load(*args, "--registration-mode", "closed")
    assert any(needle in p for p in cfg.validate()), cfg.validate()


def test_open_registration_needs_a_mailer() -> None:
    cfg = load(*GOOD[:-2], "--registration-mode", "open")
    assert any("verification email" in p for p in cfg.validate())


def test_smtp_secrets_that_cannot_be_stored_are_refused() -> None:
    cfg = load(*GOOD[:-2], "--smtp-host", "smtp.x.io", "--smtp-from", "n@x.io", environ={"ZIIRA_INSTALL_SMTP_PASSWORD": "it's"})
    assert any("quotes" in p for p in cfg.validate())


def test_answers_file_and_flags_precedence() -> None:
    text = ("# comment\nroot_domain = ziira.io\nemail=ops@ziira.io\nadmin_email=me@ziira.io\nregistration_mode=closed\n"
            "www=false\nstaging=true\n")
    cfg = load(text=text)
    assert cfg.root_domain == "ziira.io" and cfg.www is False and cfg.staging is True
    assert load("--root-domain", "other.io", text=text).root_domain == "other.io"      # flags win
    json_cfg = load(text='{"root-domain": "ziira.io", "email": "o@z.io", "admin-email": "m@z.io", "no_services": true}')
    assert json_cfg.no_services is True


def test_answers_file_rejects_unknown_names_and_ignores_secrets() -> None:
    with pytest.raises(SystemExit):
        load(text="root_domian=ziira.io")
    cfg = load(*GOOD, text="admin_password=secret123456789\n")
    assert cfg.admin_password == ""             # passwords come from the environment only


def test_passwords_come_from_the_environment_and_never_into_the_state() -> None:
    cfg = load(*GOOD, environ={"ZIIRA_OPERATOR_PASSWORD": "a-long-passphrase", "ZIIRA_INSTALL_SMTP_PASSWORD": "mailpass"})
    assert cfg.admin_password == "a-long-passphrase"
    public = cfg.public_dict()
    assert "admin_password" not in public and "smtp_password" not in public
    assert "a-long-passphrase" not in str(public)


def test_util_helpers() -> None:
    assert util.parse_cidrs("203.0.113.0/24, 2001:db8::/32") == ["203.0.113.0/24", "2001:db8::/32"]
    assert util.parse_size_mb("2G") == 2048 and util.parse_size_mb("512M") == 512
    assert util.sql_literal("a'b") == "'a''b'"
    with pytest.raises(ValueError):
        util.sql_ident('x"; drop')
    assert util.database_url("ziira", "p@ss/w:rd", "127.0.0.1", 5432, "ziira_master") == \
        "postgresql+psycopg://ziira:p%40ss%2Fw%3Ard@127.0.0.1:5432/ziira_master"
