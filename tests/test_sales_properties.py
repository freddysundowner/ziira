"""Credit and receivables under pressure: simultaneous requests never exceed a limit, overpay an invoice or deliver more
than was ordered, and a random history of selling, paying, returning and cancelling keeps every ledger in agreement."""

import random
from collections import Counter
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import one
from tests.pos_helpers import (
    POS,
    credit_customer,
    credit_sale,
    ensure_till,
    line,
    make_sales_shop,
    open_till,
    sell,
    stock,
)
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Sales Props Co", stock="2000")
    s["rep"] = s["user"]("rep", "Sales Rep", s["branch_id"])
    return s


def staff(client, shop, n: int, prefix: str):  # type: ignore[no-untyped-def]
    out = []
    for i in range(n):
        name = f"{prefix}{i}"
        who = shop["user"](name, "Cashier", shop["branch_id"])
        dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
            "branch_id": str(shop["branch_id"]), "code": f"{prefix[:3].upper()}{i}", "name": name,
            "location_id": shop["main"]}).json()
        shop[name], shop["devices"][name] = who, dev["id"]
        out.append((name, open_till(client, shop, name).json()["id"]))
    return out


def owed(shop, customer) -> Dec:  # type: ignore[no-untyped-def]
    return one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where "
                     "customer_id = :c and status in ('issued', 'part_paid')", c=customer["id"])


