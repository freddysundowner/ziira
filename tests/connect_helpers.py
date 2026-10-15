"""Shared setup for the standalone-mode tests: a business with the Connectors, Intelligence and Command units, fake
in-memory connectors registered for the test run, and helpers to plant canonical records the way a connector would."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from tests.conftest import LOCALE, make_tenant, sign_in
from tests.stock_helpers import system
from ziira.kernel import extensions
from ziira.modules.connect.public import (
    CONNECTOR,
    CanonicalBatch,
    ConfigField,
    ConnectionCheck,
    Connector,
)
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.repository import store
from ziira.modules.connect.services.branches import BranchResolver

CONNECT = "/api/v1/connect"
ZONE = ZoneInfo(LOCALE["timezone"])
TODAY = date(2026, 10, 14)


def at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    """A moment on a day in the business's time zone (a fixture value, never logic)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


class FakeErp(Connector):
    """An in-memory system. `SCRIPT[entity]` is a list of pages; a page is a CanonicalBatch or an exception to raise."""

    kind = "fake_erp"
    title = "Fake ERP"
    description = "For tests"
    entities = ("branches", "sales", "payments", "users")
    config_fields = (ConfigField("url", "Address", example="https://erp.example"),
                     ConfigField("api_key", "API key", secret=True))
    freshness = "daily"
    how_to = "Create a read-only API key."
    SCRIPT: dict[str, list[Any]] = {}
    CALLS: list[tuple[str, str | None]] = []
    CHECK_OK = True
    ROTATE: dict[str, Any] | None = None
    NOTES: list[str] = []

    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        if not self.CHECK_OK or secrets.get("api_key") != "key-1":
            return ConnectionCheck(ok=False, message="The key was refused")
        return ConnectionCheck(ok=True, message="Connected", details={"system": "Fake 1.0"})

    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        self.CALLS.append((entity, since))
        self.notes = list(self.NOTES)
        self.updated_secrets = dict(self.ROTATE) if self.ROTATE else None
        for page in self.SCRIPT.get(entity, []):
            if isinstance(page, Exception):
                raise page
            yield page


class FakeLive(FakeErp):
    kind = "fake_live"
    title = "Fake live system"
    freshness = "live"


def register_fakes() -> Callable[[], None]:
    """Plug the fake connectors in; returns the function that removes them again."""
    import ziira.modules.connect.hooks  # noqa: F401 - defines the socket

    point = extensions._points[CONNECTOR]
    added = [FakeErp, FakeLive]
    for impl in added:
        extensions._add_implementation(point, "connect", impl)

    def undo() -> None:
        for impl in added:
            point.implementations.remove(("connect", impl))

    return undo


def make_connect_shop(client, registry, name: str, units: tuple[str, ...] = ("connect", "intel", "command", "imports")):  # type: ignore[no-untyped-def]
    """A standalone-style business: only the Connectors, Intelligence, Command Center and Import units, an owner who can
    sign in, a second branch (JUJA), and a view-only accountant and a cashier without access to connections."""
    code = name.lower().replace(" ", "-")
    t = make_tenant(name)
    for unit in units:
        registry.enable(t["tenant_id"], unit)
    juja = uuid4()
    with system(t) as s:
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, 'JUJA', 'Juja')"),
                  {"i": str(juja), "t": str(t["tenant_id"]), "c": str(t["company_id"])})
    owner = sign_in(client, code, f"owner@{code}.test").headers
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}

    def user(user_name: str, role: str) -> dict[str, str]:
        email = f"{user_name}@{code}.test"
        u = client.post("/api/v1/users", headers=owner,
                        json={"full_name": user_name, "email": email, "password": f"{user_name}-pass-1"}).json()
        r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={
            "role_id": roles[role], "scope": "company", "company_id": str(t["company_id"]), "branch_id": None})
        assert r.status_code == 201, r.text
        return sign_in(client, code, email, f"{user_name}-pass-1").headers

    shop = {**t, "code": code, "owner": owner, "juja": juja, "roles": roles}
    shop["accountant"] = user("accountant", "Accountant")
    shop["cashier"] = user("cashier", "Cashier") if "Cashier" in roles else {}
    return shop


def new_connection(client, shop, kind: str = "fake_erp", name: str = "Main ERP", **extra: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    body: dict[str, Any] = {"company_id": str(shop["company_id"]), "kind": kind, "name": name}
    if kind.startswith("fake"):
        body["config"] = {"url": "https://erp.example", "api_key": "key-1"}
    body.update(extra)
    r = client.post(f"{CONNECT}/connections", headers=shop["owner"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def target_for(session, connection_id: UUID, company_id: UUID, auto: bool = False) -> store.Target:  # type: ignore[no-untyped-def]
    resolver = BranchResolver(session, connection_id, company_id, auto)
    return store.Target(connection_id, company_id, resolver.resolve)


class Planter:
    """Plants canonical records for a test the way a connector would, through the real storing path, and marks the
    entities as read (so the checks see them as connected)."""

    def __init__(self, shop: dict[str, Any], connection_id: UUID, through: datetime | None = None) -> None:
        self.shop, self.connection_id = shop, connection_id
        self.through = through or at(TODAY + timedelta(days=1), 0)
        with system(shop) as s:                      # the source's branch codes HQ and JUJA are this business's branches
            for ref, name, branch in (("HQ", "Head office", shop["branch_id"]), ("JUJA", "Juja", shop["juja"])):
                repo.add_branch_map(s, connection_id, ref, name, None)
                repo.set_branch_map(s, connection_id, ref, branch, False)

    def put(self, entity: str, records: list[Any], *, mark: bool = True) -> store.Counts:
        with system(self.shop) as s:
            counts = store.store_records(s, target_for(s, self.connection_id, self.shop["company_id"]), entity, records)
            if mark:
                repo.set_cursor(s, self.connection_id, entity, None, self.through)
        return counts

    def mark(self, *entities: str, through: datetime | None = None) -> None:
        with system(self.shop) as s:
            for entity in entities:
                repo.set_cursor(s, self.connection_id, entity, None, through or self.through)


def db_connection(client, shop, kind: str = "csv_sales", name: str = "Planted") -> UUID:  # type: ignore[no-untyped-def]
    """A connection row to hang planted records on (a file kind: nothing is ever pulled from it)."""
    return UUID(new_connection(client, shop, kind, name)["id"])


def scalar(shop: dict[str, Any], sql: str, **params: Any) -> Any:
    with system(shop) as s:
        return s.execute(text(sql), params).scalar_one()


def rows(shop: dict[str, Any], sql: str, **params: Any) -> list[Any]:
    with system(shop) as s:
        return list(s.execute(text(sql), params))


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


__all__ = ["Decimal", "timedelta"]
