"""Test setup: a fresh master database and template, all units installed, two tenants.

Every tenant gets its own database (ziira_test_t_<code>) and login (ztest_<code>), as in
production. All test databases and logins are dropped when the run ends (and before it starts,
in case an earlier run was interrupted).

Point the tests at your server with ZIIRA_TEST_ADMIN_URL (a superuser URL for any existing
database, e.g. the `postgres` database). Default matches docker-compose.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = make_url(os.environ.get(
    "ZIIRA_TEST_ADMIN_URL", "postgresql+psycopg://ziira:ziira@localhost:5432/postgres"))
MASTER_DB, TEMPLATE_DB = "ziira_test_master", "ziira_test_template"
TENANT_DB_PREFIX, TENANT_ROLE_PREFIX = "ziira_test_t_", "ztest_"
OWNER_PASSWORD = "owner-pass-123"   # test-only password for every tenant's owner
LOCALE = {"currency": "KES", "phone_country_code": "254"}   # what make_tenant creates (a test may change it for a while)


def _drop_test_databases() -> None:
    """Drop every test database and test login on the server."""
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        old = c.execute(text("select datname from pg_database where datname like :p or datname in (:m, :t)"),
                        {"p": TENANT_DB_PREFIX + "%", "m": MASTER_DB, "t": TEMPLATE_DB}).scalars().all()
        for db in old:
            c.execute(text(f'drop database "{db}" with (force)'))
        for role in c.execute(text("select rolname from pg_roles where rolname like :p"),
                              {"p": TENANT_ROLE_PREFIX + "%"}).scalars().all():
            c.execute(text(f'drop role "{role}"'))
    engine.dispose()


def _prepare_server() -> None:
    """Start clean, create an empty master database, and point the settings at the test names."""
    _drop_test_databases()
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        c.execute(text(f"create database {MASTER_DB}"))
    engine.dispose()
    os.environ.update({
        "ZIIRA_MASTER_DATABASE_URL": ADMIN_URL.set(database=MASTER_DB).render_as_string(hide_password=False),
        "ZIIRA_TENANT_SERVER_URL": ADMIN_URL.render_as_string(hide_password=False),
        "ZIIRA_TEMPLATE_DATABASE": TEMPLATE_DB,
        "ZIIRA_TENANT_DB_PREFIX": TENANT_DB_PREFIX,
        "ZIIRA_TENANT_ROLE_PREFIX": TENANT_ROLE_PREFIX,
    })


@contextmanager
def _one_test_session_at_a_time() -> Iterator[None]:
    """The test databases have fixed names, so two pytest sessions on one server would drop each other's databases.
    A session that needs the server waits here until any other one has finished (a file lock, released on exit or
    crash). The wait is visible: pytest simply sits at the first test that needs the database."""
    import fcntl
    import tempfile

    path = os.path.join(tempfile.gettempdir(), "ziira-test-database.lock")
    with open(path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@pytest.fixture(scope="session")
def registry() -> Iterator[object]:
    with _one_test_session_at_a_time():
        yield from _registry()


def _registry() -> Iterator[object]:
    _prepare_server()
    from ziira.kernel.config import get_settings
    from ziira.kernel.db import forget_all
    from ziira.kernel.registry import Registry

    get_settings.cache_clear()
    forget_all()
    reg = Registry()
    reg.install_all()
    yield reg
    forget_all()
    _drop_test_databases()


def make_tenant(name: str) -> dict[str, UUID]:
    """Create a tenant with one company, branch and owner, through the CLI.

    The workspace code is the name in lowercase with '-' for spaces; the owner signs in as
    owner@<code>.test with OWNER_PASSWORD.
    """
    import contextlib
    import io

    from ziira.kernel import cli

    code = name.lower().replace(" ", "-")
    os.environ["ZIIRA_OWNER_PASSWORD"] = OWNER_PASSWORD
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["create-tenant", name, "--code", code, "--company", f"{name} Ltd",
                         "--branch-code", "HQ", "--branch-name", "Head office", "--currency", LOCALE["currency"],
                         "--phone-country-code", LOCALE["phone_country_code"],
                         "--owner-name", f"{name} Owner", "--owner-email", f"owner@{code}.test"]) == 0
    ids = dict(line.split(" = ") for line in out.getvalue().strip().splitlines())
    return {k.strip(): UUID(v.strip()) for k, v in ids.items()}


@pytest.fixture(scope="session")
def tenants(registry: object) -> dict[str, dict[str, UUID]]:
    a, b = make_tenant("Tenant A"), make_tenant("Tenant B")
    registry.enable(a["tenant_id"], "products")        # type: ignore[attr-defined]
    registry.enable(a["tenant_id"], "catalog_stats")   # type: ignore[attr-defined]
    registry.enable(b["tenant_id"], "products")        # type: ignore[attr-defined]
    return {"A": a, "B": b}


@pytest.fixture(scope="session")
def client(registry: object):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from ziira.kernel.app import create_app

    return TestClient(create_app())



@dataclass
class Signed:
    """Result of signing in during a test."""

    headers: dict[str, str]
    refresh_token: str
    session_id: str
    user_id: str


def sign_in(client, workspace: str, login: str, password: str = OWNER_PASSWORD,  # type: ignore[no-untyped-def]
            device_id: str = "test-device") -> Signed:
    """Sign in through the API."""
    r = client.post("/api/v1/auth/sign-in", json={"workspace": workspace, "login": login, "password": password,
                                                  "device_id": device_id})
    assert r.status_code == 200, r.text
    body = r.json()
    return Signed(headers={"Authorization": f"Bearer {body['access_token']}"}, refresh_token=body["refresh_token"],
                  session_id=body["session_id"], user_id=body["user_id"])
