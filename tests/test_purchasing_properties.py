"""Purchasing under pressure: simultaneous receipts, bills and payments never take more than exists, duplicates are
refused, the database guards posted records, and a random history keeps stock, books and bills in agreement."""

import random
from collections import Counter
from decimal import Decimal as Dec  # noqa: N817

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.finance_helpers import balance
from tests.payments_helpers import one
from tests.purchasing_helpers import PUR, approved_order, bill_for, make_purchasing_shop, receive
from tests.stock_helpers import system
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_purchasing_shop(client, registry, "Buy Props Co")


def posted(client, shop, invoice, qty="10", cost="50.00"):  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty=qty, cost=cost)
    receipt = receive(client, shop, order).json()
    bill = bill_for(client, shop, receipt, invoice=invoice).json()
    return client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).json()


def test_two_receipts_cannot_both_take_the_last_units(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10")
    results = together([lambda: receive(client, shop, order, qty="6") for _ in range(4)])
    assert Counter(r.status_code for r in results) == {201: 1, 422: 3}
    line = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(line["qty_received"]) == 6
    assert one(shop, "select coalesce(sum(quantity), 0) from purchasing.goods_receipt_line where order_line_id = :l",
               l=line["id"]) == 6


def test_the_same_goods_cannot_be_billed_twice_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10")
    receipt = receive(client, shop, order).json()
    bills = [bill_for(client, shop, receipt, invoice=f"RACE-{i}").json() for i in range(4)]
    results = together([lambda b=b: client.post(f"{PUR}/bills/{b['id']}/submit", headers=shop["owner"]) for b in bills])
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    states = Counter((r.json()["status"], r.json()["match_status"]) for r in results)
    assert states == {("posted", "matched"): 1, ("pending_approval", "exception"): 3}
    line = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(line["qty_billed"]) == 10


def test_payments_at_once_never_exceed_what_is_owed(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = posted(client, shop, "PAYRACE-1", qty="10")                                     # 580
    pay = lambda: client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"],  # noqa: E731
                              json={"amount": "200.00", "method": "cash"})
    results = together([pay for _ in range(6)])
    ok = sum(1 for r in results if r.status_code == 200)
    assert ok == 2                                                                         # 200 + 200, the third is too much
    final = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
    assert Dec(final["amount_paid"]) == 400 and final["status"] == "part_paid"
    assert one(shop, "select coalesce(sum(a.amount), 0) from payments.payment_allocation a where a.doc_id = :b",
               b=bill["id"]) == 400


def test_duplicate_suppliers_and_invoice_numbers_leave_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "code": "RACESUP", "name": "Race Supplier"}
    results = together([lambda: client.post(f"{PUR}/suppliers", headers=shop["owner"], json=body) for _ in range(6)])
    assert Counter(r.status_code for r in results) == {201: 1, 409: 5}
    receipt = receive(client, shop, approved_order(client, shop, qty="30")).json()
    results = together([lambda: bill_for(client, shop, receipt, invoice="SAME-INV", qty="1") for _ in range(6)])
    assert Counter(r.status_code for r in results) == {201: 1, 409: 5}, [r.text for r in results]


def test_posted_records_are_guarded_by_the_database(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = posted(client, shop, "GUARD-1", qty="2")
    receipt_line = one(shop, "select id::text from purchasing.goods_receipt_line order by created_at desc limit 1")
    attempts = [
        ("update purchasing.goods_receipt_line set quantity = 99 where id = :i", receipt_line),
        ("delete from purchasing.goods_receipt_line where id = :i", receipt_line),
        ("delete from purchasing.goods_receipt where id = (select receipt_id from purchasing.goods_receipt_line "
         "where id = :i)", receipt_line),
        ("update purchasing.supplier_bill_line set quantity = 99 where bill_id = :i", bill["id"]),
        ("delete from purchasing.supplier_bill_line where bill_id = :i", bill["id"]),
        ("delete from purchasing.supplier_bill where id = :i", bill["id"]),
        ("update purchasing.supplier_price set unit_cost = 1 where id = (select id from purchasing.supplier_price "
         "limit 1) and :i is not null", bill["id"]),
        ("delete from purchasing.supplier_price where :i is not null", bill["id"]),
    ]
    for sql, value in attempts:
        with pytest.raises(DBAPIError), system(shop) as s:
            s.execute(text(sql), {"i": value})


def test_random_trading_keeps_stock_books_and_bills_in_agreement(client, shop) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(7)
    for n in range(14):
        qty = rng.choice(["4", "10", "25"])
        cost = rng.choice(["20.00", "50.00", "75.50"])
        order = approved_order(client, shop, qty=qty, cost=cost)
        parts = rng.choice([[Dec(qty)], [Dec(qty) / 2, Dec(qty) / 2], [Dec(qty) / 4, Dec(qty) * 3 / 4]])
        receipts = [receive(client, shop, order, qty=str(p)).json() for p in parts]
        assert all("id" in r for r in receipts), receipts
        for i, receipt in enumerate(receipts):
            if rng.random() < 0.7:
                exact = rng.random() < 0.8
                unit = receipt["lines"][0]["unit_cost"] if exact else str(Dec(cost) * Dec("1.1"))
                bill = bill_for(client, shop, receipt, cost=unit, invoice=f"RND-{n}-{i}").json()
                done = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).json()
                if done["status"] == "pending_approval":
                    client.post(f"{PUR}/bills/{bill['id']}/approve-exception", headers=shop["fm"], json={
                        "reason_code_id": shop["reasons"]["bill_exception"]})
                done = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
                assert done["status"] == "posted"
                if rng.random() < 0.5:
                    amount = (Dec(done["total"]) * Dec(rng.choice(["0.25", "0.5", "1"]))).quantize(Dec("0.01"))
                    assert client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={
                        "amount": str(amount), "method": "cash"}).status_code == 200
    # stock in the ledger equals stock in the books; the books balance
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    # what is owed on the bills equals the payables account
    owed = one(shop, "select coalesce(sum(total - amount_paid), 0) from purchasing.supplier_bill "
                     "where status in ('posted', 'part_paid')")
    assert -balance(shop, "2000") == owed
    # the goods received not yet invoiced equal the received value of what is unbilled
    unbilled = one(shop, "select coalesce(sum(round(r.quantity * r.unit_cost, 2)), 0) from purchasing.goods_receipt_line r") \
        - one(shop, "select coalesce(sum(round(b.quantity * r.unit_cost, 2)), 0) from purchasing.supplier_bill_line b "
                    "join purchasing.supplier_bill sb on sb.id = b.bill_id join purchasing.goods_receipt_line r on "
                    "r.id = b.receipt_line_id where sb.status in ('posted', 'part_paid', 'paid')")
    landed = one(shop, "select coalesce(sum(landed_cost), 0) from purchasing.goods_receipt")
    assert -balance(shop, "2100") == unbilled + landed
    # billed never exceeds received, received never exceeds ordered
    assert one(shop, "select count(*) from purchasing.purchase_order_line where qty_billed > qty_received "
                     "or qty_received > quantity") == 0
    assert one(shop, "select count(*) from purchasing.supplier_bill where status in ('posted', 'part_paid', 'paid')") > 5
