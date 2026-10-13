"""Money a customer pays in advance: held on their account, applied to invoices later, or given back."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import PAY
from tests.pos_helpers import POS, credit_customer, credit_sale, ensure_till, make_sales_shop
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_sales_shop(client, registry, "Advance Co", stock="500")


def pay(client, shop, cust, amount, method="cash", who="fm", **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{POS}/receipts", headers=shop[who], json={
        "customer_id": cust["id"], "amount": amount, "method": method, "branch_id": str(shop["branch_id"]), **kw})


def bal(client, shop, cust):  # type: ignore[no-untyped-def]
    return client.get(f"{POS}/customers/{cust['id']}/balance", headers=shop["fm"]).json()


def ledger_ok(shop) -> list[str]:  # type: ignore[no-untyped-def]
    from ziira.modules.pos.hooks import CustomerLedgerCheck

    with system(shop) as s:
        return CustomerLedgerCheck().run(s)


def test_an_advance_payment_puts_the_customers_account_in_credit(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Prepaid", limit="1000")
    before = {c: balance(shop, c) for c in ("1010", "1100")}
    refused = pay(client, shop, cust, "500.00")
    assert refused.status_code == 422 and "hold_balance" in refused.json()["message"]       # not by accident
    ok = pay(client, shop, cust, "500.00", hold_balance=True)
    assert ok.status_code == 201, ok.text
    r = ok.json()
    assert Dec(r["unallocated"]) == 500 and r["allocations"] == [] and r["number"].startswith("RCT-")
    after = {c: balance(shop, c) for c in before}
    assert after["1010"] - before["1010"] == 500 and after["1100"] - before["1100"] == -500    # cash in, account in credit
    b = bal(client, shop, cust)
    assert (Dec(b["owes"]), Dec(b["credit_on_account"]), Dec(b["invoices_owed"])) == (-500, 500, 0)
    assert Dec(b["available"]) == 1500                                                           # 1000 limit + 500 in credit
    payment = client.get(f"{PAY}/payments/{r['payment_id']}", headers=shop["fm"]).json()
    assert Dec(payment["amount"]) == 500
    assert ledger_ok(shop) == []


def test_an_overpayment_keeps_the_difference_when_asked(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Overpays", limit="5000")
    inv = client.get(f"{POS}/invoices/{credit_sale(client, shop, cust, qty='1').json()['id']}", headers=shop["fm"])
    sale = credit_sale(client, shop, cust, qty="2").json()
    assert sale["id"] and inv.status_code in (200, 404)
    r = pay(client, shop, cust, "400.00", hold_balance=True)                                    # owes 116 + 232 = 348
    assert r.status_code == 201, r.text
    assert Dec(r.json()["unallocated"]) == 52 and sum(Dec(a["amount"]) for a in r.json()["allocations"]) == 348
    b = bal(client, shop, cust)
    assert (Dec(b["invoices_owed"]), Dec(b["credit_on_account"]), Dec(b["owes"])) == (0, 52, -52)
    named = credit_sale(client, shop, cust, qty="1").json()
    invoice = next(i for i in client.get(f"{POS}/invoices", headers=shop["fm"], params={"customer_id": cust["id"],
                                                                                         "status": "issued"}).json())
    partial = pay(client, shop, cust, "300.00", allocations=[{"invoice_id": invoice["id"], "amount": "100"}],
                  hold_balance=True)
    assert partial.status_code == 201 and Dec(partial.json()["unallocated"]) == 200 and named["id"]
    bad = pay(client, shop, cust, "300.00", allocations=[{"invoice_id": invoice["id"], "amount": "100"}])
    assert bad.status_code == 422                                                                # does not add up
    assert ledger_ok(shop) == []


def test_credit_on_account_is_applied_to_invoices_later(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Applies Later", limit="5000")
    paid = pay(client, shop, cust, "300.00", hold_balance=True).json()
    credit_sale(client, shop, cust, qty="2")                                                    # 232 invoice
    credit_sale(client, shop, cust, qty="1")                                                    # 116 invoice
    before = {c: balance(shop, c) for c in ("1010", "1100", "4000")}
    done = client.post(f"{POS}/customers/{cust['id']}/apply-credit", headers=shop["fm"], json={})
    assert done.status_code == 200, done.text
    assert [(x["receipt"], Dec(x["amount"])) for x in done.json()] == [(paid["number"], Dec(232)), (paid["number"],
                                                                                                    Dec(68))]
    after = {c: balance(shop, c) for c in before}
    assert after == before                                                                       # no money, no entry
    b = bal(client, shop, cust)
    assert (Dec(b["credit_on_account"]), Dec(b["invoices_owed"]), Dec(b["owes"])) == (0, 48, 48)
    invoices = client.get(f"{POS}/invoices", headers=shop["fm"], params={"customer_id": cust["id"]}).json()
    assert sorted(i["status"] for i in invoices) == ["paid", "part_paid"]
    assert client.post(f"{POS}/customers/{cust['id']}/apply-credit", headers=shop["fm"], json={}).status_code == 422
    assert ledger_ok(shop) == []


def test_applying_to_named_invoices_and_limits(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Applies Named", limit="5000")
    pay(client, shop, cust, "150.00", hold_balance=True)
    a = credit_sale(client, shop, cust, qty="1").json()
    b = credit_sale(client, shop, cust, qty="2").json()
    invs = {i["sale_id"]: i for i in client.get(f"{POS}/invoices", headers=shop["fm"],
                                                 params={"customer_id": cust["id"]}).json()}
    path = f"{POS}/customers/{cust['id']}/apply-credit"
    for body in ({"allocations": [{"invoice_id": invs[b["id"]]["id"], "amount": "200"}]},          # more than is held
                 {"allocations": [{"invoice_id": invs[a["id"]]["id"], "amount": "200"}]},          # more than owed
                 {"allocations": [{"invoice_id": str(uuid4()), "amount": "10"}]},
                 {"allocations": [{"invoice_id": invs[a["id"]]["id"], "amount": "10"}] * 2}):
        assert client.post(path, headers=shop["fm"], json=body).status_code == 422, body
    ok = client.post(path, headers=shop["fm"], json={"allocations": [{"invoice_id": invs[b["id"]]["id"],
                                                                      "amount": "150"}]})
    assert ok.status_code == 200
    assert client.get(f"{POS}/invoices/{invs[b['id']]['id']}", headers=shop["fm"]).json()["status"] == "part_paid"
    assert client.post(path, headers=shop["storekeeper"], json={}).status_code == 403
    other = credit_customer(client, shop, name="Nothing Held")
    assert client.post(f"{POS}/customers/{other['id']}/apply-credit", headers=shop["fm"], json={}).status_code == 422


def test_giving_an_advance_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Wants Money Back", limit="1000")
    receipt = pay(client, shop, cust, "800.00", method="mpesa", hold_balance=True, external_ref="ADV1MPESA").json()
    before = {c: balance(shop, c) for c in ("1030", "1100")}
    path = f"{POS}/receipts/{receipt['id']}/refund"
    for body in ({"amount": "900", "method": "mpesa", "reason": "x"}, {"amount": "0", "method": "mpesa", "reason": "x"},
                 {"amount": "100", "method": "card", "reason": "x"}, {"amount": "100", "method": "mpesa", "reason": " "},
                 {"amount": "100", "method": "cash", "reason": "x"}):                            # no open till
        assert client.post(path, headers=shop["fm"], json=body).status_code == 422, body
    assert client.post(path, headers=shop["storekeeper"], json={"amount": "100", "method": "mpesa",
                                                                 "reason": "x"}).status_code == 403
    r = client.post(path, headers=shop["fm"], json={"amount": "300.00", "method": "mpesa", "reason": "Cancelled order",
                                                    "external_ref": "REFUND1"})
    assert r.status_code == 201, r.text
    refund = r.json()
    assert refund["number"].startswith("RFD-") and Dec(refund["amount"]) == 300
    after = {c: balance(shop, c) for c in before}
    assert after["1030"] - before["1030"] == -300 and after["1100"] - before["1100"] == 300
    got = client.get(f"{POS}/receipts/{receipt['id']}", headers=shop["fm"]).json()
    assert (Dec(got["unallocated"]), Dec(got["refunded"])) == (500, 300)
    out = client.get(f"{PAY}/payments/{refund['payment_id']}", headers=shop["fm"]).json()
    assert out["direction"] == "out" and Dec(out["amount"]) == 300
    assert refund["id"] in {x["id"] for x in client.get(f"{POS}/refunds", headers=shop["fm"],
                                                         params={"customer_id": cust["id"]}).json()}
    blocked = client.post(f"{POS}/receipts/{receipt['id']}/reverse", headers=shop["fm"], json={"reason": "x"})
    assert blocked.status_code == 422 and "refund" in blocked.json()["message"]
    # reversing the refund puts the money back on account
    back = client.post(f"{POS}/refunds/{refund['id']}/reverse", headers=shop["fm"], json={"reason": "Failed to send"})
    assert back.status_code == 200 and back.json()["status"] == "reversed"
    assert balance(shop, "1100") - before["1100"] == 0 and balance(shop, "1030") - before["1030"] == 0
    got = client.get(f"{POS}/receipts/{receipt['id']}", headers=shop["fm"]).json()
    assert (Dec(got["unallocated"]), Dec(got["refunded"])) == (800, 0)
    assert client.post(f"{POS}/refunds/{refund['id']}/reverse", headers=shop["fm"], json={"reason": "x"}
                       ).status_code == 409
    assert ledger_ok(shop) == []


def test_a_cash_refund_comes_out_of_the_cashiers_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Cash Refund", limit="1000")
    receipt = pay(client, shop, cust, "200.00", hold_balance=True).json()
    till = ensure_till(client, shop, "cashier")
    before = client.get(f"{POS}/tills/{till}/report", headers=shop["cashier"]).json()
    r = client.post(f"{POS}/receipts/{receipt['id']}/refund", headers=shop["cashier"], json={
        "amount": "50.00", "method": "cash", "reason": "Returned the deposit"})
    assert r.status_code == 201, r.text
    after = client.get(f"{POS}/tills/{till}/report", headers=shop["cashier"]).json()
    assert Dec(after["expected_cash"]) - Dec(before["expected_cash"]) == -50


def test_reversing_an_advance_reverses_what_it_paid_too(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Reverse Advance", limit="5000")
    receipt = pay(client, shop, cust, "300.00", hold_balance=True).json()
    credit_sale(client, shop, cust, qty="2")
    client.post(f"{POS}/customers/{cust['id']}/apply-credit", headers=shop["fm"], json={})      # 232 used, 68 left
    before = {c: balance(shop, c) for c in ("1010", "1100")}
    r = client.post(f"{POS}/receipts/{receipt['id']}/reverse", headers=shop["fm"], json={"reason": "Bounced"})
    assert r.status_code == 200 and r.json()["status"] == "reversed" and Dec(r.json()["unallocated"]) == 0
    b = bal(client, shop, cust)
    assert (Dec(b["invoices_owed"]), Dec(b["credit_on_account"])) == (232, 0)                    # owed again
    after = {c: balance(shop, c) for c in before}
    assert after["1010"] - before["1010"] == -300 and after["1100"] - before["1100"] == 300
    assert ledger_ok(shop) == []
    # reversing in Payments does the same
    second = pay(client, shop, cust, "100.00", hold_balance=True).json()
    assert client.post(f"{PAY}/payments/{second['payment_id']}/reverse", headers=shop["fm"], json={"reason": "Wrong"}
                       ).status_code == 200
    assert client.get(f"{POS}/receipts/{second['id']}", headers=shop["fm"]).json()["status"] == "reversed"
    assert ledger_ok(shop) == []


def test_credit_on_account_widens_what_a_customer_may_take(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Prepaid Limit", limit="200")
    assert credit_sale(client, shop, cust, qty="2").status_code == 422                           # 232 over 200
    pay(client, shop, cust, "100.00", hold_balance=True)
    assert credit_sale(client, shop, cust, qty="2").status_code == 201                           # owes 232 - 100 = 132
    st = client.get(f"{POS}/customers/{cust['id']}/statement", headers=shop["fm"]).json()
    assert Dec(st["closing_balance"]) == Dec(st["owed_now"]) == 132
    from ziira.modules.pos.public import customer_balance

    with system(shop) as s:
        assert customer_balance(s, cust["id"]) == 132
    assert ledger_ok(shop) == []
