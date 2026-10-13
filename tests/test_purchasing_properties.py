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


# --------------------------------------------------------------------------- corrections under pressure
@pytest.fixture(scope="module")
def fix_shop(client, registry):  # type: ignore[no-untyped-def]
    from tests.stock_helpers import P

    s = make_purchasing_shop(client, registry, "Buy Fix Props Co")
    made = client.post(f"{P}/products", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "sku": "NUT", "name": "Nuts", "base_uom_id": s["uom"],
        "tax_code_id": s["tax"]})
    s["nut"] = made.json()["id"]
    return s


def nut_receipt(client, shop, qty="10", cost="20.00"):  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty=qty, cost=cost, product="nut")
    return order, receive(client, shop, order).json()


def send_back(client, shop, receipt, qty):  # type: ignore[no-untyped-def]
    return client.post(f"{PUR}/receipts/{receipt['id']}/returns", headers=shop["owner"], json={
        "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": qty}],
        "reason_code_id": shop["reasons"]["purchase_return"]})


def test_simultaneous_returns_never_send_back_more_than_arrived(client, fix_shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = nut_receipt(client, fix_shop)
    results = together([lambda: send_back(client, fix_shop, receipt, "4") for _ in range(6)])
    assert Counter(r.status_code for r in results) == {201: 2, 422: 4}
    assert one(fix_shop, "select coalesce(sum(quantity), 0) from purchasing.purchase_return_line where "
                         "receipt_line_id = :l", l=receipt["lines"][0]["id"]) == 8


def test_simultaneous_credit_notes_never_credit_more_than_was_sent_back(client, fix_shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = nut_receipt(client, fix_shop)
    bill = bill_for(client, fix_shop, receipt, invoice="CNRACE-B").json()
    client.post(f"{PUR}/bills/{bill['id']}/submit", headers=fix_shop["owner"])
    ret = send_back(client, fix_shop, receipt, "5").json()
    line = ret["lines"][0]["id"]

    def note(n: int):  # type: ignore[no-untyped-def]
        return client.post(f"{PUR}/bills/{bill['id']}/credit-notes", headers=fix_shop["fm"], json={
            "supplier_credit_no": f"CNRACE-{n}", "credit_date": "2026-10-13",
            "lines": [{"return_line_id": line, "quantity": "2", "unit_cost": "20.00"}]})

    results = together([lambda n=n: note(n) for n in range(6)])
    assert Counter(r.status_code for r in results) == {201: 2, 422: 4}, [r.text for r in results]
    assert one(fix_shop, "select qty_credited from purchasing.purchase_return_line where id = :i", i=line) == 4
    fresh = client.get(f"{PUR}/bills/{bill['id']}", headers=fix_shop["fm"]).json()
    assert Dec(fresh["credited"]) == Dec("92.80")                                                    # 2 x (2 x 20 + VAT)


def test_a_bill_reversed_twice_at_once_is_reversed_once(client, fix_shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = nut_receipt(client, fix_shop)
    bill = bill_for(client, fix_shop, receipt, invoice="REVRACE-1").json()
    client.post(f"{PUR}/bills/{bill['id']}/submit", headers=fix_shop["owner"])
    before = balance(fix_shop, "2000")
    results = together([lambda: client.post(f"{PUR}/bills/{bill['id']}/reverse", headers=fix_shop["fm"],
                                            json={"reason": "Wrong"}) for _ in range(5)])
    assert Counter(r.status_code for r in results) == {200: 1, 409: 4}
    assert balance(fix_shop, "2000") == before + Dec("232")
    assert one(fix_shop, "select count(*) from kernel.event_outbox where event_type = 'bill.reversed' and "
                         "aggregate_id = :b", b=bill["id"]) == 1


def test_a_payment_and_a_reversal_racing_leave_the_bill_consistent(client, fix_shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = nut_receipt(client, fix_shop)
    bill = bill_for(client, fix_shop, receipt, invoice="PAYREV-1").json()
    client.post(f"{PUR}/bills/{bill['id']}/submit", headers=fix_shop["owner"])
    paid = client.post(f"{PUR}/bills/{bill['id']}/pay", headers=fix_shop["fm"], json={"amount": "100", "method": "cash"})
    assert paid.status_code == 200
    payment = client.get(f"{PUR}/bills/{bill['id']}/payments", headers=fix_shop["fm"]).json()[0]["payment_id"]
    results = together([
        lambda: client.post(f"{PUR}/bills/{bill['id']}/reverse-payment", headers=fix_shop["fm"],
                            json={"payment_id": payment, "reason": "Wrong"}),
        lambda: client.post(f"{PUR}/bills/{bill['id']}/pay", headers=fix_shop["fm"],
                            json={"amount": "50", "method": "cash"}),
        lambda: client.post(f"{PUR}/bills/{bill['id']}/reverse-payment", headers=fix_shop["fm"],
                            json={"payment_id": payment, "reason": "Wrong again"}),
    ])
    assert all(r.status_code in (200, 409, 422) for r in results), [r.text for r in results]
    final = client.get(f"{PUR}/bills/{bill['id']}", headers=fix_shop["fm"]).json()
    live = one(fix_shop, "select coalesce(sum(a.amount), 0) from payments.payment_allocation a join payments.payment p "
                         "on p.id = a.payment_id where a.doc_id = :b and p.status = 'posted'", b=bill["id"])
    assert Dec(final["amount_paid"]) == live


def test_random_corrections_keep_the_books_the_stock_and_the_bills_in_agreement(client, fix_shop) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(11)
    for n in range(12):
        order, receipt = nut_receipt(client, fix_shop, qty=rng.choice(["6", "10", "20"]), cost="20.00")
        qty = Dec(receipt["lines"][0]["quantity"])
        bill = None
        if rng.random() < 0.8:
            made = bill_for(client, fix_shop, receipt, invoice=f"RC-{n}").json()
            bill = client.post(f"{PUR}/bills/{made['id']}/submit", headers=fix_shop["owner"]).json()
            assert bill["status"] == "posted"
        if rng.random() < 0.7:
            back = (qty / rng.choice([2, 3])).quantize(Dec("1"))
            ret = send_back(client, fix_shop, receipt, str(back))
            assert ret.status_code == 201, ret.text
            if bill is not None and rng.random() < 0.8:
                c = client.post(f"{PUR}/bills/{bill['id']}/credit-notes", headers=fix_shop["fm"], json={
                    "supplier_credit_no": f"RCN-{n}", "credit_date": "2026-10-13",
                    "lines": [{"return_line_id": ret.json()["lines"][0]["id"], "quantity": str(back),
                               "unit_cost": "20.00"}]})
                assert c.status_code == 201, c.text
        if bill is not None and rng.random() < 0.3:
            client.post(f"{PUR}/bills/{bill['id']}/pay", headers=fix_shop["fm"], json={"amount": "10", "method": "cash"})
        if bill is not None and rng.random() < 0.3:
            payments = client.get(f"{PUR}/bills/{bill['id']}/payments", headers=fix_shop["fm"]).json()
            live = [p for p in payments if p["status"] == "posted"]
            if live:
                client.post(f"{PUR}/bills/{bill['id']}/reverse-payment", headers=fix_shop["fm"],
                            json={"payment_id": live[0]["payment_id"], "reason": "Mistake"})
        if bill is not None and rng.random() < 0.25:
            client.post(f"{PUR}/bills/{bill['id']}/reverse", headers=fix_shop["fm"], json={"reason": "Mistake"})
        assert order["id"]
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=fix_shop["owner"], params={
        "company_id": str(fix_shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    assert one(fix_shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(fix_shop, "1200")
    owed = one(fix_shop, "select coalesce(sum(total - amount_paid - credited), 0) from purchasing.supplier_bill "
                         "where status in ('posted', 'part_paid')")
    assert -balance(fix_shop, "2000") == owed
    # goods received not invoiced: what arrived, less what was sent back, less what live bills cleared, plus what
    # credit notes cleared for goods sent back
    arrived = one(fix_shop, "select coalesce(sum(round(quantity * unit_cost, 2)), 0) from "
                            "purchasing.goods_receipt_line")
    returned = one(fix_shop, "select coalesce(sum(stock_value), 0) from purchasing.purchase_return_line")
    cleared = one(fix_shop, "select coalesce(sum((posted_figures->>'stock_received_value')::numeric), 0) from "
                            "purchasing.supplier_bill where status in ('posted', 'part_paid', 'paid')")
    credited = one(fix_shop, "select coalesce(sum(round(r.stock_value * l.quantity / r.quantity, 2)), 0) from "
                             "purchasing.supplier_credit_note_line l join purchasing.purchase_return_line r on "
                             "r.id = l.return_line_id")
    assert -balance(fix_shop, "2100") == arrived - returned - cleared + credited
    # billed can exceed received only by goods sent back that the supplier has not yet credited
    assert one(fix_shop, "select count(*) from purchasing.purchase_order_line o where o.qty_received > o.quantity "
                         "or o.qty_received < 0 or o.qty_billed > o.qty_received + coalesce((select sum(r.quantity - "
                         "r.qty_credited) from purchasing.purchase_return_line r join purchasing.goods_receipt_line g "
                         "on g.id = r.receipt_line_id where g.order_line_id = o.id), 0)") == 0
