"""Selling on credit, invoices, customers paying, and getting it all back to reconcile."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import PAY, one
from tests.pos_helpers import (
    POS,
    credit_customer,
    credit_sale,
    ensure_till,
    line,
    make_sales_shop,
    sell,
    stock,
)

CRM = "/api/v1/crm"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_sales_shop(client, registry, "Credit Co", stock="500")


def invoice_of(client, shop, sale):  # type: ignore[no-untyped-def]
    found = client.get(f"{POS}/invoices", headers=shop["fm"], params={"limit": 200}).json()
    return next(i for i in found if i["sale_id"] == sale["id"])


def owed(shop, customer) -> Dec:  # type: ignore[no-untyped-def]
    return one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where "
                     "customer_id = :c and status in ('issued', 'part_paid')", c=customer["id"])


# --------------------------------------------------------------------------- selling on credit
def test_a_sale_on_credit_makes_an_invoice_and_the_customer_owes(client, shop) -> None:  # type: ignore[no-untyped-def]
    mama = credit_customer(client, shop, limit="5000", terms=14)
    before = {c: balance(shop, c) for c in ("1010", "1100", "4000", "2200", "5000", "1200")}
    stock0 = stock(shop)
    r = credit_sale(client, shop, mama, qty="2")
    assert r.status_code == 201, r.text
    sale = r.json()
    assert Dec(sale["total"]) == 232 and [p["method"] for p in sale["payments"]] == ["credit"]
    assert sale["payments"][0]["payment_id"] is None                                  # no money changed hands
    inv = invoice_of(client, shop, sale)
    assert inv["kind"] == "credit_sale" and Dec(inv["total"]) == 232 and Dec(inv["tax_total"]) == 32
    assert inv["customer_id"] == mama["id"] and inv["status"] == "issued" and inv["number"].startswith("INV-HQ-")
    assert inv["due_date"] == str(__import__("datetime").date.fromisoformat(sale["business_date"])
                                  + __import__("datetime").timedelta(days=14))
    assert stock(shop) == stock0 - 2
    after = {c: balance(shop, c) for c in before}
    assert after["1100"] - before["1100"] == 232 and after["1010"] == before["1010"]            # owed, not cash
    assert after["4000"] - before["4000"] == -200 and after["2200"] - before["2200"] == -32
    assert after["5000"] - before["5000"] == 100 and after["1200"] - before["1200"] == -100     # the cost still counts
    assert owed(shop, mama) == 232
    receivable = one(shop, "select coalesce(sum(debit - credit), 0) from finance.journal_line where party_id = :c",
                     c=mama["id"])
    assert receivable == 232                                                                    # the customer's own ledger


def test_part_cash_part_credit(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Part Payer")
    r = credit_sale(client, shop, cust, qty="3", cash="100.00")
    assert r.status_code == 201, r.text
    assert {p["method"]: Dec(p["amount"]) for p in r.json()["payments"]} == {"cash": 100, "credit": 248}
    inv = invoice_of(client, shop, r.json())
    assert Dec(inv["total"]) == 248 and Dec(inv["tax_total"]) == Dec("34.21")                   # VAT in proportion
    assert one(shop, "select count(*) from payments.payment where id in (select payment_id from pos.sale_payment "
                     "where sale_id = :s)", s=r.json()["id"]) == 1                              # only the cash is a payment


def test_credit_is_refused_when_it_should_be(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Limited", limit="300")
    assert credit_sale(client, shop, cust, qty="2").status_code == 201                          # 232 of 300
    over = credit_sale(client, shop, cust, qty="1")                                             # 116 more: 348 > 300
    assert over.status_code == 422 and "credit limit" in over.json()["message"]
    assert owed(shop, cust) == 232
    assert credit_sale(client, shop, cust, qty="1", cash="50.00").status_code == 201            # 66 on credit: 298
    none = credit_customer(client, shop, name="No credit", limit="0", terms=0)
    assert credit_sale(client, shop, none, qty="1").status_code == 422
    client.patch(f"{CRM}/customers/{cust['id']}", headers=shop["owner"], json={"status": "on_hold"})
    held = credit_sale(client, shop, cust, qty="1")
    assert held.status_code == 422 and "on hold" in held.json()["message"]
    cash = sell(client, shop, customer_id=cust["id"])                                           # cash is always fine
    assert cash.status_code == 201
    no_customer = sell(client, shop, payments=[{"method": "credit", "amount": "116"}])
    assert no_customer.status_code == 422 and "customer" in no_customer.json()["message"]
    stranger = sell(client, shop, payments=[{"method": "credit", "amount": "116"}], customer_id=str(uuid4()))
    assert stranger.status_code == 422


def test_a_customers_group_price_list_applies(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import P

    lst = client.post(f"{P}/price-lists", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Wholesale prices", "customer_group": "Wholesale"})
    assert lst.status_code == 201, lst.text
    client.put(f"{P}/price-lists/{lst.json()['id']}/prices", headers=shop["owner"], json={
        "product_id": shop["cement"], "price": "100.00", "valid_from": "2026-01-01"})
    dealer = credit_customer(client, shop, name="Dealer", customer_group="Wholesale", limit="10000")
    retail = credit_customer(client, shop, name="Walk-in credit", limit="10000")
    cheap = sell(client, shop, customer_id=dealer["id"], payments=[{"method": "cash", "amount": "100.00"}])
    assert cheap.status_code == 201 and Dec(cheap.json()["total"]) == 100
    assert Dec(cheap.json()["lines"][0]["list_price"]) == 100
    normal = sell(client, shop, customer_id=retail["id"])
    assert Dec(normal.json()["total"]) == 116
    other_product = sell(client, shop, lines=[line(shop, "paint", "1")], customer_id=dealer["id"],
                         payments=[{"method": "cash", "amount": "232.00"}])
    assert Dec(other_product.json()["total"]) == 232                                            # the default price covers the rest


# --------------------------------------------------------------------------- customers paying
def test_a_customer_pays_the_oldest_invoices_first(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Pays Oldest", limit="10000")
    first = invoice_of(client, shop, credit_sale(client, shop, cust, qty="2").json())            # 232
    second = invoice_of(client, shop, credit_sale(client, shop, cust, qty="1").json())           # 116
    before = {c: balance(shop, c) for c in ("1010", "1100", "1030")}
    r = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "300.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["number"].startswith("RCT-HQ-") and receipt["payment_id"]
    assert [(a["invoice_id"], Dec(a["amount"])) for a in receipt["allocations"]] == [(first["id"], Dec(232)),
                                                                                    (second["id"], Dec(68))]
    paid = client.get(f"{POS}/invoices/{first['id']}", headers=shop["fm"]).json()
    part = client.get(f"{POS}/invoices/{second['id']}", headers=shop["fm"]).json()
    assert paid["status"] == "paid" and part["status"] == "part_paid" and Dec(part["amount_paid"]) == 68
    after = {c: balance(shop, c) for c in before}
    assert after["1010"] - before["1010"] == 300 and after["1100"] - before["1100"] == -300
    assert owed(shop, cust) == 48
    pay = client.get(f"{PAY}/payments/{receipt['payment_id']}", headers=shop["fm"]).json()
    assert pay["direction"] == "in" and pay["method"] == "cash" and Dec(pay["amount"]) == 300
    rest = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "48.00", "method": "mpesa", "branch_id": str(shop["branch_id"]),
        "external_ref": "RCT9MPESA"})
    assert rest.status_code == 201, rest.text
    assert owed(shop, cust) == 0
    assert balance(shop, "1030") - before["1030"] == 48


def test_naming_the_invoices_and_not_overpaying(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Names Invoices", limit="10000")
    a = invoice_of(client, shop, credit_sale(client, shop, cust, qty="1").json())
    b = invoice_of(client, shop, credit_sale(client, shop, cust, qty="2").json())
    path = f"{POS}/receipts"
    body = {"customer_id": cust["id"], "method": "cash", "branch_id": str(shop["branch_id"])}
    for name, change in {
        "more than owed": {"amount": "400.00"},
        "zero": {"amount": "0"}, "cents": {"amount": "10.005"},
        "allocations do not add up": {"amount": "100.00", "allocations": [{"invoice_id": b["id"], "amount": "90"}]},
        "more than the invoice owes": {"amount": "200.00", "allocations": [{"invoice_id": a["id"], "amount": "200"}]},
        "another customer's invoice": {"amount": "10.00", "allocations": [{"invoice_id": str(uuid4()), "amount": "10"}]},
        "invoice twice": {"amount": "20.00", "allocations": [{"invoice_id": a["id"], "amount": "10"},
                                                             {"invoice_id": a["id"], "amount": "10"}]},
        "bad method": {"amount": "10.00", "method": "bitcoin"},
        "no account": {"amount": "10.00", "method": "card", "branch_id": str(shop["juja"])},
    }.items():
        assert client.post(path, headers=shop["fm"], json={**body, **change}).status_code == 422, name
    ok = client.post(path, headers=shop["fm"], json={**body, "amount": "150.00", "allocations": [
        {"invoice_id": b["id"], "amount": "150"}]})
    assert ok.status_code == 201
    assert client.get(f"{POS}/invoices/{a['id']}", headers=shop["fm"]).json()["status"] == "issued"
    assert client.post(path, headers=shop["fm"], json={**body, "amount": "10", "customer_id": str(uuid4())}
                       ).status_code in (404, 422)
    assert client.post(path, headers=shop["storekeeper"], json={**body, "amount": "10"}).status_code == 403
    clean = credit_customer(client, shop, name="Owes nothing")
    nothing = client.post(path, headers=shop["fm"], json={**body, "customer_id": clean["id"], "amount": "10"})
    assert nothing.status_code == 422


def test_cash_paid_at_the_till_counts_in_the_drawer(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Pays At Till", limit="10000")
    inv = invoice_of(client, shop, credit_sale(client, shop, cust, qty="1").json())
    till = ensure_till(client, shop, "cashier")
    before = client.get(f"{POS}/tills/{till}/report", headers=shop["cashier"]).json()
    r = client.post(f"{POS}/receipts", headers=shop["cashier"], json={
        "customer_id": cust["id"], "amount": "116.00", "method": "cash", "till_session_id": till})
    assert r.status_code == 201, r.text
    after = client.get(f"{POS}/tills/{till}/report", headers=shop["cashier"]).json()
    assert Dec(after["expected_cash"]) - Dec(before["expected_cash"]) == 116
    assert client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()["status"] == "paid"
    other = client.post(f"{POS}/receipts", headers=shop["cashier"], json={
        "customer_id": cust["id"], "amount": "1.00", "method": "cash", "till_session_id": str(uuid4())})
    assert other.status_code == 422


def test_a_reversed_payment_makes_the_invoices_owed_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Bounced", limit="10000")
    inv = invoice_of(client, shop, credit_sale(client, shop, cust, qty="2").json())
    r = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "232.00", "method": "cash", "branch_id": str(shop["branch_id"])}).json()
    assert owed(shop, cust) == 0
    before = {c: balance(shop, c) for c in ("1010", "1100")}
    path = f"{POS}/receipts/{r['id']}/reverse"
    assert client.post(path, headers=shop["storekeeper"], json={"reason": "x"}).status_code == 403
    assert client.post(path, headers=shop["fm"], json={"reason": " "}).status_code == 422
    done = client.post(path, headers=shop["fm"], json={"reason": "Cheque bounced"})
    assert done.status_code == 200 and done.json()["status"] == "reversed"
    assert client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()["status"] == "issued"
    assert owed(shop, cust) == 232
    after = {c: balance(shop, c) for c in before}
    assert after["1010"] - before["1010"] == -232 and after["1100"] - before["1100"] == 232
    assert client.post(path, headers=shop["fm"], json={"reason": "again"}).status_code == 409
    # reversing it directly in Payments does the same
    r2 = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "100.00", "method": "cash", "branch_id": str(shop["branch_id"])}).json()
    assert client.post(f"{PAY}/payments/{r2['payment_id']}/reverse", headers=shop["fm"], json={"reason": "Wrong"}
                       ).status_code == 200
    assert client.get(f"{POS}/receipts/{r2['id']}", headers=shop["fm"]).json()["status"] == "reversed"
    assert owed(shop, cust) == 232


# --------------------------------------------------------------------------- returns and voids of credit sales
def test_returning_goods_bought_on_credit_reduces_what_is_owed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Returns Goods", limit="10000")
    sale = credit_sale(client, shop, cust, qty="3").json()                                       # 348 owed
    line_id = sale["lines"][0]["id"]
    path = f"{POS}/sales/{sale['id']}/returns"
    body = {"lines": [{"sale_line_id": line_id, "quantity": "1"}], "reason_code_id": shop["reasons"]["sale_return"]}
    cash = client.post(path, headers=shop["manager"], json={**body, "refund_method": "cash"})
    assert cash.status_code == 422 and "credit note" in cash.json()["message"]
    ensure_till(client, shop, "manager")
    before = {c: balance(shop, c) for c in ("1010", "1100", "4100", "2200", "1200")}
    stock0 = stock(shop)
    ok = client.post(path, headers=shop["manager"], json={**body, "refund_method": "credit_note"})
    assert ok.status_code == 201 and ok.json()["status"] == "posted", ok.text
    assert owed(shop, cust) == 232 and stock(shop) == stock0 + 1
    after = {c: balance(shop, c) for c in before}
    assert after["1100"] - before["1100"] == -116 and after["1010"] == before["1010"]
    assert after["4100"] - before["4100"] == 100 and after["2200"] - before["2200"] == 16
    inv = invoice_of(client, shop, sale)
    assert Dec(inv["credited"]) == 116 and inv["status"] == "part_paid"
    too_much = client.post(path, headers=shop["manager"], json={
        "lines": [{"sale_line_id": line_id, "quantity": "2"}], "reason_code_id": shop["reasons"]["sale_return"],
        "refund_method": "credit_note"})
    assert too_much.status_code == 201                                                          # 232 owed, 232 credited
    assert owed(shop, cust) == 0
    assert client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()["status"] == "paid"
    plain = sell(client, shop)
    refused = client.post(f"{POS}/sales/{plain.json()['id']}/returns", headers=shop["manager"], json={
        "lines": [{"sale_line_id": plain.json()["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": shop["reasons"]["sale_return"], "refund_method": "credit_note"})
    assert refused.status_code == 422                                                           # a cash sale has no account


def test_once_the_customer_has_paid_the_refund_is_in_cash(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Paid Then Returns", limit="10000")
    sale = credit_sale(client, shop, cust, qty="1").json()
    client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "116.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    ensure_till(client, shop, "manager")
    body = {"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
            "reason_code_id": shop["reasons"]["sale_return"]}
    path = f"{POS}/sales/{sale['id']}/returns"
    assert client.post(path, headers=shop["manager"], json={**body, "refund_method": "credit_note"}).status_code == 422
    assert client.post(path, headers=shop["manager"], json={**body, "refund_method": "cash"}).status_code == 201


def test_voiding_a_credit_sale_cancels_its_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Voided Sale", limit="10000")
    sale = credit_sale(client, shop, cust, qty="2").json()
    inv = invoice_of(client, shop, sale)
    receipt = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "50.00", "method": "cash", "branch_id": str(shop["branch_id"])}).json()
    void = f"{POS}/sales/{sale['id']}/void"
    body = {"reason_code_id": shop["reasons"]["void"]}
    refused = client.post(void, headers=shop["manager"], json=body)
    assert refused.status_code == 422 and "paid or been credited" in refused.json()["message"]
    client.post(f"{POS}/receipts/{receipt['id']}/reverse", headers=shop["fm"], json={"reason": "Mistake"})
    before = {c: balance(shop, c) for c in ("1100", "1200")}
    done = client.post(void, headers=shop["manager"], json=body)
    assert done.status_code == 200, done.text
    assert client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()["status"] == "cancelled"
    assert owed(shop, cust) == 0
    assert balance(shop, "1100") - before["1100"] == -232 and balance(shop, "1200") - before["1200"] == 100


# --------------------------------------------------------------------------- offline
def test_a_credit_sale_made_offline_is_accepted_and_raised_if_over_the_limit(client, shop) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    cust = credit_customer(client, shop, name="Offline Credit", limit="100")
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": "OFC1", "name": "Offline credit", "location_id": shop["main"]}).json()
    key = dev["key"]
    who = shop["user"]("offlinecredit", "Cashier", shop["branch_id"])
    till = str(uuid4())
    at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    ops = [{"type": "till_open", "local_id": till, "at": at, "opening_float": "0"},
           {"type": "sale", "local_id": str(uuid4()), "till_local_id": till, "at": at,
            "number": "POS-HQ-OFC1-L000001", "customer_id": cust["id"],
            "lines": [{"product_id": shop["cement"], "quantity": "2", "unit_price": "116.00"}],
            "payments": [{"method": "credit", "amount": "232.00"}]},
           {"type": "till_close", "local_id": str(uuid4()), "till_local_id": till, "at": at, "counted_cash": "0"}]
    r = client.post(f"{POS}/sync/upload", headers={**who, "X-Device-Key": key}, json={"ops": ops})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["status"] for x in results] == ["ok", "ok", "ok"], results
    assert any(w.startswith("over_credit_limit") for w in results[1]["warnings"])
    assert owed(shop, cust) == 232                                                              # it was sold, so it is owed
    kinds = {i["kind"] for i in client.get("/api/v1/exceptions", headers=shop["owner"], params={"limit": 500}).json()}
    assert "offline_over_credit_limit" in kinds
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'customer.over_limit_attempt'") >= 1
    assert client.post(f"{POS}/sync/upload", headers={**who, "X-Device-Key": key}, json={"ops": ops}
                       ).json()["results"][1]["status"] == "duplicate"


# --------------------------------------------------------------------------- it all reconciles
def test_the_customer_ledger_equals_the_invoices_and_the_receivable_account(client, shop) -> None:  # type: ignore[no-untyped-def]
    ledger = one(shop, "select coalesce(sum(debit - credit), 0) from finance.journal_line l join finance.account a on "
                       "a.id = l.account_id where a.code = '1100'")
    invoices_owed = one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice "
                              "where status in ('issued', 'part_paid')")
    assert ledger == invoices_owed
    by_party = one(shop, "select coalesce(sum(d), 0) from (select sum(debit - credit) as d from finance.journal_line "
                         "l join finance.account a on a.id = l.account_id where a.code = '1100' and l.party_id is not "
                         "null group by l.party_id) x")
    assert by_party == ledger
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
