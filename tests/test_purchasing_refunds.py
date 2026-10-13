"""When a supplier credits a bill that was already paid, it owes the money back: recording the refund and its reversal."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import PAY, one
from tests.purchasing_helpers import PUR, make_purchasing_shop
from tests.stock_helpers import P
from tests.test_purchasing_corrections import back, credit, moved, order_receipt, post_bill, snapshot


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_purchasing_shop(client, registry, "Refund Co")
    made = client.post(f"{P}/products", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "sku": "BOLT", "name": "Bolts", "base_uom_id": s["uom"],
        "tax_code_id": s["tax"]})
    s["bolt"] = made.json()["id"]
    return s


def paid_and_credited(client, shop, invoice):  # type: ignore[no-untyped-def]
    """A bill for 10 at 50 (580), paid in full, then 4 sent back and credited (232): the supplier owes 232."""
    _, receipt = order_receipt(client, shop)
    bill = post_bill(client, shop, receipt, invoice)
    paid = client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "580.00", "method": "cash"})
    assert paid.json()["status"] == "paid"
    ret = back(client, shop, receipt, "4").json()
    note = credit(client, shop, bill, ret["lines"][0]["id"], "4", no=f"CN-{invoice}")
    assert note.status_code == 201, note.text
    return bill


def test_a_credit_after_payment_leaves_the_supplier_owing_money_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = paid_and_credited(client, shop, "REF-1")
    due = {d["bill_id"]: d for d in client.get(f"{PUR}/refunds-due", headers=shop["fm"]).json()}
    assert Dec(due[bill["id"]]["owed_back"]) == 232 and due[bill["id"]]["supplier_invoice_no"] == "REF-1"
    got = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
    assert got["status"] == "paid" and Dec(got["credited"]) == 232 and Dec(got["refunded"]) == 0
    from tests.stock_helpers import system
    from ziira.modules.purchasing.public import supplier_balance

    with system(shop) as s:
        assert supplier_balance(s, shop["supplier"]) <= Dec(-232)                      # they owe us (at least this)
    over = credit(client, shop, bill, str(uuid4()), "1", no="CN-OVER")
    assert over.status_code == 422


def test_the_refund_arrives_in_parts(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = paid_and_credited(client, shop, "REF-2")
    before, mpesa_before = snapshot(shop), balance(shop, "1030")
    path = f"{PUR}/bills/{bill['id']}/refund"
    first = client.post(path, headers=shop["fm"], json={"amount": "100.00", "method": "bank",
                                                        "payment_account_id": shop["bank"], "external_ref": "EFT-REF-1"})
    assert first.status_code == 201, first.text
    refund = first.json()
    assert refund["number"].startswith("SRF-") and Dec(refund["amount"]) == 100 and refund["status"] == "posted"
    assert moved(before, snapshot(shop)) == {"1020": Dec(100), "2000": Dec(-100)}            # bank in, owed to us down
    pay = client.get(f"{PAY}/payments/{refund['payment_id']}", headers=shop["fm"]).json()
    assert pay["direction"] == "in" and pay["method"] == "bank" and Dec(pay["amount"]) == 100
    due = {d["bill_id"]: d for d in client.get(f"{PUR}/refunds-due", headers=shop["fm"]).json()}
    assert Dec(due[bill["id"]]["owed_back"]) == 132
    rest = client.post(path, headers=shop["fm"], json={"amount": "132.00", "method": "mpesa", "external_ref": "SUPPL1MP"})
    assert rest.status_code == 201, rest.text
    assert bill["id"] not in {d["bill_id"] for d in client.get(f"{PUR}/refunds-due", headers=shop["fm"]).json()}
    assert moved(before, snapshot(shop)) == {"1020": Dec(100), "2000": Dec(-232)}
    assert balance(shop, "1030") - mpesa_before == 132
    assert {x["id"] for x in client.get(f"{PUR}/refunds", headers=shop["fm"],
                                         params={"supplier_id": shop["supplier"]}).json()} >= {refund["id"],
                                                                                              rest.json()["id"]}
    assert client.get(f"{PUR}/refunds/{refund['id']}", headers=shop["fm"]).json()["number"] == refund["number"]
    done = client.post(path, headers=shop["fm"], json={"amount": "1.00", "method": "cash"})
    assert done.status_code == 422 and "owes nothing back" in done.json()["message"]


def test_refund_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = paid_and_credited(client, shop, "REF-3")
    path = f"{PUR}/bills/{bill['id']}/refund"
    for body in ({"amount": "233", "method": "cash"}, {"amount": "0", "method": "cash"},
                 {"amount": "10.005", "method": "cash"}, {"amount": "10", "method": "bitcoin"},
                 {"amount": "10", "method": "mpesa", "payment_account_id": shop["bank"]},
                 {"amount": "10", "method": "bank", "payment_account_id": str(uuid4())}):
        assert client.post(path, headers=shop["fm"], json=body).status_code == 422, body
    ok = {"amount": "10", "method": "cash"}
    assert client.post(path, headers=shop["clerk"], json=ok).status_code == 403
    assert client.post(path, headers=shop["buyer"], json=ok).status_code == 403
    assert client.post(f"{PUR}/bills/{uuid4()}/refund", headers=shop["fm"], json=ok).status_code == 404
    unpaid = post_bill(client, shop, order_receipt(client, shop)[1], "REF-3B")
    assert client.post(f"{PUR}/bills/{unpaid['id']}/refund", headers=shop["fm"], json=ok).status_code == 422


def test_a_refund_that_did_not_arrive_is_reversed(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = paid_and_credited(client, shop, "REF-4")
    path = f"{PUR}/bills/{bill['id']}/refund"
    refund = client.post(path, headers=shop["fm"], json={"amount": "232.00", "method": "cash"}).json()
    before = snapshot(shop)
    rev = f"{PUR}/refunds/{refund['id']}/reverse"
    assert client.post(rev, headers=shop["clerk"], json={"reason": "x"}).status_code == 403
    assert client.post(rev, headers=shop["fm"], json={"reason": " "}).status_code == 422
    done = client.post(rev, headers=shop["fm"], json={"reason": "Cheque bounced"})
    assert done.status_code == 200 and done.json()["status"] == "reversed"
    assert moved(before, snapshot(shop)) == {"1010": Dec(-232), "2000": Dec(232)}              # owed to us again
    assert Dec(client.get(f"{PUR}/refunds-due", headers=shop["fm"]).json()[0]["owed_back"]) >= 232
    assert client.post(rev, headers=shop["fm"], json={"reason": "again"}).status_code == 409
    # the same through Payments
    again = client.post(path, headers=shop["fm"], json={"amount": "50.00", "method": "cash"}).json()
    assert client.post(f"{PAY}/payments/{again['payment_id']}/reverse", headers=shop["fm"], json={"reason": "Wrong"}
                       ).status_code == 200
    assert client.get(f"{PUR}/refunds/{again['id']}", headers=shop["fm"]).json()["status"] == "reversed"
    assert Dec(client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()["refunded"]) == 0


def test_the_payment_a_refund_relies_on_cannot_be_reversed_first(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = paid_and_credited(client, shop, "REF-5")
    refund = client.post(f"{PUR}/bills/{bill['id']}/refund", headers=shop["fm"],
                         json={"amount": "232.00", "method": "cash"}).json()
    payment = client.get(f"{PUR}/bills/{bill['id']}/payments", headers=shop["fm"]).json()[0]["payment_id"]
    blocked = client.post(f"{PUR}/bills/{bill['id']}/reverse-payment", headers=shop["fm"],
                          json={"payment_id": payment, "reason": "Wrong supplier"})
    assert blocked.status_code == 422 and "reverse the refund first" in blocked.json()["message"]
    client.post(f"{PUR}/refunds/{refund['id']}/reverse", headers=shop["fm"], json={"reason": "Undo"})
    ok = client.post(f"{PUR}/bills/{bill['id']}/reverse-payment", headers=shop["fm"],
                     json={"payment_id": payment, "reason": "Wrong supplier"})
    assert ok.status_code == 200
    got = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
    assert Dec(got["amount_paid"]) == 0 and got["status"] == "posted"                          # owed less, via the credit
    assert Dec(got["total"]) - Dec(got["credited"]) == 348
    refused = client.post(f"{PUR}/bills/{bill['id']}/reverse", headers=shop["fm"], json={"reason": "x"})
    assert refused.status_code == 422                                                         # it has credit notes


def test_the_books_agree_with_what_suppliers_owe_and_owe_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    expected = one(shop, "select coalesce(sum(total - amount_paid - credited + refunded), 0) from purchasing.supplier_bill "
                         "where status in ('posted', 'part_paid', 'paid')")
    assert -balance(shop, "2000") == expected
    assert one(shop, "select count(*) from purchasing.supplier_bill where refunded > amount_paid + credited - total "
                     "and refunded > 0") == 0
