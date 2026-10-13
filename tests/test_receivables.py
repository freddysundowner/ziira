"""What customers owe: ageing, statements, balances, reminders, and the check that the books agree."""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, credit_sale, make_sales_shop
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Owed Co", stock="500")
    s["rep"] = s["user"]("rep", "Sales Rep", s["branch_id"])
    return s


def invoice_of(client, shop, sale):  # type: ignore[no-untyped-def]
    return next(i for i in client.get(f"{POS}/invoices", headers=shop["fm"], params={"limit": 200}).json()
                if i["sale_id"] == sale["id"])


def aged_invoice(client, shop, cust, days_old: int, qty: str = "1", terms: int = 30):  # type: ignore[no-untyped-def]
    """An invoice issued `days_old` days ago, due `terms` days after that."""
    r = client.post(f"{POS}/invoices", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "terms_days": terms,
        "issue_date": str(date.today() - timedelta(days=days_old)),
        "lines": [{"product_id": shop["cement"], "quantity": qty}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_ageing_puts_each_invoice_in_its_band(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Aged Debtor", limit="100000", terms=30)
    for days in (5, 45, 75, 110, 200):                                  # 25 days to go, 15, 45, 80, 170 overdue
        aged_invoice(client, shop, cust, days)
    report = client.get(f"{POS}/receivables/ageing", headers=shop["fm"], params={"customer_id": cust["id"]}).json()
    row = report["customers"][0]
    assert row["customer"] == "Aged Debtor" and Dec(row["total"]) == 580
    assert (Dec(row["not_due"]), Dec(row["1_30"]), Dec(row["31_60"]), Dec(row["61_90"]), Dec(row["over_90"])) == (
        Dec(116), Dec(116), Dec(116), Dec(116), Dec(116))
    assert Dec(report["buckets"]["over_90"]) >= 116 and Dec(report["total"]) >= 580
    earlier = client.get(f"{POS}/receivables/ageing", headers=shop["fm"], params={
        "customer_id": cust["id"], "as_of": str(date.today() - timedelta(days=150))}).json()
    assert Dec(earlier["total"]) == Dec(116)                                                  # only the oldest existed
    assert client.get(f"{POS}/receivables/ageing", headers=shop["storekeeper"]).status_code == 403
    assert client.get(f"{POS}/receivables/ageing", headers=shop["cashier"]).status_code == 403


def test_a_statement_is_the_account_with_a_running_balance(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.pos_helpers import ensure_till

    cust = credit_customer(client, shop, name="Statement Customer", limit="100000")
    credit_sale(client, shop, cust, qty="2")                                                   # 232
    second = credit_sale(client, shop, cust, qty="1").json()                                   # 116
    ensure_till(client, shop, "manager")
    back = client.post(f"{POS}/sales/{second['id']}/returns", headers=shop["manager"], json={
        "lines": [{"sale_line_id": second["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": shop["reasons"]["sale_return"], "refund_method": "credit_note"})
    assert back.status_code == 201, back.text
    paid = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "200.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    assert paid.status_code == 201, paid.text
    st = client.get(f"{POS}/customers/{cust['id']}/statement", headers=shop["fm"]).json()
    rows = [(x["kind"], Dec(x["debit"]), Dec(x["credit"]), Dec(x["balance"])) for x in st["lines"]]
    assert rows == [("invoice", Dec(232), Dec(0), Dec(232)), ("invoice", Dec(116), Dec(0), Dec(348)),
                    ("credit_note", Dec(0), Dec(116), Dec(232)), ("receipt", Dec(0), Dec(200), Dec(32))]
    assert Dec(st["closing_balance"]) == Dec(st["owed_now"]) == 32                               # the statement agrees
    assert Dec(st["opening_balance"]) == 0 and st["code"] == cust["code"]
    from_tomorrow = client.get(f"{POS}/customers/{cust['id']}/statement", headers=shop["fm"], params={
        "date_from": str(date.today() + timedelta(days=1))}).json()
    assert from_tomorrow["lines"] == [] and Dec(from_tomorrow["opening_balance"]) == 32
    assert client.get(f"{POS}/customers/{uuid4()}/statement", headers=shop["fm"]).status_code == 404
    assert client.get(f"{POS}/customers/{cust['id']}/statement", headers=shop["storekeeper"]).status_code == 403


def test_a_customers_balance_and_what_they_can_still_take(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Balance Check", limit="1000", terms=21)
    credit_sale(client, shop, cust, qty="3")                                                   # 348
    b = client.get(f"{POS}/customers/{cust['id']}/balance", headers=shop["rep"]).json()
    assert (Dec(b["owes"]), Dec(b["credit_limit"]), Dec(b["available"]), b["terms_days"]) == (
        Dec(348), Dec(1000), Dec(652), 21)
    from ziira.modules.pos.public import customer_balance

    with system(shop) as s:
        assert customer_balance(s, cust["id"]) == 348


def test_overdue_invoices_come_up_for_a_reminder_until_chased(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Slow Payer", limit="100000", terms=30, phone="0722000999")
    fresh = credit_sale(client, shop, cust, qty="1").json()
    assert all(r["customer_id"] != cust["id"] for r in client.get(f"{POS}/receivables/reminders",
                                                                   headers=shop["fm"]).json())     # not due yet
    inv = aged_invoice(client, shop, cust, 40)                                                  # due 10 days ago
    due = client.get(f"{POS}/receivables/reminders", headers=shop["fm"]).json()
    mine = next(r for r in due if r["invoice_id"] == inv["id"])
    assert mine["days_overdue"] == 10 and Dec(mine["outstanding"]) == 116 and mine["phone"] == "254722000999"
    path = f"{POS}/invoices/{inv['id']}/reminders"
    assert client.post(path, headers=shop["fm"], json={"channel": "pigeon"}).status_code == 422
    assert client.post(path, headers=shop["storekeeper"], json={"channel": "call"}).status_code == 403
    made = client.post(path, headers=shop["fm"], json={"channel": "call", "note": "Sent the statement"})
    assert made.status_code == 201 and made.json()["channel"] == "call"
    again = client.get(f"{POS}/receivables/reminders", headers=shop["fm"]).json()
    assert all(r["invoice_id"] != inv["id"] for r in again)                                     # chased a moment ago
    later = client.get(f"{POS}/receivables/reminders", headers=shop["fm"], params={"repeat_days": 0}).json()
    assert any(r["invoice_id"] == inv["id"] and r["last_reminder"] for r in later)
    client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "232.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    paid = client.post(path, headers=shop["fm"], json={"channel": "call"})
    assert paid.status_code == 422 and fresh["id"]                                              # nothing left to chase


def test_the_ledger_check_finds_a_difference_and_is_otherwise_quiet(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.pos.hooks import CustomerLedgerCheck

    with system(shop) as s:
        assert CustomerLedgerCheck().run(s) == []
    cust = credit_customer(client, shop, name="Ledger Check", limit="100000")
    inv = invoice_of(client, shop, credit_sale(client, shop, cust, qty="1").json())
    # break the records on purpose: say the invoice was paid without a receipt
    with system(shop) as s:
        s.execute(text("update pos.sales_invoice set amount_paid = 50 where id = :i"), {"i": inv["id"]})
    with system(shop) as s:
        problems = CustomerLedgerCheck().run(s)
    assert any("marked 50" in p for p in problems) and any(cust["id"] in p for p in problems)
    with system(shop) as s:
        s.execute(text("update pos.sales_invoice set amount_paid = 0 where id = :i"), {"i": inv["id"]})
        assert CustomerLedgerCheck().run(s) == []
    assert one(shop, "select count(*) from pos.sales_invoice") > 0


def test_a_cashier_can_check_a_balance_and_take_payments_but_not_browse_debtors(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="At The Counter", limit="2000")
    credit_sale(client, shop, cust, qty="1")
    assert client.get(f"{POS}/customers/{cust['id']}/balance", headers=shop["cashier"]).status_code == 200
    for path in (f"{POS}/receivables/ageing", f"{POS}/invoices", f"{POS}/customers/{cust['id']}/statement",
                 f"{POS}/receivables/reminders", f"{POS}/receipts", f"{POS}/quotations"):
        assert client.get(path, headers=shop["cashier"]).status_code == 403, path
    paid = client.post(f"{POS}/receipts", headers=shop["cashier"], json={
        "customer_id": cust["id"], "amount": "50.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    assert paid.status_code == 201
    assert client.get(f"{POS}/customers/{cust['id']}/balance", headers=shop["storekeeper"]).status_code == 403
