"""Testing kit for plugin and module authors (docs/writing-a-plugin.md, "Testing").

Import it only from tests. A plugin's `tests/conftest.py` is one line:

    from ziira.sdk.testing import *  # noqa: F401,F403  (fixtures: registry, client)

and a test reads like this:

    def test_items(client, registry):
        shop = make_tenant("Shop One", units=["my_plugin"])
        owner = sign_in(client, shop)
        assert client.post("/api/v1/plugins/my-plugin/items", headers=owner.headers, json={...}).status_code == 201

    def test_guarded(client, registry):
        assert_all_routes_guarded(client.app, "/api/v1/plugins/my-plugin", client=client)

What is here:

- `registry`, `client` (pytest fixtures): throw-away databases (`ziira_test_*`, dropped afterwards) with every unit
  installed, and an API client. Tests queue on a file lock, so several runs never clash.
- `make_tenant(name, units)`, `sign_in(client, tenant)`, `user_with_role(...)`: a business with its owner, and
  people signed in as a role (real sign-in, never the development header).
- `run_outbox_once()`, `run_jobs_once()`: deliver events to `@subscribe_after` handlers and run due background jobs.
- `freeze_company_date(day)`: what `company_today` answers while the block runs.
- `fake_http(handler)`: an HTTP transport that never touches the network, for provider plugins.
- `assert_all_routes_guarded(app, prefix, client=...)` and `assert_tenant_isolation(...)`: the permission and
  isolation checks every plugin should pass.
"""

import contextlib
import fcntl
import io
import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

__all__ = [
    "ADMIN_URL",
    "OWNER_PASSWORD",
    "FakeHttp",
    "Signed",
    "Tenant",
    "assert_all_routes_guarded",
    "assert_tenant_isolation",
    "client",
    "fake_http",
    "freeze_company_date",
    "make_tenant",
    "registry",
    "run_jobs_once",
    "run_outbox_once",
    "sign_in",
    "user_with_role",
]

ADMIN_URL = make_url(os.environ.get("ZIIRA_TEST_ADMIN_URL", "postgresql+psycopg://ziira:ziira@localhost:5432/postgres"))
MASTER_DB, TEMPLATE_DB = "ziira_test_master", "ziira_test_template"
TENANT_DB_PREFIX, TENANT_ROLE_PREFIX = "ziira_test_t_", "ztest_"
OWNER_PASSWORD = "owner-pass-123"  # every test business's owner signs in with this
_registry: Any = None  # the Registry of this test run, for make_tenant


def _ensure_extra_package() -> None:
    """Plugins from ZIIRA_EXTRA_UNIT_PATHS import as `ziira_ext.<name>`: make that importable before tests import it."""
    from ziira.kernel import plugin_trust
    from ziira.kernel.config import get_settings

    roots = get_settings().extra_unit_path_list()
    if roots:
        plugin_trust.extra_package(roots)


_ensure_extra_package()


# --------------------------------------------------------------------------- the test platform
def _drop_test_databases() -> None:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        old = (
            c.execute(
                text("select datname from pg_database where datname like :p or datname in (:m, :t)"),
                {"p": TENANT_DB_PREFIX + "%", "m": MASTER_DB, "t": TEMPLATE_DB},
            )
            .scalars()
            .all()
        )
        for db in old:
            c.execute(text(f'drop database "{db}" with (force)'))
        for role in (
            c.execute(text("select rolname from pg_roles where rolname like :p"), {"p": TENANT_ROLE_PREFIX + "%"})
            .scalars()
            .all()
        ):
            c.execute(text(f'drop role "{role}"'))
    engine.dispose()


