"""Checking a supplier's statement against our books."""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.purchasing_helpers import PUR, make_purchasing_shop

TODAY = date.today()


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_purchasing_shop(client, registry, "Statement Co")
    books = client.post(f"/api/v1/finance/companies/{s['company_id']}/books", headers=s["owner"]).json()
    s["expense"] = next(a["id"] for a in books if a["code"] == "6200")
    return s


def supplier(client, shop, code):  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/suppliers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": code, "name": f"Supplier {code}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def bill(client, shop, sup, invoice, net, when=TODAY):  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/bills", headers=shop["owner"], json={
        "supplier_id": sup, "supplier_invoice_no": invoice, "bill_date": str(when), "lines": [
            {"quantity": "1", "unit_cost": net, "expense_account_id": shop["expense"], "description": "Services",
             "tax_code_id": shop["tax"]}]})
    assert r.status_code == 201, r.text
    done = client.post(f"{PUR}/bills/{r.json()['id']}/submit", headers=shop["owner"])
    assert done.json()["status"] == "posted", done.text
    return done.json()


def pay(client, shop, b, amount, ref):  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/bills/{b['id']}/pay", headers=shop["fm"], json={
        "amount": amount, "method": "bank", "payment_account_id": shop["bank"], "external_ref": ref})
    assert r.status_code == 200, r.text


def check(client, shop, sup, lines, who="clerk", **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{PUR}/suppliers/{sup}/statement-reconciliation", headers=shop[who], json={
        "lines": [{"date": str(d), "reference": ref, "kind": kind, "amount": amount} for d, ref, kind, amount in lines],
        **kw})


def test_a_statement_that_agrees_with_our_books(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "AGREE")
    a = bill(client, shop, sup, "S-A", "500.00")                                               # 580
    pay(client, shop, a, "200.00", "EFT-AGREE-1")
    r = check(client, shop, sup, [(TODAY, "S-A", "invoice", "580.00"), (TODAY, "EFT-AGREE-1", "payment", "200.00")])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["summary"] == {"matched": 2, "amount_differs": 0, "missing_here": 0, "missing_there": 0}
    assert Dec(out["their_balance"]) == Dec(out["our_balance"]) == 380 and Dec(out["difference"]) == 0
    assert Dec(out["unexplained"]) == 0 and out["supplier"] == "Supplier AGREE"
    loose = check(client, shop, sup, [(TODAY, " s a ", "invoice", "580.00")])                    # references match loosely
    assert loose.json()["summary"]["matched"] == 1


def test_what_the_supplier_has_and_we_have_not(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "MISSING")
    a = bill(client, shop, sup, "M-A", "100.00")                                               # 116
    out = check(client, shop, sup, [
        (TODAY, "M-A", "invoice", "116.00"), (TODAY, "M-B", "invoice", "232.00"),               # a bill we never entered
        (TODAY, "CN-9", "credit", "50.00"), (TODAY, "EFT-NOPE", "payment", "30.00")]).json()    # a credit and payment unknown
    statuses = {i["reference"]: i["status"] for i in out["items"]}
    assert statuses == {"M-A": "matched", "M-B": "missing_here", "CN-9": "missing_here", "EFT-NOPE": "missing_here"}
    assert out["summary"]["missing_here"] == 3
    assert Dec(out["our_balance"]) == 116 and Dec(out["their_balance"]) == 116 + 232 - 50 - 30
    assert Dec(out["difference"]) == Dec(out["explained_by_lines"]) == 152 and Dec(out["unexplained"]) == 0
    notes = {i["reference"]: i["note"] for i in out["items"]}
    assert "no bill" in notes["M-B"] and "no credit note" in notes["CN-9"] and "no payment" in notes["EFT-NOPE"]
    assert a["id"]


def test_an_amount_that_differs(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "DIFFERS")
    bill(client, shop, sup, "D-A", "1000.00")                                                  # 1160
    out = check(client, shop, sup, [(TODAY, "D-A", "invoice", "1200.00")]).json()
    item = out["items"][0]
    assert item["status"] == "amount_differs" and Dec(item["their_amount"]) == 1200 and Dec(item["our_amount"]) == 1160
    assert "They say 1200" in item["note"]
    assert Dec(out["difference"]) == 40 == Dec(out["explained_by_lines"]) and Dec(out["unexplained"]) == 0


