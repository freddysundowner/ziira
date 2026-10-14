"""Guards for the indexes the hot paths rely on (docs/performance.md), and a plan check on a modest dataset.

If one of these fails, a migration dropped an index a report, list or posting needs: restore it (new numbered
migration), do not just edit this list.
"""

import json

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant

# schema.table -> indexes that must exist (by name)
REQUIRED = {
    "finance.journal_line": {"journal_line_ix2", "journal_line_ix4", "journal_line_ix5"},
    "finance.journal_entry": {"journal_entry_ix1", "journal_entry_ix2"},
    "inventory.stock_movement": {"stock_movement_ix1", "stock_movement_ix3", "stock_movement_ix4",
                                 "stock_movement_ix5", "stock_movement_ix6"},
    "pos.sale": {"sale_ix1", "sale_ix4", "sale_ix5", "sale_ix6"},
    "pos.sale_payment": {"sale_payment_ix1"},
    "pos.sale_line": {"sale_line_ix1"},
    "payments.payment_allocation": {"payment_allocation_ix2"},
    "purchasing.supplier_bill_line": {"supplier_bill_line_ix1", "supplier_bill_line_ix2"},
    "purchasing.supplier_bill": {"supplier_bill_ix3"},
    "people.payslip_line": {"payslip_line_ix1"},
    "intel.finding": {"finding_ux_fingerprint"},
}


@pytest.fixture(scope="module")
def perf_tenant(registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Perf Index Co")
    for unit in ("products", "inventory", "payments", "pos", "finance", "purchasing", "people", "intel"):
        registry.enable(t["tenant_id"], unit)
    return t


def _indexes(tenant) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    system_context(tenant["tenant_id"])
    with tenant_session(tenant["tenant_id"]) as s:
        rows = s.execute(text("select schemaname || '.' || tablename as tbl, indexname from pg_indexes "
                              "where schemaname not in ('pg_catalog', 'information_schema')")).all()
    found: dict[str, set[str]] = {}
    for r in rows:
        found.setdefault(r.tbl, set()).add(r.indexname)
    return found


def test_the_indexes_the_hot_paths_need_exist(perf_tenant) -> None:  # type: ignore[no-untyped-def]
    found = _indexes(perf_tenant)
    missing = {table: sorted(names - found.get(table, set())) for table, names in REQUIRED.items()
               if names - found.get(table, set())}
    assert not missing, f"missing indexes: {missing}"


def _plan(s, sql: str, **params) -> str:  # type: ignore[no-untyped-def]
    plan = s.execute(text(f"explain (format json) {sql}"), params).scalar_one()
    return json.dumps(plan)


def test_hot_queries_use_their_indexes_on_a_modest_dataset(perf_tenant) -> None:  # type: ignore[no-untyped-def]
    """20,000 movements and 20,000 journal lines: the newest-first movement list and a month of ledger lines must
    read an index, not scan the table (a sequential scan here is 100x slower on a real business)."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    t, c = str(perf_tenant["tenant_id"]), str(perf_tenant["company_id"])
    system_context(perf_tenant["tenant_id"])
    with tenant_session(perf_tenant["tenant_id"], admin=True) as s:
        p = {"t": t, "c": c}
        uom = s.execute(text("insert into products.uom (tenant_id, code, name) values (:t, 'PCS', 'Pieces') "
                             "returning id"), p).scalar_one()
        tax = s.execute(text("insert into products.tax_code (tenant_id, code, name, vat_rate) values "
                             "(:t, 'V', 'VAT', 16) returning id"), p).scalar_one()
        product = s.execute(text(
            "insert into products.product (tenant_id, company_id, sku, name, base_uom_id, tax_code_id) values "
            "(:t, :c, 'P1', 'Product', :u, :x) returning id"), {**p, "u": uom, "x": tax}).scalar_one()
        locations = s.execute(text(
            "insert into inventory.location (tenant_id, company_id, code, name) values (:t, :c, 'A', 'A'), "
            "(:t, :c, 'B', 'B') returning id"), p).scalars().all()
        s.execute(text(
            "insert into inventory.stock_movement (tenant_id, created_at, company_id, location_id, product_id, "
            "quantity, unit_cost, value, movement_type, source_type, source_id, business_date) "
            "select :t, now() - (g || ' minutes')::interval, :c, case when g % 2 = 0 then cast(:a as uuid) "
            "else cast(:b as uuid) end, :p, 1, 10, 10, 'receipt', 'goods_receipt', gen_random_uuid(), "
            "current_date - (g / 100)::int from generate_series(1, 20000) g"),
            {**p, "a": locations[0], "b": locations[1], "p": product})
        accounts = s.execute(text(
            "insert into finance.account (tenant_id, company_id, code, name, type) values "
            "(:t, :c, '1010', 'Cash', 'asset'), (:t, :c, '4000', 'Sales', 'income') returning id"), p).scalars().all()
        journal = s.execute(text("insert into finance.journal (tenant_id, company_id, code, name) values "
                                 "(:t, :c, 'SAL', 'Sales') returning id"), p).scalar_one()
        period = s.execute(text("insert into finance.period (tenant_id, company_id, start_date, end_date) values "
                                "(:t, :c, current_date - 400, current_date + 1) returning id"), p).scalar_one()
        s.execute(text(
            "insert into finance.journal_entry (id, tenant_id, company_id, journal_id, period_id, number, entry_date) "
            "select gen_random_uuid(), :t, :c, :j, :pe, 'SAL-' || g, current_date - (g / 30)::int "
            "from generate_series(1, 10000) g"), {**p, "j": journal, "pe": period})
        s.execute(text(
            "insert into finance.journal_line (tenant_id, entry_id, company_id, account_id, debit, credit) "
            "select :t, e.id, :c, case when side = 0 then cast(:a as uuid) else cast(:b as uuid) end, "
            "case when side = 0 then 10 else 0 end, case when side = 0 then 0 else 10 end "
            "from finance.journal_entry e cross join generate_series(0, 1) side"),
            {**p, "a": accounts[0], "b": accounts[1]})
        s.execute(text("analyze inventory.stock_movement"))
        s.execute(text("analyze finance.journal_line"))
        s.execute(text("analyze finance.journal_entry"))

        newest = _plan(s, "select * from inventory.stock_movement order by created_at desc, id limit 50")
        assert "stock_movement_ix4" in newest and "Seq Scan" not in newest, newest
        in_place = _plan(s, "select * from inventory.stock_movement where location_id = :l "
                            "order by created_at desc, id limit 50", l=str(locations[0]))
        assert "Seq Scan" not in in_place and ("stock_movement_ix5" in in_place or "stock_movement_ix4" in in_place), \
            in_place
        month = _plan(s, "select account_id, sum(debit), sum(credit) from finance.journal_line "
                         "where company_id = :c and entry_date >= current_date - 10 and entry_date <= current_date "
                         "group by account_id", c=c)
        assert "journal_line_ix4" in month and "Seq Scan" not in month, month
