"""Rules enforced by PostgreSQL itself, regardless of application code."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


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


def test_unbalanced_journal_rejected_and_balanced_accepted(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    a = tenants["A"]
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


def test_posted_records_are_immutable(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    a = tenants["A"]
    with pytest.raises(DBAPIError, match="immutable"), tenant_session(a["tenant_id"]) as s:
        s.execute(text("update finance.journal_line set debit = debit"))
    from ziira.kernel import audit
    from ziira.kernel.context import RequestContext, set_context

    set_context(RequestContext(tenant_id=a["tenant_id"], channel="system"))
    with tenant_session(a["tenant_id"]) as s:
        audit.record(s, "test", "test.entity", None)
    with pytest.raises(DBAPIError, match="immutable"), tenant_session(a["tenant_id"]) as s:
        s.execute(text("delete from kernel.audit_log"))


def test_tenant_cannot_write_into_another_tenant(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(tenants["B"]["tenant_id"]) as s:
        s.execute(text("insert into products.uom (tenant_id, code, name) values (:t, 'X', 'x')"),
                  {"t": str(tenants["A"]["tenant_id"])})