@contextlib.contextmanager
def _one_test_session_at_a_time() -> Iterator[None]:
    """The test databases have fixed names, so two test sessions on one server wait for each other here."""
    path = os.path.join(tempfile.gettempdir(), "ziira-test-database.lock")
    with open(path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@pytest.fixture(scope="session")
def registry() -> Iterator[Any]:
    """A fresh platform with every discovered unit installed (extra plugin folders come from ZIIRA_EXTRA_UNIT_PATHS)."""
    global _registry
    if os.environ.get("ZIIRA_TEST_PLATFORM") == "1":  # another fixture in this run already set the platform up
        from ziira.kernel.registry import Registry

        _registry = Registry()
        yield _registry
        _registry = None
        return
    with _one_test_session_at_a_time():
        _drop_test_databases()
        engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as c:
            c.execute(text(f"create database {MASTER_DB}"))
        engine.dispose()
        os.environ.update(
            {
                "ZIIRA_MASTER_DATABASE_URL": ADMIN_URL.set(database=MASTER_DB).render_as_string(hide_password=False),
                "ZIIRA_TENANT_SERVER_URL": ADMIN_URL.render_as_string(hide_password=False),
                "ZIIRA_TEMPLATE_DATABASE": TEMPLATE_DB,
                "ZIIRA_TENANT_DB_PREFIX": TENANT_DB_PREFIX,
                "ZIIRA_TENANT_ROLE_PREFIX": TENANT_ROLE_PREFIX,
                "ZIIRA_TEST_PLATFORM": "1",
            }
        )
        from ziira.kernel.config import get_settings
        from ziira.kernel.db import forget_all
        from ziira.kernel.registry import Registry

        get_settings.cache_clear()
        forget_all()
        reg = Registry()
        reg.install_all()
        _registry = reg
        yield reg
        _registry = None
        os.environ.pop("ZIIRA_TEST_PLATFORM", None)
        forget_all()
        _drop_test_databases()


@pytest.fixture(scope="session")
def client(registry: Any) -> Any:
    """An API client for the whole application."""
    from fastapi.testclient import TestClient

    from ziira.kernel.app import create_app

    return TestClient(create_app())


# --------------------------------------------------------------------------- businesses and people
@dataclass(frozen=True)
class Tenant:
    """A test business: its ids and the owner's login."""

    code: str
    tenant_id: UUID
    company_id: UUID
    branch_id: UUID
    owner_id: UUID
    owner_login: str


@dataclass
class Signed:
    """Someone signed in: use `headers` on requests."""

    headers: dict[str, str]
    refresh_token: str
    session_id: str
    user_id: str


def make_tenant(name: str, units: list[str] | tuple[str, ...] = ()) -> Tenant:
    """Create a business (one company, one branch, an owner) and switch on `units` (what they require comes along).
    The workspace code is the name in lower case with '-' for spaces; the owner is owner@<code>.test."""
    from ziira.kernel import cli

    if _registry is None:
        raise RuntimeError("make_tenant needs the `registry` fixture (use it in the test's arguments)")
    code = name.lower().replace(" ", "-")
    os.environ["ZIIRA_OWNER_PASSWORD"] = OWNER_PASSWORD
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert (
            cli.main(
                [
                    "create-tenant",
                    name,
                    "--code",
                    code,
                    "--company",
                    f"{name} Ltd",
                    "--branch-code",
                    "HQ",
                    "--branch-name",
                    "Head office",
                    "--currency",
                    "USD",
                    "--phone-country-code",
                    "44",
                    "--timezone",
                    "UTC",
                    "--owner-name",
                    f"{name} Owner",
                    "--owner-email",
                    f"owner@{code}.test",
                ]
            )
            == 0
        )
    ids = {k.strip(): UUID(v.strip()) for k, v in (line.split(" = ") for line in out.getvalue().strip().splitlines())}
    for unit in units:
        _registry.enable(ids["tenant_id"], unit)
    return Tenant(code, ids["tenant_id"], ids["company_id"], ids["branch_id"], ids["owner_id"], f"owner@{code}.test")


def sign_in(client: Any, tenant: Tenant, login: str | None = None, password: str = OWNER_PASSWORD) -> Signed:
    """Sign in through the API (the owner by default)."""
    r = client.post(
        "/api/v1/auth/sign-in",
        json={
            "workspace": tenant.code,
            "login": login or tenant.owner_login,
            "password": password,
            "device_id": f"test-{uuid4().hex[:8]}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return Signed(
        {"Authorization": f"Bearer {body['access_token']}"}, body["refresh_token"], body["session_id"], body["user_id"]
    )


def user_with_role(
    client: Any, tenant: Tenant, role: str | None = None, *, permissions: list[str] | None = None
) -> Signed:
    """Someone signed in with a role of the business: a default one by name ("Cashier", "Branch Manager", ...), or
    with `permissions` a new role that holds exactly those (an empty list: a person who may do nothing)."""
    owner = sign_in(client, tenant)
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner.headers).json()}
    if permissions is not None:
        made = client.post(
            "/api/v1/roles", headers=owner.headers, json={"name": f"test-{uuid4().hex[:8]}", "permissions": permissions}
        )
        assert made.status_code == 201, made.text
        role_id = made.json()["id"]
    else:
        role_id = roles[role or "Cashier"]
    email, password = f"user-{uuid4().hex[:8]}@{tenant.code}.test", f"user-pass-{uuid4().hex[:6]}"
    person = client.post(
        "/api/v1/users", headers=owner.headers, json={"full_name": "Test person", "email": email, "password": password}
    )
    assert person.status_code == 201, person.text
    given = client.post(
        f"/api/v1/users/{person.json()['id']}/roles",
        headers=owner.headers,
        json={"role_id": role_id, "scope": "company", "company_id": str(tenant.company_id)},
    )
    assert given.status_code in (200, 201), given.text
    return sign_in(client, tenant, email, password)


