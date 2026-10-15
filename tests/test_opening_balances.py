"""A business moves onto Ziira: what customers owe, what it owes suppliers and the trial balance are brought in from files.

The numbers are worked out by hand. Go-live is 2026-06-30. Customers (receivables control account 1100):
  CUST-A  INV-101 (2026-05-01, due 2026-05-31) 1,000.00  and  INV-102 (2026-06-10, due 2026-07-10) 2,500.50  -> 3,500.50
  CUST-B  INV-201 (2026-02-01, due 2026-03-03)   750.00                                                     ->   750.00
  CUST-C  paid in advance (credit)                300.00                                                     ->  -300.00
  the receivable total is 3,950.50.
Suppliers (payables control account 2000, credit balances):
  SUP-1   BD-1 (2026-06-01, due 2026-07-01) 4,000.00 and BD-2 (2026-04-15, due 2026-05-15) 1,250.25   -> 5,250.25
  SUP-2   X-9 (2026-06-20, 14-day terms so due 2026-07-04) 800.00                                      ->   800.00
  the payable total is 6,050.25.
Stock: 10 x 50.00 = 500.00 (inventory 1200). Trial balance: cash 5,000.00 and bank 20,000.00 debit; owner's equity
23,400.25 credit; receivables, payables and stock as above. Account by account the debits are 5,000.00 + 20,000.00 +
3,950.50 + 500.00 = 29,450.50 and the credits 6,050.25 + 23,400.25 = 29,450.50.
The trial balance entry posts cash, bank and equity (debit 25,000.00, credit 23,400.25) and, to cancel what the customers',
suppliers' and stock entries put on opening balance equity (net credit -1,599.75 = 3,950.50 - 6,050.25 + 500.00),
credits opening balance equity 1,599.75: afterwards opening balance equity is zero.
"""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from itertools import count
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from tests.finance_helpers import FIN, balance
from tests.pos_helpers import POS, make_sales_shop
from tests.purchasing_helpers import PUR
from tests.stock_helpers import INV, system
from ziira.kernel.jobs import run_due

IMP = "/api/v1/imports"
GO_LIVE = "2026-06-30"

CUSTOMERS = ("customer_code,reference,invoice_date,due_date,amount\n"
             "CUST-A,INV-101,2026-05-01,2026-05-31,1000.00\n"
             "CUST-A,INV-102,2026-06-10,2026-07-10,2500.50\n"
             "CUST-B,INV-201,2026-02-01,2026-03-03,750.00\n"
             "CUST-C,ADV-7,,,-300.00\n")
SUPPLIERS = ("supplier_code,reference,invoice_date,due_date,amount\n"
             "SUP-1,BD-1,2026-06-01,2026-07-01,4000.00\n"
             "SUP-1,BD-2,2026-04-15,2026-05-15,1250.25\n"
             "SUP-2,X-9,2026-06-20,,800.00\n")
TRIAL_BALANCE = ("account_code,debit,credit,party_code\n"
                 "1010,5000.00,,\n"
                 "1020,20000.00,,\n"
                 "1100,3500.50,,CUST-A\n"
                 "1100,750.00,,CUST-B\n"
                 "1100,,300.00,CUST-C\n"
                 "1200,500.00,,\n"
                 "2000,,5250.25,SUP-1\n"
                 "2000,,800.00,SUP-2\n"
                 "3000,,23400.25,\n")


def new_shop(client, registry, name: str, *, stock: bool = False):  # type: ignore[no-untyped-def]
    """A business with Finance, CRM, POS, Payments, Purchasing and Import on, the customers and suppliers above set up,
    and (with `stock`) 10 cement at 50.00 on hand since the go-live date."""
    shop = make_sales_shop(client, registry, name, stock="0")
    for unit in ("purchasing", "imports"):
        registry.enable(shop["tenant_id"], unit)
    owner, co = shop["owner"], str(shop["company_id"])
    shop["co"] = co
    for code, name_ in (("CUST-A", "Alpha Stores"), ("CUST-B", "Beta Traders"), ("CUST-C", "Gamma Mart")):
        r = client.post("/api/v1/crm/customers", headers=owner, json={"company_id": co, "code": code, "name": name_})
        assert r.status_code == 201, r.text
        shop[code] = r.json()["id"]
    for code, name_, terms in (("SUP-1", "First Supplies", 30), ("SUP-2", "Second Supplies", 14)):
        r = client.post(f"{PUR}/suppliers", headers=owner, json={
            "company_id": co, "code": code, "name": name_, "payment_terms_days": terms})
        assert r.status_code == 201, r.text
        shop[code] = r.json()["id"]
    r = client.post(f"{FIN}/companies/{co}/books", headers=owner)          # the chart must exist to import into
    assert r.status_code == 200, r.text
    if stock:
        r = client.post(f"{INV}/opening-stock", headers=owner, json={
            "company_id": co, "location_id": shop["main"], "business_date": GO_LIVE,
            "lines": [{"product_id": shop["cement"], "quantity": "10", "unit_cost": "50"}]})
        assert r.status_code == 201, r.text
    return shop


