"""Expenses: drafted, submitted, approved by the matrix, posted to the books, reversed."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import FIN, balance, entries, make_books_shop

TODAY = "2026-10-14"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Expense Co")
    s["accountant"] = s["user"]("accountant", "Accountant", None)
    s["finance"] = s["user"]("finance", "Finance Manager", None)
    s["company"] = str(s["company_id"])
    books = client.post(f"{FIN}/companies/{s['company']}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in books}
    return s


def draft(client, shop, who="accountant", amount="1160.00", tax="160.00", code="6200", paid_from="cash", **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": shop["company"], "branch_id": str(shop["branch_id"]), "expense_date": TODAY,
            "description": "Electricity", "account_id": shop["acc"][code], "amount": amount, "tax_amount": tax,
            "paid_from": paid_from, "payee": "KPLC", "receipt_ref": "R-100", **kw}
    return client.post(f"{FIN}/expenses", headers=shop[who], json=body)


def submit(client, shop, expense_id, who="accountant"):  # type: ignore[no-untyped-def]
    return client.post(f"{FIN}/expenses/{expense_id}/submit", headers=shop[who])


def spend(client, shop, **kw):  # type: ignore[no-untyped-def]
    made = draft(client, shop, **kw)
    assert made.status_code == 201, made.text
    done = submit(client, shop, made.json()["id"])
    assert done.status_code == 200, done.text
    return done.json()


# --------------------------------------------------------------------------- posting
def test_an_expense_is_drafted_then_posted(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = balance(shop, "6200"), balance(shop, "1300"), balance(shop, "1010")
    made = draft(client, shop)
    assert made.status_code == 201, made.text
    e = made.json()
    assert e["status"] == "draft" and e["number"].startswith("EXP-") and e["entry_id"] is None
    assert (balance(shop, "6200"), balance(shop, "1300"), balance(shop, "1010")) == before      # a draft changes nothing
    done = submit(client, shop, e["id"]).json()
    assert done["status"] == "posted" and done["entry_id"]
    assert balance(shop, "6200") == before[0] + 1000                       # the cost, before VAT
    assert balance(shop, "1300") == before[1] + 160                        # VAT input
    assert balance(shop, "1010") == before[2] - 1160                       # paid in cash
    entry = [x for x in entries(shop, source_type="expense")][-1]
    assert sorted((c, d, cr) for c, d, cr, _ in entry[2]) == [("1010", 0, Dec(1160)), ("1300", Dec(160), 0),
                                                              ("6200", Dec(1000), 0)]
    assert entry[2][0][3] == shop["branch_id"]                             # the branch is on the lines
    assert submit(client, shop, e["id"]).status_code == 409                # once only
    assert client.get(f"{FIN}/expenses/{e['id']}", headers=shop["accountant"]).json()["status"] == "posted"


def test_the_money_comes_from_where_it_was_paid(client, shop) -> None:  # type: ignore[no-untyped-def]
    for method, code in (("bank", "1020"), ("mobile_money", "1030"), ("card", "1040"), ("other", "1020")):
        before = balance(shop, code)
        spend(client, shop, amount="116.00", tax="16.00", paid_from=method, code="6300")
        assert balance(shop, code) == before - 116, method
    no_tax = spend(client, shop, amount="50.00", tax="0", code="6900")
    lines = [x for x in entries(shop, source_type="expense")][-1][2]
    assert len(lines) == 2 and no_tax["tax_amount"] == "0.00"              # no VAT line when there is no VAT


def test_expenses_show_in_the_reports(client, shop) -> None:  # type: ignore[no-untyped-def]
    spend(client, shop, amount="232.00", tax="32.00", code="6000")
    params = {"company_id": shop["company"], "date_from": "2026-10-01", "date_to": "2026-10-31"}
    pnl = client.get(f"{FIN}/reports/profit-and-loss", headers=shop["accountant"], params=params).json()
    rent = next(x for x in pnl["consolidated"]["expenses"] if x["code"] == "6000")
    assert Dec(rent["amount"]) == 200
    vat = client.get(f"{FIN}/reports/vat-summary", headers=shop["accountant"], params=params).json()
    assert Dec(vat["input_vat"]) >= 32 and Dec(vat["net_payable"]) == Dec(vat["output_vat"]) - Dec(vat["input_vat"])


# --------------------------------------------------------------------------- approval
@pytest.fixture(scope="module")
def approval_rule(client, shop):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": shop["company"], "doc_type": "expense", "approver_role_id": shop["roles"]["Finance Manager"],
        "min_amount": "5000"})
    assert r.status_code == 201, r.text


def decide(client, shop, doc_id, who, approve=True):  # type: ignore[no-untyped-def]
    pending = client.get("/api/v1/approvals/pending", headers=shop[who]).json()
    request = next((x for x in pending if x["doc_id"] == doc_id), None)
    assert request is not None, f"{who} sees no pending request"
    return client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop[who], json={"approve": approve, "note": None if approve else "Not budgeted"})


def test_a_large_expense_waits_for_approval(client, shop, approval_rule) -> None:  # type: ignore[no-untyped-def]
    assert spend(client, shop, amount="4999.00", tax="0", code="6000")["status"] == "posted"   # below the threshold
    e = draft(client, shop, amount="20000.00", tax="0", code="6000").json()
    pending = submit(client, shop, e["id"]).json()
    assert pending["status"] == "pending_approval" and pending["entry_id"] is None
    before = balance(shop, "6000")
    assert client.get("/api/v1/approvals/pending", headers=shop["accountant"]).json() == []       # not an approver
    assert decide(client, shop, e["id"], "finance").status_code == 200
    posted = client.get(f"{FIN}/expenses/{e['id']}", headers=shop["finance"]).json()
    assert posted["status"] == "posted" and posted["approved_by"] and posted["entry_id"]
    assert balance(shop, "6000") == before + 20000


def test_a_rejected_expense_never_posts(client, shop, approval_rule) -> None:  # type: ignore[no-untyped-def]
    e = draft(client, shop, amount="9000.00", tax="0", code="6000").json()
    submit(client, shop, e["id"])
    before = balance(shop, "6000")
    assert decide(client, shop, e["id"], "finance", approve=False).status_code == 200
    rejected = client.get(f"{FIN}/expenses/{e['id']}", headers=shop["finance"]).json()
    assert rejected["status"] == "rejected" and rejected["entry_id"] is None and balance(shop, "6000") == before
    assert submit(client, shop, e["id"]).status_code == 409


# --------------------------------------------------------------------------- reversal
def test_reversing_a_posted_expense(client, shop) -> None:  # type: ignore[no-untyped-def]
    e = spend(client, shop, amount="580.00", tax="80.00", code="6300")
    before = balance(shop, "6300"), balance(shop, "1300"), balance(shop, "1010")
    path = f"{FIN}/expenses/{e['id']}/reverse"
    assert client.post(path, headers=shop["accountant"], json={"reason": "Wrong"}).status_code == 403
    assert client.post(path, headers=shop["finance"], json={"reason": "  "}).status_code == 422
    done = client.post(path, headers=shop["finance"], json={"reason": "Entered twice"})
    assert done.status_code == 200 and done.json()["status"] == "reversed", done.text
    assert (balance(shop, "6300"), balance(shop, "1300"), balance(shop, "1010")) == (
        before[0] - 500, before[1] - 80, before[2] + 580)
    assert client.post(path, headers=shop["finance"], json={"reason": "Again"}).status_code == 409
    fresh = draft(client, shop).json()
    assert client.post(f"{FIN}/expenses/{fresh['id']}/reverse", headers=shop["finance"],
                       json={"reason": "x"}).status_code == 409                       # a draft has nothing to reverse


# --------------------------------------------------------------------------- rules and permissions
def test_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"amount": "0"}, {"amount": "-5"}, {"tax": "1160.00"}, {"tax": "-1"}, {"paid_from": "cheque"},
                {"description": "   "}, {"payee": "x" * 201}, {"receipt_ref": "x" * 101}):
        body = {"amount": "1160.00", "tax": "160.00", "paid_from": "cash", **bad}
        made = draft(client, shop, **body)
        assert made.status_code == 422, (bad, made.text)
    for code in ("1010", "4000", "1100", "2200"):                                      # not expense accounts
        assert draft(client, shop, code=code).status_code == 422, code
    foreign = client.post(f"{FIN}/expenses", headers=shop["accountant"], json={
        "company_id": shop["company"], "expense_date": TODAY, "description": "x", "account_id": str(uuid4()),
        "amount": "10", "paid_from": "cash"})
    assert foreign.status_code == 422
    assert draft(client, shop, branch_id=str(uuid4())).status_code in (403, 404, 422)
    assert client.get(f"{FIN}/expenses/{uuid4()}", headers=shop["accountant"]).status_code == 404


def test_who_may_do_what(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert draft(client, shop, who="cashier").status_code == 403
    assert draft(client, shop, who="storekeeper").status_code == 403
    e = draft(client, shop).json()
    assert submit(client, shop, e["id"], who="cashier").status_code == 403
    assert client.get(f"{FIN}/expenses", headers=shop["cashier"]).status_code == 403
    assert client.get(f"{FIN}/expenses/{e['id']}", headers=shop["cashier"]).status_code == 403


def test_a_branch_manager_works_only_inside_their_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    own = draft(client, shop, who="manager")
    assert own.status_code == 201, own.text
    elsewhere = draft(client, shop, who="manager", branch_id=str(shop["juja"]))
    assert elsewhere.status_code == 403
    juja = draft(client, shop, branch_id=str(shop["juja"])).json()                      # the accountant is company-wide
    assert client.get(f"{FIN}/expenses/{juja['id']}", headers=shop["manager"]).status_code == 404
    seen = client.get(f"{FIN}/expenses", headers=shop["manager"], params={"company_id": shop["company"]}).json()
    assert seen and all(x["branch_id"] == str(shop["branch_id"]) for x in seen)
    everyone = client.get(f"{FIN}/expenses", headers=shop["accountant"], params={"company_id": shop["company"]}).json()
    assert len(everyone) > len(seen)
    posted = client.get(f"{FIN}/expenses", headers=shop["accountant"], params={"status": "posted", "limit": 3}).json()
    assert len(posted) == 3 and all(x["status"] == "posted" for x in posted)
    assert client.get(f"{FIN}/expenses", headers=shop["accountant"],
                      params={"date_from": "2030-01-01"}).json() == []