# --------------------------------------------------------------------------- background work and time
def run_outbox_once() -> int:
    """Deliver committed events to `@subscribe_after` handlers once, for every business. Returns how many."""
    from ziira.kernel import outbox

    return outbox.process_all()


def run_jobs_once() -> int:
    """Run the background jobs that are due, once, for every business. Returns how many finished."""
    from ziira.kernel import jobs

    return jobs.run_all()


@contextlib.contextmanager
def freeze_company_date(day: date) -> Iterator[None]:
    """For the length of the block `company_today(...)` answers `day`, whatever the clock says."""
    import ziira.kernel.clock
    import ziira.sdk

    def frozen(*_: Any, **__: Any) -> date:
        return day

    with (
        mock.patch.object(ziira.kernel.clock, "company_today", frozen),
        mock.patch.object(ziira.sdk, "company_today", frozen),
    ):
        yield


# --------------------------------------------------------------------------- pretend HTTP services
@dataclass
class FakeHttp:
    """A transport that answers from a function and remembers every request (no network is ever used)."""

    handler: Callable[[httpx.Request], httpx.Response]
    requests: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        def answer(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.handler(request)

        return httpx.MockTransport(answer)

    def client(self, **kwargs: Any) -> httpx.Client:
        """An `httpx.Client` wired to the fake, for code that takes a client."""
        return httpx.Client(transport=self.transport(), **kwargs)


def fake_http(handler: Callable[[httpx.Request], httpx.Response] | int = 200, *, json: Any = None) -> FakeHttp:
    """A pretend web service: pass `(request) -> httpx.Response`, or a status code (and a `json=` body)."""
    if callable(handler):
        return FakeHttp(handler)
    status = handler
    return FakeHttp(lambda request: httpx.Response(status, json=json if json is not None else {}))


# --------------------------------------------------------------------------- the checks every plugin should pass
def _operations(app: Any, prefix: str) -> list[tuple[str, str]]:
    found = []
    for path, operations in app.openapi().get("paths", {}).items():
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            found += [
                (method.upper(), path)
                for method in operations
                if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE")
            ]
    return found


def assert_all_routes_guarded(app: Any, prefix: str, *, client: Any = None, tenant: Tenant | None = None) -> int:
    """Every endpoint under `prefix` refuses a caller who is not signed in (401); with `tenant` it also refuses a
    signed-in person who holds no permissions (403). Calls the endpoints with junk, so none may do anything before
    the check. Returns how many endpoints were checked; fails if there are none."""
    from fastapi.testclient import TestClient

    http = client or TestClient(app)
    operations = _operations(app, prefix)
    assert operations, f"No endpoints under {prefix}: is the plugin installed and its API prefix right?"
    nobody = user_with_role(http, tenant, permissions=[]) if tenant else None
    for method, path in operations:
        url = path
        for part in [p for p in path.split("/") if p.startswith("{")]:
            url = url.replace(part, str(uuid4()))
        sent = http.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert sent.status_code == 401, f"{method} {path} answered {sent.status_code} to a caller who is not signed in"
        if nobody is not None:
            sent = http.request(
                method, url, headers=nobody.headers, json={} if method in ("POST", "PUT", "PATCH") else None
            )
            assert sent.status_code == 403, (
                f"{method} {path} answered {sent.status_code} to a signed-in person "
                "with no permissions: add require_permission(...)"
            )
    return len(operations)


def assert_tenant_isolation(
    client: Any, other_owner: Signed, record_path: str, *, list_path: str | None = None, record_id: str | None = None
) -> None:
    """A record of one business is invisible to another's owner: reading it by id gives 404 (or 403), and, with
    `list_path` and `record_id`, the other business's list does not contain it."""
    seen = client.get(record_path, headers=other_owner.headers)
    assert seen.status_code in (403, 404), f"GET {record_path} answered {seen.status_code} to another business's owner"
    if list_path and record_id:
        listed = client.get(list_path, headers=other_owner.headers)
        assert listed.status_code == 200, listed.text
        assert record_id not in listed.text, f"{list_path} shows another business's record"