def upload(client, shop, kind: str, content: str, *, who: str = "owner", as_of: str | None = GO_LIVE,
           tolerance: str | None = None, expect: int = 201) -> dict[str, Any]:
    params: dict[str, Any] = {"kind": kind, "company_id": shop["co"], "filename": f"{kind}.csv"}
    if as_of:
        params["as_of"] = as_of
    if tolerance:
        params["tolerance"] = tolerance
    r = client.post(f"{IMP}/batches", headers={**shop[who], "Content-Type": "application/octet-stream"},
                    params=params, content=content.encode())
    assert r.status_code == expect, r.text
    return r.json()


def check(client, shop, batch_id: str) -> dict[str, Any]:
    r = client.post(f"{IMP}/batches/{batch_id}/validate", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


def commit(client, shop, batch_id: str, *, confirm: bool = False, expect: int = 202) -> dict[str, Any]:
    r = client.post(f"{IMP}/batches/{batch_id}/commit", headers=shop["owner"], params={"confirm": confirm})
    assert r.status_code == expect, r.text
    if expect != 202:
        return r.json()
    while run_due(shop["tenant_id"]) > 0:
        pass
    done = client.get(f"{IMP}/batches/{batch_id}", headers=shop["owner"]).json()
    assert done["status"] == "done", done
    return done


def bring_in(client, shop, kind: str, content: str, **kw) -> dict[str, Any]:
    """Upload, check and import a file that must be fine; the finished batch."""
    batch = upload(client, shop, kind, content)
    checked = check(client, shop, batch["id"])
    assert checked["counts"]["invalid"] == 0 and checked["file_check"]["problems"] == [], checked
    return commit(client, shop, batch["id"], **kw)


def report(client, shop, batch_id: str) -> dict[str, Any]:
    r = client.get(f"{IMP}/batches/{batch_id}/report", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


def rows(client, shop, batch_id: str) -> dict[int, dict[str, Any]]:
    r = client.get(f"{IMP}/batches/{batch_id}/rows", headers=shop["owner"], params={"limit": 200}).json()["rows"]
    return {x["row_no"]: x for x in r}


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def party_net(shop, account: str) -> dict[str, Dec]:  # type: ignore[no-untyped-def]
    """Debits less credits per party code of a control account, from the journal (customers and suppliers by code)."""
    found = sql(shop, "select coalesce(c.code, s.code) as code, sum(l.debit - l.credit) as net from finance.journal_line l "
                      "join finance.account a on a.id = l.account_id "
                      "left join crm.customer c on c.id = l.party_id left join purchasing.supplier s on s.id = l.party_id "
                      "where a.code = :a and l.party_id is not null group by 1", a=account)
    return {r.code: Dec(r.net) for r in found if r.net != 0}


def verify_clean(shop) -> None:  # type: ignore[no-untyped-def]
    """`ziira verify`: the books check, the customer ledger and the supplier ledger all report nothing."""
    from ziira.kernel import cli

    assert cli.main(["verify", shop["code"]]) == 0


def trial_balance(client, shop) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.get(f"{FIN}/reports/trial-balance", headers=shop["owner"],
                   params={"company_id": shop["co"], "as_of": "2026-12-31"})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- the happy path, in the right order
@pytest.fixture(scope="module")
def moved(client, registry):  # type: ignore[no-untyped-def]
    shop = new_shop(client, registry, "Moved Co", stock=True)
    shop["customers"] = bring_in(client, shop, "customer_balances", CUSTOMERS)
    shop["suppliers"] = bring_in(client, shop, "supplier_balances", SUPPLIERS)
    shop["tb"] = bring_in(client, shop, "opening_trial_balance", TRIAL_BALANCE)
    return shop


def test_the_new_kinds_are_listed_with_their_columns_and_need_a_go_live_date(client, moved) -> None:  # type: ignore[no-untyped-def]
    kinds = {k["kind"]: k for k in client.get(f"{IMP}/kinds", headers=moved["owner"]).json()}
    for kind in ("customer_balances", "supplier_balances", "opening_trial_balance"):
        assert kinds[kind]["needs_go_live"] and kinds[kind]["reversible"], kind
    assert kinds["opening_trial_balance"]["whole_file"] and not kinds["customer_balances"]["whole_file"]
    assert [c["name"] for c in kinds["customer_balances"]["columns"]] == [
        "customer_code", "reference", "invoice_date", "due_date", "amount"]
    template = client.get(f"{IMP}/kinds/customer_balances/template", headers=moved["owner"])
    assert template.text.splitlines()[0] == "customer_code,reference,invoice_date,due_date,amount"
    refused = upload(client, moved, "customer_balances", CUSTOMERS, as_of=None, expect=422)
    assert "go-live date" in refused["message"]


def test_receivables_equal_the_customers_balances_and_the_books_balance(client, moved) -> None:  # type: ignore[no-untyped-def]
    assert balance(moved, "1100") == Dec("3950.50")
    assert party_net(moved, "1100") == {"CUST-A": Dec("3500.50"), "CUST-B": Dec("750.00"), "CUST-C": Dec("-300.00")}
    owed = sql(moved, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice "
                      "where status in ('issued', 'part_paid')")[0][0]
    held = sql(moved, "select coalesce(sum(unallocated), 0) from pos.customer_receipt where status = 'posted'")[0][0]
    assert owed - held == balance(moved, "1100")
    assert owed == Dec("4250.50") and held == Dec("300.00")
    tb = trial_balance(client, moved)
    assert tb["balanced"] and Dec(tb["total_debit"]) == Dec(tb["total_credit"])
    verify_clean(moved)


def test_payables_equal_the_suppliers_balances(client, moved) -> None:  # type: ignore[no-untyped-def]
    assert balance(moved, "2000") == Dec("-6050.25")
    assert party_net(moved, "2000") == {"SUP-1": Dec("-5250.25"), "SUP-2": Dec("-800.00")}
    owed = sql(moved, "select coalesce(sum(total - amount_paid - credited), 0) from purchasing.supplier_bill "
                      "where status in ('posted', 'part_paid')")[0][0]
    assert owed == -balance(moved, "2000")


def test_every_account_shows_the_trial_balance_and_opening_equity_is_clear(client, moved) -> None:  # type: ignore[no-untyped-def]
    assert {c: balance(moved, c) for c in ("1010", "1020", "1100", "1200", "2000", "3000", "3100")} == {
        "1010": Dec("5000.00"), "1020": Dec("20000.00"), "1100": Dec("3950.50"), "1200": Dec("500.00"),
        "2000": Dec("-6050.25"), "3000": Dec("-23400.25"), "3100": Dec("0.00")}
    entry = sql(moved, "select e.entry_date, e.is_manual, d.number, d.difference, d.status from finance.opening_balance d "
                       "join finance.journal_entry e on e.id = d.entry_id")
    assert len(entry) == 1 and str(entry[0].entry_date) == GO_LIVE and entry[0].is_manual
    assert entry[0].number == "OB-000001" and entry[0].difference == 0 and entry[0].status == "posted"
    lines = sql(moved, "select a.code, l.debit, l.credit from finance.journal_line l join finance.account a on "
                       "a.id = l.account_id join finance.journal_entry e on e.id = l.entry_id "
                       "where e.source_type = 'opening_balance' order by a.code, l.debit")
    assert [(r.code, r.debit, r.credit) for r in lines] == [
        ("1010", Dec("5000.00"), 0), ("1020", Dec("20000.00"), 0), ("3000", 0, Dec("23400.25")),
        ("3100", 0, Dec("1599.75"))]


def test_the_reports_show_what_was_posted_against_what_the_files_said(client, moved) -> None:  # type: ignore[no-untyped-def]
    customers = report(client, moved, moved["customers"]["id"])
    assert customers["reconciled"] and customers["rows_in_file"] == 4
    assert {t["label"]: (Dec(t["in_file"]), Dec(t["in_ziira"])) for t in customers["totals"]} == {
        "customer balances": (Dec("3950.50"), Dec("3950.50")), "posted to the books": (Dec("3950.50"), Dec("3950.50"))}
    suppliers = report(client, moved, moved["suppliers"]["id"])
    assert suppliers["reconciled"]
    assert {t["label"]: Dec(t["in_ziira"]) for t in suppliers["totals"]} == {
        "supplier balances": Dec("6050.25"), "posted to the books": Dec("6050.25")}
    tb = report(client, moved, moved["tb"]["id"])
    assert tb["reconciled"], tb["problems"]
    assert {t["label"]: (Dec(t["in_file"]), Dec(t["in_ziira"])) for t in tb["totals"]} == {
        "debits": (Dec("29450.50"), Dec("29450.50")), "credits": (Dec("29450.50"), Dec("29450.50"))}
    assert {r["status"] for r in rows(client, moved, moved["tb"]["id"]).values()} == {"imported"}
    assert len({r["record_id"] for r in rows(client, moved, moved["tb"]["id"]).values()}) == 1      # one entry


def test_ageing_uses_the_original_due_dates(client, moved) -> None:  # type: ignore[no-untyped-def]
    ageing = client.get(f"{POS}/receivables/ageing", headers=moved["owner"], params={"as_of": GO_LIVE}).json()
    by_name = {c["customer"]: c for c in ageing["customers"]}
    a, b = by_name["Alpha Stores"], by_name["Beta Traders"]
    # A: due 2026-05-31 is 30 days late (1-30); due 2026-07-10 is not yet due. B: due 2026-03-03 is 119 days late.
    assert (Dec(a["not_due"]), Dec(a["1_30"]), Dec(a["total"])) == (Dec("2500.50"), Dec("1000.00"), Dec("3500.50"))
    assert (Dec(b["over_90"]), Dec(b["total"])) == (Dec("750.00"), Dec("750.00"))
    payables = client.get(f"{PUR}/payables", headers=moved["owner"], params={"as_of": GO_LIVE}).json()
    first = next(s for s in payables["suppliers"] if s["supplier"] == "First Supplies")
    second = next(s for s in payables["suppliers"] if s["supplier"] == "Second Supplies")
    assert (Dec(first["not_due"]), Dec(first["31_60"])) == (Dec("4000.00"), Dec("1250.25"))   # BD-2 is 46 days late
    assert (Dec(second["not_due"]), Dec(second["total"])) == (Dec("800.00"), Dec("800.00"))   # 20 June + 14 days
    assert Dec(payables["total"]) == Dec("6050.25")


def test_statements_show_the_opening_balances_and_the_credit(client, moved) -> None:  # type: ignore[no-untyped-def]
    st_a = client.get(f"{POS}/customers/{moved['CUST-A']}/statement", headers=moved["owner"]).json()
    assert [(x["kind"], Dec(x["debit"]), Dec(x["balance"])) for x in st_a["lines"]] == [
        ("invoice", Dec("1000.00"), Dec("1000.00")), ("invoice", Dec("2500.50"), Dec("3500.50"))]
    assert "Opening balance, invoice INV-101" in st_a["lines"][0]["description"]
    st_c = client.get(f"{POS}/customers/{moved['CUST-C']}/statement", headers=moved["owner"]).json()
    assert Dec(st_c["closing_balance"]) == Dec("-300.00") and "Credit brought forward" in st_c["lines"][0]["description"]
    balance_c = client.get(f"{POS}/customers/{moved['CUST-C']}/balance", headers=moved["owner"]).json()
    assert Dec(balance_c["owes"]) == Dec("-300.00") and Dec(balance_c["credit_on_account"]) == Dec("300.00")


def test_a_receipt_pays_an_opening_invoice_and_the_ledgers_still_agree(client, moved) -> None:  # type: ignore[no-untyped-def]
    paid = client.post(f"{POS}/receipts", headers=moved["owner"], json={
        "customer_id": moved["CUST-A"], "amount": "600.00", "method": "cash", "branch_id": str(moved["branch_id"])})
    assert paid.status_code == 201, paid.text
    invoices = {r.external_ref: (r.amount_paid, r.status) for r in sql(
        moved, "select external_ref, amount_paid, status from pos.sales_invoice where kind = 'opening_balance' "
               "and customer_id = :c", c=moved["CUST-A"])}
    assert invoices == {"INV-101": (Dec("600.00"), "part_paid"), "INV-102": (Dec("0.00"), "issued")}  # oldest due first
    assert balance(moved, "1100") == Dec("3350.50") and balance(moved, "1010") == Dec("5600.00")
    verify_clean(moved)
    # the credit of CUST-C can be applied to nothing (no invoice) but is held; it can be refunded as any advance
    receipt = sql(moved, "select id from pos.customer_receipt where method = 'opening'")[0].id
    assert client.post(f"{POS}/receipts/{receipt}/reverse", headers=moved["owner"], json={"reason": "x"}
                       ).status_code == 422                       # no payment behind it: it goes with the import


def test_an_import_with_payments_against_it_cannot_be_reversed(client, moved) -> None:  # type: ignore[no-untyped-def]
    refused = client.post(f"{IMP}/batches/{moved['customers']['id']}/reverse", headers=moved["owner"],
                          json={"reason": "wrong file"})
    assert refused.status_code == 422 or refused.status_code == 409
    # the trial balance has to go first, and then the customers' payment is what stops the rest
    assert "trial balance" in refused.json()["message"].lower() or "paid" in refused.json()["message"].lower()
    assert balance(moved, "1100") == Dec("3350.50")


def test_an_opening_invoice_cannot_be_cancelled_by_hand(client, moved) -> None:  # type: ignore[no-untyped-def]
    invoice = sql(moved, "select id from pos.sales_invoice where kind = 'opening_balance' limit 1")[0].id
    r = client.post(f"{POS}/invoices/{invoice}/cancel", headers=moved["owner"], json={"reason": "no"})
    assert r.status_code == 422 and "reversing the whole import" in r.json()["message"]


def test_the_opening_entry_cannot_be_reversed_as_a_plain_journal_entry(client, moved) -> None:  # type: ignore[no-untyped-def]
    entry = sql(moved, "select entry_id from finance.opening_balance")[0].entry_id
    r = client.post(f"{FIN}/journal-entries/{entry}/reverse", headers=moved["owner"], json={"reason": "no"})
    assert r.status_code == 422 and "opening balance entry" in r.json()["message"]


def test_only_the_owner_imports_and_one_business_cannot_see_anothers_batch(client, registry, moved) -> None:  # type: ignore[no-untyped-def]
    for who in ("fm", "manager", "cashier", "storekeeper"):
        upload(client, moved, "customer_balances", CUSTOMERS, who=who, expect=403)
        assert client.get(f"{IMP}/kinds", headers=moved[who]).status_code == 403
    other = new_shop(client, registry, "Other Moved Co")
    seen = client.get(f"{IMP}/batches/{moved['tb']['id']}", headers=other["owner"])
    assert seen.status_code == 404
    assert client.post(f"{IMP}/batches/{moved['tb']['id']}/reverse", headers=other["owner"],
                       json={"reason": "x"}).status_code == 404
    listing = client.get(f"{FIN}/opening-balances", headers=other["owner"]).json()
    assert listing == []
    assert len(client.get(f"{FIN}/opening-balances", headers=moved["owner"]).json()) == 1
    assert client.get(f"{FIN}/opening-balances", headers=moved["cashier"]).status_code == 403


def test_balances_cannot_be_added_after_the_trial_balance(client, moved) -> None:  # type: ignore[no-untyped-def]
    late = upload(client, moved, "customer_balances",
                  "customer_code,reference,invoice_date,due_date,amount\nCUST-B,INV-999,2026-06-01,2026-07-01,10.00\n")
    checked = check(client, moved, late["id"])
    assert checked["counts"]["invalid"] == 1
    assert "trial balance has already been posted" in rows(client, moved, late["id"])[2]["errors"][0]
    late_bill = upload(client, moved, "supplier_balances",
                       "supplier_code,reference,invoice_date,amount\nSUP-1,BD-9,2026-06-01,10.00\n")
    assert check(client, moved, late_bill["id"])["counts"]["invalid"] == 1


# --------------------------------------------------------------------------- undoing a whole import
@pytest.fixture(scope="module")
def undone(client, registry):  # type: ignore[no-untyped-def]
    return new_shop(client, registry, "Undone Co", stock=True)


def test_importing_the_same_file_twice_changes_nothing(client, undone) -> None:  # type: ignore[no-untyped-def]
    first = bring_in(client, undone, "customer_balances", CUSTOMERS)
    bring_in(client, undone, "supplier_balances", SUPPLIERS)
    again = upload(client, undone, "customer_balances", CUSTOMERS)
    checked = check(client, undone, again["id"])
    assert checked["counts"] == {"pending": 0, "valid": 0, "invalid": 0, "imported": 0, "skipped": 4, "failed": 0,
                                 "reverted": 0}
    assert "already has an opening balance INV-101" in rows(client, undone, again["id"])[2]["errors"][0]
    commit(client, undone, again["id"], expect=422)
    assert balance(undone, "1100") == Dec("3950.50")
    assert sql(undone, "select count(*) from pos.sales_invoice where kind = 'opening_balance'")[0][0] == 3
    # a second batch of suppliers with the same invoices is skipped too, and a typed-in duplicate inside one file is refused
    again = upload(client, undone, "supplier_balances", SUPPLIERS + "SUP-1,BD-1,2026-06-01,2026-07-01,1.00\n")
    counts = check(client, undone, again["id"])["counts"]
    assert counts["skipped"] == 3 and counts["invalid"] == 1
    assert "same" in rows(client, undone, again["id"])[5]["errors"][0]
    assert first["counts"]["imported"] == 4


def test_a_second_trial_balance_needs_the_first_to_be_reversed(client, undone) -> None:  # type: ignore[no-untyped-def]
    tb = bring_in(client, undone, "opening_trial_balance", TRIAL_BALANCE)
    second = upload(client, undone, "opening_trial_balance", TRIAL_BALANCE)
    checked = check(client, undone, second["id"])
    assert any("already has an opening balance entry" in p for p in checked["file_check"]["problems"])
    commit(client, undone, second["id"], expect=422)
    assert sql(undone, "select count(*) from finance.opening_balance")[0][0] == 1
    undone["tb"] = tb


def test_reversing_the_whole_import_in_the_right_order_leaves_the_books_balanced(client, undone) -> None:  # type: ignore[no-untyped-def]
    batches = {b["kind"]: b for b in client.get(f"{IMP}/batches", headers=undone["owner"]).json()
               if b["status"] == "done"}
    reason = {"reason": "Loaded the wrong month"}
    # the trial balance first: customers cannot be reversed while their control account is what the trial balance checks
    reversed_tb = client.post(f"{IMP}/batches/{batches['opening_trial_balance']['id']}/reverse",
                              headers=undone["owner"], json=reason)
    assert reversed_tb.status_code == 200 and reversed_tb.json()["status"] == "reverted"
    assert reversed_tb.json()["counts"]["reverted"] == 9
    assert balance(undone, "3000") == 0 and balance(undone, "1010") == 0
    assert sql(undone, "select status, reverse_reason from finance.opening_balance") == [("reversed", "Loaded the wrong month")]
    again = client.post(f"{IMP}/batches/{batches['opening_trial_balance']['id']}/reverse", headers=undone["owner"],
                        json=reason)
    assert again.status_code == 409
    customers = client.post(f"{IMP}/batches/{batches['customer_balances']['id']}/reverse", headers=undone["owner"],
                            json=reason)
    assert customers.status_code == 200 and customers.json()["status"] == "reverted"
    suppliers = client.post(f"{IMP}/batches/{batches['supplier_balances']['id']}/reverse", headers=undone["owner"],
                            json=reason)
    assert suppliers.status_code == 200
    assert balance(undone, "1100") == 0 and balance(undone, "2000") == 0
    assert balance(undone, "1200") == Dec("500.00")                         # stock has its own import
    assert balance(undone, "3100") == Dec("-500.00")
    assert sql(undone, "select count(*) from pos.sales_invoice where kind = 'opening_balance' and status = 'cancelled'"
               )[0][0] == 3
    assert sql(undone, "select status, unallocated from pos.customer_receipt where method = 'opening'") == [
        ("reversed", 0)]
    assert sql(undone, "select count(*) from purchasing.supplier_bill where kind = 'opening_balance' and "
                       "status = 'reversed'")[0][0] == 3
    ageing = client.get(f"{POS}/receivables/ageing", headers=undone["owner"]).json()
    assert Dec(ageing["total"]) == 0
    tb = trial_balance(client, undone)
    assert tb["balanced"]
    verify_clean(undone)
    kept = client.get(f"{IMP}/batches/{batches['customer_balances']['id']}", headers=undone["owner"]).json()
    assert kept["status"] == "reverted" and kept["revert_reason"] == "Loaded the wrong month"


def test_after_a_reversal_the_corrected_file_goes_in(client, undone) -> None:  # type: ignore[no-untyped-def]
    fixed = CUSTOMERS.replace("1000.00", "1100.00")
    bring_in(client, undone, "customer_balances", fixed)
    assert balance(undone, "1100") == Dec("4050.50")                        # 1,100.00 + 2,500.50 + 750.00 - 300.00
    verify_clean(undone)


def test_a_reversal_needs_a_reason_and_a_finished_import_of_a_reversible_kind(client, undone) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, undone, "customer_balances", CUSTOMERS)
    assert client.post(f"{IMP}/batches/{batch['id']}/reverse", headers=undone["owner"],
                       json={"reason": "x"}).status_code == 409            # not imported yet
    assert client.post(f"{IMP}/batches/{batch['id']}/reverse", headers=undone["owner"], json={}).status_code == 422


# --------------------------------------------------------------------------- a trial balance that does not balance
@pytest.fixture(scope="module")
def plain(client, registry):  # type: ignore[no-untyped-def]
    return new_shop(client, registry, "Plain Co")


def tb_file(*lines: str) -> str:
    return "account_code,debit,credit,party_code\n" + "".join(f"{line}\n" for line in lines)


def test_a_file_that_does_not_balance_posts_its_difference_to_opening_equity_only_when_confirmed(  # type: ignore[no-untyped-def]
        client, plain) -> None:
    batch = upload(client, plain, "opening_trial_balance", tb_file("1010,1000.00,,", "3000,,900.00,"))
    checked = check(client, plain, batch["id"])
    assert checked["file_check"]["problems"] == []
    assert "debits are more than credits by 100.00" in checked["file_check"]["confirm"]
    refused = commit(client, plain, batch["id"], expect=409)
    assert "100.00" in refused["message"]
    assert sql(plain, "select count(*) from finance.opening_balance")[0][0] == 0
    done = commit(client, plain, batch["id"], confirm=True)
    assert done["options"]["confirmed"] == "1"
    assert balance(plain, "1010") == Dec("1000.00") and balance(plain, "3000") == Dec("-900.00")
    assert balance(plain, "3100") == Dec("-100.00")                          # the difference, and only that, is here
    doc = sql(plain, "select difference from finance.opening_balance")[0]
    assert doc.difference == Dec("100.00")
    assert trial_balance(client, plain)["balanced"]
    verify_clean(plain)
    # the report says the books carry the file's figures (the difference sits on opening equity, not on a file account)
    assert {t["label"]: Dec(t["in_ziira"]) for t in report(client, plain, batch["id"])["totals"]} == {
        "debits": Dec("1000.00"), "credits": Dec("900.00")}
    opening_id = sql(plain, "select id from finance.opening_balance")[0].id
    reversed_ = client.post(f"{FIN}/opening-balances/{opening_id}/reverse", headers=plain["fm"],
                            json={"reason": "Redo"})
    assert reversed_.status_code == 200 and reversed_.json()["status"] == "reversed"
    assert all(balance(plain, c) == 0 for c in ("1010", "3000", "3100"))


def test_a_small_difference_within_the_tolerance_goes_to_opening_equity_without_confirmation(  # type: ignore[no-untyped-def]
        client, plain) -> None:
    file = tb_file("1010,1000.00,,", "3000,,999.97,")
    strict = check(client, plain, upload(client, plain, "opening_trial_balance", file)["id"])
    assert strict["file_check"]["confirm"] is not None                       # no tolerance: it must be confirmed
    batch = upload(client, plain, "opening_trial_balance", file, tolerance="0.05")
    checked = check(client, plain, batch["id"])
    assert checked["file_check"]["confirm"] is None and "within the tolerance of 0.05" in checked["file_check"]["notes"][0]
    commit(client, plain, batch["id"])
    assert balance(plain, "3100") == Dec("-0.03")
    opening_id = sql(plain, "select id from finance.opening_balance where status = 'posted'")[0].id
    assert client.post(f"{FIN}/opening-balances/{opening_id}/reverse", headers=plain["fm"],
                       json={"reason": "Redo"}).status_code == 200
    # an accountant who cannot approve may not reverse it
    assert client.post(f"{FIN}/opening-balances/{opening_id}/reverse", headers=plain["manager"],
                       json={"reason": "x"}).status_code == 403


def test_income_and_expense_lines_and_other_bad_lines_are_refused_row_by_row(client, plain) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, plain, "opening_trial_balance", tb_file(
        "4000,,500.00,",             # row 2  income
        "6000,500.00,,",             # row 3  expense
        "1100,100.00,,",             # row 4  receivables with no customer
        "1100,100.00,,NOPE",         # row 5  a customer that does not exist
        "1010,100.00,,CUST-A",       # row 6  a customer code on an ordinary account
        "1030,100.00,,",             # row 7  mobile money clearing is kept by its own records
        "9999,100.00,,",             # row 8  no such account
        "1020,100.00,100.00,",       # row 9  debit and credit both
        "1020,-5.00,,",              # row 10 negative
        "1020,10.005,,",             # row 11 more than two decimals
        "3000,,100.00,", "3000,,100.00,"))  # rows 12-13 the same account twice
    checked = check(client, plain, batch["id"])
    listing = rows(client, plain, batch["id"])
    assert checked["counts"]["valid"] == 1 and checked["counts"]["invalid"] == 11
    assert "balance sheet accounts" in listing[2]["errors"][0] and "balance sheet accounts" in listing[3]["errors"][0]
    assert "needs the customer's code" in listing[4]["errors"][0]
    assert "no customer with code NOPE" in listing[5]["errors"][0]
    assert "only receivable and payable accounts" in listing[6]["errors"][0]
    assert "kept by its own records" in listing[7]["errors"][0]
    assert "no account 9999" in listing[8]["errors"][0]
    assert "either a debit or a credit" in listing[9]["errors"][0]
    assert "must be 0 or more" in listing[10]["errors"][0]
    assert "at most 2 decimal places" in listing[11]["errors"][0]
    assert "same" in listing[13]["errors"][0]
    assert any("every row must be valid" in p for p in checked["file_check"]["problems"])
    commit(client, plain, batch["id"], expect=422)
    assert sql(plain, "select count(*) from finance.opening_balance")[0][0] == 2     # the two reversed ones only


