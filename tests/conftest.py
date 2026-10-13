"""Test setup: a fresh database `ziira_test`, all units installed, two tenants.

Point the tests at your server with ZIIRA_TEST_ADMIN_URL (an owner/superuser URL
for any existing database, e.g. the `postgres` database). Default matches docker-compose.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = make_url(os.environ.get(
    "ZIIRA_TEST_ADMIN_URL", "postgresql+psycopg://ziira:ziira@localhost:5432/postgres"))
TEST_DB = "ziira_test"
APP_ROLE, APP_PASSWORD = "ziira_app", "ziira_app"
OWNER_PASSWORD = "owner-pass-123"   # test-only password for every tenant's owner


def _prepare_database() -> None:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        c.execute(text(
            f"do $$ begin if not exists (select from pg_roles where rolname = '{APP_ROLE}') then "
            f"create role {APP_ROLE} login password '{APP_PASSWORD}'; end if; end $$"))
        c.execute(text(f"drop database if exists {TEST_DB} with (force)"))
        c.execute(text(f"create database {TEST_DB}"))
    engine.dispose()
    os.environ["ZIIRA_ADMIN_DATABASE_URL"] = ADMIN_URL.set(database=TEST_DB).render_as_string(
        hide_password=False)
    os.environ["ZIIRA_APP_DATABASE_URL"] = ADMIN_URL.set(
        database=TEST_DB, username=APP_ROLE, password=APP_PASSWORD).render_as_string(hide_password=False)
    os.environ["ZIIRA_APP_DB_ROLE"] = APP_ROLE


@pytest.fixture(scope="session")
def registry() -> Iterator[object]:
    _prepare_database()
    from ziira.kernel.config import get_settings
    from ziira.kernel.db import admin_engine, app_engine
    from ziira.kernel.registry import Registry

    get_settings.cache_clear()
    app_engine.cache_clear()
    admin_engine.cache_clear()
    reg = Registry()
    reg.install_all()
    yield reg
    app_engine().dispose()
    admin_engine().dispose()


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
                         "--branch-code", "HQ", "--branch-name", "Head office",
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