def test_simultaneous_credit_sales_never_exceed_the_limit(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Race Limit", limit="400")
    crew = staff(client, shop, 4, "creditrace")
    body = lambda till: {"till_session_id": till, "customer_id": cust["id"],  # noqa: E731
                         "lines": [line(shop, "cement", "1")], "payments": [{"method": "credit", "amount": "116.00"}]}
    results = together([lambda who=who, till=till: client.post(f"{POS}/sales", headers=shop[who], json=body(till))
                        for _ in range(3) for who, till in crew])                               # 12 tries at 116 each
    assert Counter(r.status_code for r in results) == {201: 3, 422: 9}, [r.text for r in results][:2]
    assert owed(shop, cust) == 348 <= 400


def test_simultaneous_payments_never_pay_more_than_is_owed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Race Pay", limit="5000")
    credit_sale(client, shop, cust, qty="2")                                                    # 232
    pay = lambda: client.post(f"{POS}/receipts", headers=shop["fm"], json={  # noqa: E731
        "customer_id": cust["id"], "amount": "100.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    results = together([pay for _ in range(6)])
    assert Counter(r.status_code for r in results) == {201: 2, 422: 4}, [r.text for r in results]
    assert owed(shop, cust) == 32
    paid = one(shop, "select coalesce(sum(amount_paid), 0) from pos.sales_invoice where customer_id = :c", c=cust["id"])
    live = one(shop, "select coalesce(sum(amount), 0) from pos.customer_receipt where customer_id = :c and "
                     "status = 'posted'", c=cust["id"])
    assert paid == live == 200


def test_an_order_cannot_be_delivered_more_than_once_at_the_same_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Race Deliver", limit="100000")
    order = client.post(f"{POS}/orders", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"],
        "lines": [{"product_id": shop["cement"], "quantity": "10"}]}).json()
    client.post(f"{POS}/orders/{order['id']}/submit", headers=shop["rep"])
    stock0 = stock(shop)
    deliver = lambda: client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={  # noqa: E731
        "lines": [{"order_line_id": order["lines"][0]["id"], "quantity": "6"}]})
    results = together([deliver for _ in range(5)])
    assert Counter(r.status_code for r in results) == {201: 1, 422: 4}, [r.text for r in results]
    assert stock(shop) == stock0 - 6
    assert Dec(client.get(f"{POS}/orders/{order['id']}", headers=shop["rep"]).json()["lines"][0]["qty_delivered"]) == 6


def test_credit_notes_and_payments_racing_never_credit_beyond_what_is_owed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Race Credit", limit="5000")
    sale = credit_sale(client, shop, cust, qty="2").json()                                      # 232
    ensure_till(client, shop, "manager")
    note = lambda: client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json={  # noqa: E731
        "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": shop["reasons"]["sale_return"], "refund_method": "credit_note"})
    pay = lambda: client.post(f"{POS}/receipts", headers=shop["fm"], json={  # noqa: E731
        "customer_id": cust["id"], "amount": "150.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    results = together([note, note, note, pay, pay])
    assert all(r.status_code in (201, 422) for r in results), [r.text for r in results]
    invoice = client.get(f"{POS}/invoices", headers=shop["fm"], params={"customer_id": cust["id"]}).json()[0]
    assert Dec(invoice["amount_paid"]) + Dec(invoice["credited"]) <= Dec(invoice["total"])
    assert owed(shop, cust) == Dec(invoice["total"]) - Dec(invoice["amount_paid"]) - Dec(invoice["credited"]) >= 0


def test_a_payment_and_a_void_racing_leave_one_consistent_result(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Race Void", limit="5000")
    sale = credit_sale(client, shop, cust, qty="1").json()
    void = lambda: client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"], json={  # noqa: E731
        "reason_code_id": shop["reasons"]["void"]})
    pay = lambda: client.post(f"{POS}/receipts", headers=shop["fm"], json={  # noqa: E731
        "customer_id": cust["id"], "amount": "116.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    ensure_till(client, shop, "manager")
    results = together([void, pay, void, pay])
    inv = client.get(f"{POS}/invoices", headers=shop["fm"], params={"customer_id": cust["id"]}).json()[0]
    if inv["status"] == "cancelled":
        assert Dec(inv["amount_paid"]) == 0 and owed(shop, cust) == 0
    else:
        assert inv["status"] == "paid" and Dec(inv["amount_paid"]) == 116
    from tests.stock_helpers import system
    from ziira.modules.pos.hooks import CustomerLedgerCheck

    with system(shop) as s:
        assert CustomerLedgerCheck().run(s) == [], [r.text for r in results]


def test_random_trading_on_account_keeps_every_ledger_in_agreement(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import system
    from ziira.modules.pos.hooks import CustomerLedgerCheck

    rng = random.Random(21)
    customers = [credit_customer(client, shop, name=f"Random {i}", limit="20000") for i in range(4)]
    ensure_till(client, shop, "cashier")
    ensure_till(client, shop, "manager")
    for step in range(60):
        cust = rng.choice(customers)
        action = rng.choice(["credit", "credit", "cash", "pay", "pay", "order", "return", "void", "reverse"])
        if action == "credit":
            r = credit_sale(client, shop, cust, qty=rng.choice(["1", "2", "3"]),
                            cash=rng.choice([None, None, "50.00"]))
            assert r.status_code in (201, 422), r.text
        elif action == "cash":
            assert sell(client, shop, customer_id=cust["id"]).status_code == 201
        elif action == "pay":
            open_ = client.get(f"{POS}/invoices", headers=shop["fm"], params={"customer_id": cust["id"]}).json()
            owing = sum(Dec(i["total"]) - Dec(i["amount_paid"]) - Dec(i["credited"])
                        for i in open_ if i["status"] in ("issued", "part_paid"))
            if owing > 0:
                amount = min(owing, Dec(rng.choice(["50", "100", "500"])))
                r = client.post(f"{POS}/receipts", headers=shop["fm"], json={
                    "customer_id": cust["id"], "amount": str(amount), "method": rng.choice(["cash", "mobile_money", "bank"]),
                    "branch_id": str(shop["branch_id"]), "external_ref": f"RND{step}{uuid4().hex[:4].upper()}"})
                assert r.status_code == 201, r.text
        elif action == "order":
            q = client.post(f"{POS}/orders", headers=shop["rep"], json={
                "customer_id": cust["id"], "location_id": shop["main"],
                "lines": [{"product_id": shop["cement"], "quantity": str(rng.choice([2, 4]))}]}).json()
            client.post(f"{POS}/orders/{q['id']}/submit", headers=shop["rep"])
            client.post(f"{POS}/orders/{q['id']}/deliver", headers=shop["rep"], json={})
        elif action == "return":
            sales = client.get(f"{POS}/sales", headers=shop["manager"], params={"limit": 30}).json()
            credit_ones = [s for s in sales if s["status"] == "posted"]
            if credit_ones:
                pick = rng.choice(credit_ones)
                detail = client.get(f"{POS}/sales/{pick['id']}", headers=shop["manager"]).json()
                client.post(f"{POS}/sales/{pick['id']}/returns", headers=shop["manager"], json={
                    "lines": [{"sale_line_id": detail["lines"][0]["id"], "quantity": "1"}],
                    "reason_code_id": shop["reasons"]["sale_return"],
                    "refund_method": rng.choice(["credit_note", "cash"])})
        elif action == "void":
            sales = client.get(f"{POS}/sales", headers=shop["manager"], params={"limit": 10}).json()
            if sales:
                client.post(f"{POS}/sales/{rng.choice(sales)['id']}/void", headers=shop["manager"], json={
                    "reason_code_id": shop["reasons"]["void"]})
        elif action == "reverse":
            receipts = [x for x in client.get(f"{POS}/receipts", headers=shop["fm"]).json() if x["status"] == "posted"]
            if receipts:
                client.post(f"{POS}/receipts/{rng.choice(receipts)['id']}/reverse", headers=shop["fm"],
                            json={"reason": "Random mistake"})
    # every ledger agrees
    with system(shop) as s:
        assert CustomerLedgerCheck().run(s) == []
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
    ledger = one(shop, "select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l join finance.account a "
                       "on a.id = l.account_id where a.code = '1100'")
    assert ledger == one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice "
                               "where status in ('issued', 'part_paid')")
    assert one(shop, "select count(*) from pos.sales_invoice where amount_paid + credited > total") == 0
    for cust in customers:
        assert owed(shop, cust) <= Dec(cust["credit_limit"])                                    # never over the limit