def test_control_lines_must_agree_with_the_customers_and_stock_already_in(client, plain) -> None:  # type: ignore[no-untyped-def]
    bring_in(client, plain, "customer_balances", CUSTOMERS)
    # the file leaves CUST-B out and has CUST-A wrong
    batch = upload(client, plain, "opening_trial_balance", tb_file(
        "1100,3000.00,,CUST-A", "1100,,300.00,CUST-C", "1200,500.00,,", "3000,,3200.00,"))
    problems = check(client, plain, batch["id"])["file_check"]["problems"]
    assert len(problems) == 2
    receivable = next(p for p in problems if p.startswith("1100"))
    assert "CUST-A: file 3,000.00, Ziira 3,500.50" in receivable and "another customer: file 0.00, Ziira 750.00" in receivable
    assert next(p for p in problems if p.startswith("1200")) == (
        "1200 Inventory: the file says 500.00 but opening stock in Ziira is worth 0.00. Import opening stock first, "
        "or correct the file")
    commit(client, plain, batch["id"], expect=422)
    assert sql(plain, "select count(*) from finance.opening_balance where status = 'posted'")[0][0] == 0


# --------------------------------------------------------------------------- the period
def test_a_closed_period_refuses_opening_balances(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = new_shop(client, registry, "Locked Co")
    period = client.post(f"{FIN}/periods", headers=shop["owner"], json={"company_id": shop["co"], "day": GO_LIVE})
    assert period.status_code == 201, period.text
    for state in ("soft_closed", "locked"):
        assert client.post(f"{FIN}/periods/{period.json()['id']}/status", headers=shop["owner"],
                           json={"status": state}).status_code == 200
    batch = upload(client, shop, "customer_balances", CUSTOMERS)
    checked = check(client, shop, batch["id"])
    assert checked["counts"]["invalid"] == 4
    assert "locked" not in checked["counts"] and "closed" in rows(client, shop, batch["id"])[2]["errors"][0]
    tb = upload(client, shop, "opening_trial_balance", tb_file("1010,100.00,,", "3000,,100.00,"))
    assert any("is locked" in p for p in check(client, shop, tb["id"])["file_check"]["problems"])
    assert sql(shop, "select count(*) from finance.journal_entry where source_type like 'opening%'")[0][0] == 0
    # and a go-live date in the future is refused
    future = upload(client, shop, "customer_balances", CUSTOMERS, as_of="2999-01-01")
    assert "in the future" in rows(client, shop, check(client, shop, future["id"])["id"])[2]["errors"][0]


# --------------------------------------------------------------------------- a property: any opening balances keep the books
SERIAL = count(1)
amounts = st.integers(min_value=1, max_value=9_999_999).map(lambda cents: Dec(cents) / 100)


@pytest.fixture(scope="module")
def prop(client, registry):  # type: ignore[no-untyped-def]
    return new_shop(client, registry, "Property Co")


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(invoices=st.lists(st.tuples(st.integers(0, 2), amounts, st.integers(0, 120)), max_size=6),
       credits=st.lists(st.tuples(st.integers(0, 2), amounts), max_size=2),
       bills=st.lists(st.tuples(st.integers(0, 1), amounts), max_size=4))
def test_any_opening_balances_keep_debits_equal_credits_and_the_ledgers_equal_the_controls(  # type: ignore[no-untyped-def]
        prop, invoices, credits, bills) -> None:
    from datetime import timedelta

    from ziira.modules.crm.public import find_customer
    from ziira.modules.pos.hooks import CustomerLedgerCheck
    from ziira.modules.pos.services import opening_balances as pos_opening
    from ziira.modules.purchasing.hooks import SupplierLedgerCheck
    from ziira.modules.purchasing.repository import purchasing_repo
    from ziira.modules.purchasing.services import opening_balances as buy_opening

    live = date.fromisoformat(GO_LIVE)
    customers = [prop["CUST-A"], prop["CUST-B"], prop["CUST-C"]]
    suppliers = [prop["SUP-1"], prop["SUP-2"]]
    made: list[Any] = []
    with system(prop) as s:
        for who, amount, age in invoices:
            customer = find_customer(s, customers[who])
            made.append(pos_opening.create_opening_invoice(
                s, customer=customer, reference=f"P-{next(SERIAL)}", issue_date=live - timedelta(days=age + 1),
                due_date=live - timedelta(days=age), amount=amount, go_live_date=live))
        for who, amount in credits:
            customer = find_customer(s, customers[who])
            made.append(pos_opening.create_opening_credit(
                s, customer=customer, reference=f"P-{next(SERIAL)}", amount=amount, go_live_date=live))
        bill_ids = []
        for who, amount in bills:
            supplier = purchasing_repo.get_supplier(s, suppliers[who])
            bill_ids.append(buy_opening.create_opening_bill(
                s, supplier=supplier, reference=f"P-{next(SERIAL)}", bill_date=live - timedelta(days=5),
                due_date=live, amount=amount, go_live_date=live).id)
    owed = sum((a for _, a, _ in invoices), Dec(0)) - sum((a for _, a in credits), Dec(0))
    assert balance(prop, "1100") == owed
    assert balance(prop, "2000") == -sum((a for _, a in bills), Dec(0))
    totals = sql(prop, "select coalesce(sum(debit), 0) as d, coalesce(sum(credit), 0) as c from finance.journal_line")[0]
    assert totals.d == totals.c
    with system(prop) as s:
        assert CustomerLedgerCheck().run(s) == [] and SupplierLedgerCheck().run(s) == []
        pos_opening.reverse_opening_documents(s, [m.id for m in made], "property test")
        buy_opening.reverse_opening_bills(s, bill_ids, "property test")
    assert balance(prop, "1100") == 0 and balance(prop, "2000") == 0
    totals = sql(prop, "select coalesce(sum(debit), 0) as d, coalesce(sum(credit), 0) as c from finance.journal_line")[0]
    assert totals.d == totals.c


def test_the_domain_always_balances_the_entry() -> None:
    from ziira.modules.finance.domain import opening

    for plain_net, controlled in ((Dec("1599.75"), Dec("-1599.75")), (Dec("100"), Dec("0")), (Dec("-30"), Dec("50")),
                                  (Dec("0"), Dec("-12.34")), (Dec("7.10"), Dec("3.30"))):
        pos = opening.position(plain_net, controlled)
        equity = sum((a if side == "debit" else -a for side, a, _ in opening.equity_lines(pos)), Dec(0))
        assert plain_net + equity == 0              # the lines the entry posts net to zero, difference accepted or not
        assert pos.difference == plain_net + controlled