def test_what_we_have_that_the_supplier_has_not_shown(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "OURS")
    a = bill(client, shop, sup, "O-A", "500.00")                                               # 580
    pay(client, shop, a, "300.00", "EFT-OURS-1")                                               # not yet received by them
    out = check(client, shop, sup, [(TODAY, "O-A", "invoice", "580.00")]).json()
    assert out["summary"]["missing_there"] == 1
    gap = out["missing_there"][0]
    assert gap["kind"] == "payment" and gap["reference"] == "EFT-OURS-1" and Dec(gap["amount"]) == 300
    assert "have not shown" in gap["note"]
    assert Dec(out["our_balance"]) == 280 and Dec(out["their_balance"]) == 580 and Dec(out["difference"]) == 300
    assert Dec(out["explained_by_lines"]) == 300 and Dec(out["unexplained"]) == 0


def test_payments_are_found_by_amount_and_date_when_the_reference_differs(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "FUZZY")
    a = bill(client, shop, sup, "F-A", "500.00")
    pay(client, shop, a, "250.00", "OUR-REF-77")
    near = check(client, shop, sup, [(TODAY, "F-A", "invoice", "580.00"),
                                     (TODAY - timedelta(days=2), "THEIR-RECEIPT-5", "payment", "250.00")]).json()
    assert near["summary"]["matched"] == 2 and near["summary"]["missing_here"] == 0
    far = check(client, shop, sup, [(TODAY, "F-A", "invoice", "580.00"),
                                    (TODAY - timedelta(days=30), "THEIR-RECEIPT-5", "payment", "250.00")]).json()
    assert far["summary"]["missing_here"] == 1 and far["summary"]["missing_there"] == 1
    other_amount = check(client, shop, sup, [(TODAY, "F-A", "invoice", "580.00"),
                                             (TODAY, "THEIR-RECEIPT-5", "payment", "249.00")]).json()
    assert other_amount["summary"]["missing_here"] == 1


def test_an_opening_balance_difference_is_left_unexplained(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "OPENING")
    bill(client, shop, sup, "P-A", "100.00")                                                   # 116
    out = check(client, shop, sup, [(TODAY, "P-A", "invoice", "116.00")], their_balance="616.00").json()
    assert Dec(out["their_balance"]) == 616 and Dec(out["difference"]) == 500
    assert Dec(out["explained_by_lines"]) == 0 and Dec(out["unexplained"]) == 500           # from before these lines


def test_only_what_is_on_or_before_the_statement_date_counts(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "CUTOFF")
    bill(client, shop, sup, "C-A", "100.00", when=TODAY - timedelta(days=20))
    bill(client, shop, sup, "C-B", "200.00", when=TODAY)
    out = check(client, shop, sup, [(TODAY - timedelta(days=20), "C-A", "invoice", "116.00")],
                as_of=str(TODAY - timedelta(days=10))).json()
    assert out["summary"]["missing_there"] == 0 and Dec(out["our_balance"]) == 116 == Dec(out["their_balance"])
    assert out["as_of"] == str(TODAY - timedelta(days=10))


def test_a_statement_can_be_sent_as_csv(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "CSVSUP")
    bill(client, shop, sup, "V-A", "100.00")
    csv_text = f"date,reference,kind,amount\n{TODAY},V-A,invoice,116.00\n{TODAY},V-B,invoice,58.00\n"
    r = client.post(f"{PUR}/suppliers/{sup}/statement-reconciliation", headers=shop["clerk"], json={"csv": csv_text})
    assert r.status_code == 200 and r.json()["summary"] == {
        "matched": 1, "amount_differs": 0, "missing_here": 1, "missing_there": 0}
    bad = client.post(f"{PUR}/suppliers/{sup}/statement-reconciliation", headers=shop["clerk"],
                      json={"csv": "2026-10-01,X,gift,10"})
    assert bad.status_code == 422 and "Line 1" in bad.json()["message"]


def test_validation_and_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = supplier(client, shop, "RULES")
    line = (TODAY, "R-A", "invoice", "10.00")
    path = f"{PUR}/suppliers/{sup}/statement-reconciliation"
    assert client.post(path, headers=shop["clerk"], json={}).status_code == 422
    assert client.post(path, headers=shop["clerk"], json={"lines": [{"date": str(TODAY), "reference": "A", "kind":
                                                                      "invoice", "amount": "1"}], "csv": "x"}
                       ).status_code == 422
    for bad in ({"amount": "0"}, {"amount": "-1"}, {"kind": "gift"}, {"reference": ""}, {"date": "soon"}):
        item = {"date": str(TODAY), "reference": "A", "kind": "invoice", "amount": "10.00", **bad}
        assert client.post(path, headers=shop["clerk"], json={"lines": [item]}).status_code == 422, bad
    assert client.post(path, headers=shop["clerk"], json={"lines": []}).status_code == 422
    assert check(client, shop, str(uuid4()), [line]).status_code == 404
    for who in ("buyer", "storekeeper", "cashier"):
        assert check(client, shop, sup, [line], who=who).status_code == 403, who
    assert check(client, shop, sup, [line], who="fm").status_code == 200
