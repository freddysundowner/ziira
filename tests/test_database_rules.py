"""Rules enforced by PostgreSQL itself, regardless of application code."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

from tests.conftest import make_tenant


@pytest.fixture(scope="module")
def rules_tenant(registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Rules Co")
    registry.enable(t["tenant_id"], "finance")
    registry.enable(t["tenant_id"], "products")
    return t


def _seed_finance(s, tenant: dict) -> dict[str, str]:  # type: ignore[no-untyped-def,type-arg]
    t, c = str(tenant["tenant_id"]), str(tenant["company_id"])
    acc = s.execute(text(
        "insert into finance.account (tenant_id, company_id, code, name, type) values "
        "(:t, :c, '1010', 'Till cash', 'asset'), (:t, :c, '4000', 'Sales', 'income') returning id"),
        {"t": t, "c": c}).scalars().all()
    j = s.execute(text("insert into finance.journal (tenant_id, company_id, code, name) "
                       "values (:t, :c, 'SAL', 'Sales') returning id"), {"t": t, "c": c}).scalar()
    p = s.execute(text("insert into finance.period (tenant_id, company_id, start_date, end_date) "
                       "values (:t, :c, '2026-10-01', '2026-10-31') returning id"), {"t": t, "c": c}).scalar()
    return {"t": t, "c": c, "cash": str(acc[0]), "sales": str(acc[1]), "j": str(j), "p": str(p)}


def test_unbalanced_journal_rejected_and_balanced_accepted(rules_tenant) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    a = rules_tenant
    with tenant_session(a["tenant_id"]) as s:
        ids = _seed_finance(s, a)

    def post(number: str, lines: list[tuple[str, int, int]]) -> None:
        with tenant_session(a["tenant_id"]) as s:
            e = s.execute(text(
                "insert into finance.journal_entry (tenant_id, company_id, journal_id, period_id, number, "
                "entry_date) values (:t, :c, :j, :p, :n, '2026-10-08') returning id"),
                {**ids, "n": number}).scalar()
            for account, debit, credit in lines:
                s.execute(text(
                    "insert into finance.journal_line (tenant_id, entry_id, company_id, account_id, debit, "
                    "credit) values (:t, :e, :c, :acc, :d, :cr)"),
                    {**ids, "e": str(e), "acc": account, "d": debit, "cr": credit})

    post("JE-1", [(ids["cash"], 1000, 0), (ids["sales"], 0, 1000)])
    with pytest.raises(DBAPIError, match="not balanced"):
        post("JE-2", [(ids["cash"], 500, 0)])


def test_posted_records_are_immutable(rules_tenant) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    a = rules_tenant
    with pytest.raises(DBAPIError, match="immutable"), tenant_session(a["tenant_id"]) as s:
        s.execute(text("update finance.journal_line set debit = debit"))
    from ziira.kernel import audit
    from ziira.kernel.context import RequestContext, set_context

    set_context(RequestContext(tenant_id=a["tenant_id"], channel="system"))
    with tenant_session(a["tenant_id"]) as s:
        audit.record(s, "test", "test.entity", None)
    with pytest.raises(DBAPIError, match="immutable"), tenant_session(a["tenant_id"]) as s:
        s.execute(text("delete from kernel.audit_log"))


def test_tenant_cannot_write_another_tenant_id(rules_tenant, tenants) -> None:  # type: ignore[no-untyped-def]
    """Second layer: inside a tenant database, row-level security still refuses other tenant ids."""
    from ziira.kernel.db import tenant_session

    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(rules_tenant["tenant_id"]) as s:
        s.execute(text("insert into products.uom (tenant_id, code, name) values (:t, 'X', 'x')"),
                  {"t": str(tenants["A"]["tenant_id"])})


def test_each_tenant_has_its_own_database_and_login(rules_tenant, tenants) -> None:  # type: ignore[no-untyped-def]
    """First layer: a tenant's login cannot even connect to another tenant's database."""
    from sqlalchemy import make_url

    from ziira.kernel.db import master_session, tenant_engine
    from ziira.kernel.security import decrypt

    with master_session() as s:
        rows = {r.id: r for r in s.execute(text(
            "select id, db_name, app_role, app_url_encrypted from master.tenant"))}
    mine, theirs = rows[rules_tenant["tenant_id"]], rows[tenants["A"]["tenant_id"]]
    assert mine.db_name != theirs.db_name and mine.app_role != theirs.app_role
    # Credentials are stored encrypted, never in plain text
    assert "postgresql" not in mine.app_url_encrypted and mine.app_role not in mine.app_url_encrypted
    my_url = make_url(decrypt(mine.app_url_encrypted))
    assert my_url.username == mine.app_role and my_url.database == mine.db_name
    # My login, pointed at their database, is refused by PostgreSQL
    engine = create_engine(my_url.set(database=theirs.db_name))
    with pytest.raises(OperationalError, match="permission denied"), engine.connect():
        pass
    engine.dispose()
    # The tenant database holds exactly one tenant
    with tenant_engine(rules_tenant["tenant_id"], admin=True).connect() as conn:
        assert conn.execute(text("select id from kernel.tenant")).scalars().all() == [rules_tenant["tenant_id"]]


def _exists(db: str, role: str) -> tuple[bool, bool]:
    from ziira.kernel.db import server_engine

    with server_engine().connect() as conn:
        return (conn.execute(text("select 1 from pg_database where datname = :d"), {"d": db}).first() is not None,
                conn.execute(text("select 1 from pg_roles where rolname = :r"), {"r": role}).first() is not None)


def test_failed_provisioning_leaves_nothing_behind(registry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import tenants
    from ziira.kernel.db import master_session

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    monkeypatch.setattr(tenants, "_set_up_business", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        make_tenant("Half Co")
    assert _exists("ziira_test_t_half_co", "ztest_half_co") == (False, False)
    with master_session() as s:
        assert s.execute(text("select count(*) from master.tenant where code = 'half-co'")).scalar() == 0


def test_drop_tenant_removes_database_login_and_record(registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import master_session
    from ziira.kernel.tenants import drop_tenant

    t = make_tenant("Leaving Co")
    assert _exists("ziira_test_t_leaving_co", "ztest_leaving_co") == (True, True)
    drop_tenant(t["tenant_id"])
    assert _exists("ziira_test_t_leaving_co", "ztest_leaving_co") == (False, False)
    with master_session() as s:
        assert s.execute(text("select count(*) from master.tenant where code = 'leaving-co'")).scalar() == 0


def test_suspended_tenant_is_locked_out(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import sign_in
    from ziira.kernel.db import forget_tenant, master_session

    t = make_tenant("Paused Co")
    signed = sign_in(client, "paused-co", "owner@paused-co.test")
    with master_session() as s:
        s.execute(text("update master.tenant set status = 'suspended' where id = :i"), {"i": str(t["tenant_id"])})
    forget_tenant(t["tenant_id"])
    assert client.get("/api/v1/auth/me", headers=signed.headers).status_code == 401
    r = client.post("/api/v1/auth/sign-in", json={"workspace": "paused-co", "login": "owner@paused-co.test",
                                                  "password": "owner-pass-123", "device_id": "d"})
    assert r.status_code == 401
