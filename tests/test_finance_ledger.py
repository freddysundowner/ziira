"""Periods and closing, manual journals with approval, and reversals."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import FIN, balance, entries, make_books_shop, opening, publish_sale
from tests.stock_helpers import INV, system
from ziira.sdk import ValidationFailed


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Ledger Co")
    opening(client, s)
    s["accountant"] = s["user"]("accountant", "Accountant", None)
    s["finance"] = s["user"]("finance", "Finance Manager", None)
    s["finance2"] = s["user"]("finance2", "Finance Manager", None)
    accounts = client.get(f"{FIN}/accounts", headers=s["owner"], params={"company_id": str(s["company_id"])}).json()
    s["acc"] = {a["code"]: a["id"] for a in accounts}
    return s


def journal(client, shop, who: str, lines, entry_date: str = "2026-10-13", description: str = "Adjusting entry"):  # type: ignore[no-untyped-def]
    return client.post(f"{FIN}/manual-journals", headers=shop.get(who, who), json={
        "company_id": str(shop["company_id"]), "entry_date": entry_date, "description": description, "lines": lines})


def two_lines(shop, debit_code: str = "6000", credit_code: str = "1020", amount: str = "500"):  # type: ignore[no-untyped-def]
    return [{"account_id": shop["acc"][debit_code], "debit": amount},
            {"account_id": shop["acc"][credit_code], "credit": amount}]


def submit(client, shop, manual_id, who: str = "accountant"):  # type: ignore[no-untyped-def]
    return client.post(f"{FIN}/manual-journals/{manual_id}/submit", headers=shop[who])


def post_manual(client, shop, amount: str = "500", **kw):  # type: ignore[no-untyped-def]
    d = journal(client, shop, "accountant", two_lines(shop, amount=amount), **kw)
    assert d.status_code == 201, d.text
    r = submit(client, shop, d.json()["id"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- manual journals
def test_a_manual_journal_is_drafted_then_posted(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = balance(shop, "6000")
    d = journal(client, shop, "accountant", two_lines(shop)).json()
    assert d["status"] == "draft" and d["number"] == "MJ-000001" and Dec(d["total"]) == 500
    assert balance(shop, "6000") == before                                   # a draft changes nothing
    r = submit(client, shop, d["id"]).json()
    assert r["status"] == "posted" and r["entry_id"]
    assert balance(shop, "6000") == before + 500
    entry = client.get(f"{FIN}/journal-entries/{r['entry_id']}", headers=shop["finance"]).json()
    assert entry["is_manual"] and entry["number"].startswith("GEN-") and len(entry["lines"]) == 2
    assert submit(client, shop, d["id"]).status_code == 409                  # only once


def test_manual_journal_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    acc, owner = shop["acc"], "owner"
    cases = {
        "unbalanced": [{"account_id": acc["6000"], "debit": "10"}, {"account_id": acc["1020"], "credit": "9"}],
        "one line": [{"account_id": acc["6000"], "debit": "10"}],
        "both sides": [{"account_id": acc["6000"], "debit": "10", "credit": "10"}, {"account_id": acc["1020"],
                                                                                 "credit": "0"}],
        "empty line": [{"account_id": acc["6000"]}, {"account_id": acc["1020"], "credit": "1"}],
        "cents": [{"account_id": acc["6000"], "debit": "1.005"}, {"account_id": acc["1020"], "credit": "1.005"}],
        "stock account": [{"account_id": acc["1200"], "debit": "10"}, {"account_id": acc["1020"], "credit": "10"}],
        "receivable": [{"account_id": acc["6000"], "debit": "10"}, {"account_id": acc["1100"], "credit": "10"}],
        "no such account": [{"account_id": str(uuid4()), "debit": "10"}, {"account_id": acc["1020"], "credit": "10"}],
        "negative": [{"account_id": acc["6000"], "debit": "-5"}, {"account_id": acc["1020"], "credit": "-5"}],
        "huge": [{"account_id": acc["6000"], "debit": "1e20"}, {"account_id": acc["1020"], "credit": "1e20"}],
        "bad branch": [{"account_id": acc["6000"], "debit": "5", "branch_id": str(uuid4())},
                       {"account_id": acc["1020"], "credit": "5"}],
    }
    for name, lines in cases.items():
        r = journal(client, shop, owner, lines)
        assert r.status_code == 422, (name, r.status_code, r.text)
    assert journal(client, shop, owner, two_lines(shop), description="  ").status_code == 422
    assert journal(client, shop, owner, two_lines(shop), entry_date="not a date").status_code == 422


def test_an_inactive_account_cannot_be_used(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{FIN}/accounts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "6800", "name": "Old", "type": "expense"})
    old = r.json()["id"]
    client.patch(f"{FIN}/accounts/{old}", headers=shop["owner"], json={"is_active": False})
    lines = [{"account_id": old, "debit": "5"}, {"account_id": shop["acc"]["1020"], "credit": "5"}]
    assert journal(client, shop, "owner", lines).status_code == 422


def test_only_people_with_the_permission_write_journals(client, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("cashier", "storekeeper", "manager"):
        assert journal(client, shop, who, two_lines(shop)).status_code == 403
    d = journal(client, shop, "accountant", two_lines(shop)).json()
    assert submit(client, shop, d["id"], "cashier").status_code == 403


# --------------------------------------------------------------------------- the approval matrix
@pytest.fixture(scope="module")
def approval_rule(client, shop):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "manual_journal",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "10000"})
    assert r.status_code == 201, r.text


def decide(client, shop, doc_id, who: str, approve: bool = True, note: str | None = None):  # type: ignore[no-untyped-def]
    pending = client.get("/api/v1/approvals/pending", headers=shop[who]).json()
    request = next((x for x in pending if x["doc_id"] == doc_id), None)
    assert request is not None, f"{who} sees no pending request"
    return client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop[who],
                       json={"approve": approve, "note": note})


def test_a_large_journal_waits_for_approval(client, shop, approval_rule) -> None:  # type: ignore[no-untyped-def]
    small = post_manual(client, shop, amount="9999.99")                      # below the threshold: posts at once
    assert small["status"] == "posted"
    d = journal(client, shop, "accountant", two_lines(shop, amount="20000")).json()
    r = submit(client, shop, d["id"]).json()
    assert r["status"] == "pending_approval" and r["entry_id"] is None
    before = balance(shop, "6000")
    assert client.get("/api/v1/approvals/pending", headers=shop["accountant"]).json() == []       # not an approver
    assert client.post(f"/api/v1/approvals/{uuid4()}/decision", headers=shop["accountant"],
                       json={"approve": True}).status_code == 404
    done = decide(client, shop, d["id"], "finance")
    assert done.status_code == 200, done.text
    posted = client.get(f"{FIN}/manual-journals/{d['id']}", headers=shop["finance"]).json()
    assert posted["status"] == "posted" and posted["approved_by"] and posted["entry_id"]
    assert balance(shop, "6000") == before + 20000


def test_a_rejected_journal_never_posts_and_the_writer_cannot_approve_their_own(client, shop, approval_rule) -> None:  # type: ignore[no-untyped-def]
    before = balance(shop, "6000")
    d = journal(client, shop, "accountant", two_lines(shop, amount="30000")).json()
    submit(client, shop, d["id"])
    assert decide(client, shop, d["id"], "finance", approve=False).status_code == 422           # a reason is needed
    assert decide(client, shop, d["id"], "finance", approve=False, note="Wrong account").status_code == 200
    assert client.get(f"{FIN}/manual-journals/{d['id']}", headers=shop["owner"]).json()["status"] == "rejected"
    assert balance(shop, "6000") == before
    # a finance manager who wrote it cannot approve it (separation of duties)
    own = client.post(f"{FIN}/manual-journals", headers=shop["finance"], json={
        "company_id": str(shop["company_id"]), "entry_date": "2026-10-13", "description": "Mine",
        "lines": two_lines(shop, amount="40000")}).json()
    client.post(f"{FIN}/manual-journals/{own['id']}/submit", headers=shop["finance"])
    assert decide(client, shop, own["id"], "finance").status_code == 403
    assert decide(client, shop, own["id"], "finance2").status_code == 200


# --------------------------------------------------------------------------- reversals
def test_reversing_a_manual_entry(client, shop) -> None:  # type: ignore[no-untyped-def]
    original = post_manual(client, shop, amount="700")
    before = balance(shop, "6000")
    url = f"{FIN}/journal-entries/{original['entry_id']}/reverse"
    assert client.post(url, headers=shop["accountant"], json={"reason": "Mistake"}).status_code == 403   # no approve
    assert client.post(url, headers=shop["finance"], json={"reason": " "}).status_code == 422
    r = client.post(url, headers=shop["finance"], json={"reason": "Posted twice"})
    assert r.status_code == 201, r.text
    reversal = r.json()
    assert reversal["reversal_of_id"] == original["entry_id"] and "Reversal of" in reversal["description"]
    debits = {x["account_id"]: Dec(x["debit"]) for x in reversal["lines"]}
    assert Dec(debits[shop["acc"]["1020"]]) == 700                           # the sides are swapped
    assert balance(shop, "6000") == before - 700
    assert client.get(f"{FIN}/journal-entries/{original['entry_id']}", headers=shop["finance"]
                      ).json()["reversed_by"] == reversal["id"]
    assert client.post(url, headers=shop["finance"], json={"reason": "again"}).status_code == 409      # once only
    again = client.post(f"{FIN}/journal-entries/{reversal['id']}/reverse", headers=shop["finance"],
                        json={"reason": "undo the undo"})
    assert again.status_code == 422 and "cannot be reversed" in again.json()["message"]


def test_system_entries_are_corrected_in_their_source_not_reversed(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = uuid4()
    publish_sale(shop, sale_id=sale)
    entry = client.get(f"{FIN}/journal-entries", headers=shop["finance"],
                       params={"source_type": "sale", "source_id": str(sale)}).json()[0]
    r = client.post(f"{FIN}/journal-entries/{entry['id']}/reverse", headers=shop["finance"], json={"reason": "x"})
    assert r.status_code == 422 and "correct that document" in r.json()["message"]
    assert client.post(f"{FIN}/journal-entries/{uuid4()}/reverse", headers=shop["finance"],
                       json={"reason": "x"}).status_code == 404


# --------------------------------------------------------------------------- periods
def periods(client, shop):  # type: ignore[no-untyped-def]
    return {p["start_date"]: p for p in client.get(f"{FIN}/periods", headers=shop["finance"],
                                                  params={"company_id": str(shop["company_id"])}).json()}


def set_status(client, shop, period_id, status: str, who: str = "finance"):  # type: ignore[no-untyped-def]
    return client.post(f"{FIN}/periods/{period_id}/status", headers=shop[who], json={"status": status})


def test_periods_appear_monthly_as_things_are_posted(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert "2026-10-01" in periods(client, shop)
    publish_sale(shop, business_date="2026-08-15")
    p = periods(client, shop)["2026-08-01"]
    assert p["end_date"] == "2026-08-31" and p["status"] == "open"
    r = client.post(f"{FIN}/periods", headers=shop["finance"], json={"company_id": str(shop["company_id"]),
                                                                    "day": "2028-02-10"})
    assert r.status_code == 201 and r.json()["end_date"] == "2028-02-29"        # leap year
    assert client.post(f"{FIN}/periods", headers=shop["accountant"], json={"company_id": str(shop["company_id"]),
                                                                          "day": "2028-03-10"}).status_code == 403


def test_closing_needs_permission_and_follows_the_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, business_date="2026-07-15")
    p = periods(client, shop)["2026-07-01"]
    assert set_status(client, shop, p["id"], "soft_closed", "accountant").status_code == 403
    assert set_status(client, shop, p["id"], "locked").status_code == 422             # soft-close first
    assert set_status(client, shop, p["id"], "open").status_code == 422               # already open
    closed = set_status(client, shop, p["id"], "soft_closed")
    assert closed.status_code == 200 and closed.json()["closed_by"]
    assert set_status(client, shop, p["id"], "open").json()["closed_by"] is None      # reopen is allowed
    set_status(client, shop, p["id"], "soft_closed")
    assert set_status(client, shop, p["id"], "locked").status_code == 200
    assert set_status(client, shop, p["id"], "open").status_code == 422               # locked stays locked
    assert set_status(client, shop, str(uuid4()), "soft_closed").status_code == 404


def test_a_period_cannot_close_while_journals_wait_for_approval(client, shop, approval_rule) -> None:  # type: ignore[no-untyped-def]
    d = journal(client, shop, "accountant", two_lines(shop, amount="50000"), entry_date="2026-06-10").json()
    submit(client, shop, d["id"])
    period = periods(client, shop)["2026-06-01"] if "2026-06-01" in periods(client, shop) else client.post(
        f"{FIN}/periods", headers=shop["finance"], json={"company_id": str(shop["company_id"]),
                                                          "day": "2026-06-10"}).json()
    checklist = client.get(f"{FIN}/periods/{period['id']}/checklist", headers=shop["finance"]).json()
    assert checklist["ready"] is False and "waiting for approval" in checklist["problems"][0]
    r = set_status(client, shop, period["id"], "soft_closed")
    assert r.status_code == 422 and "cannot be closed yet" in r.json()["message"]
    assert decide(client, shop, d["id"], "finance").status_code == 200                 # approve it; now it can close
    assert client.get(f"{FIN}/periods/{period['id']}/checklist", headers=shop["finance"]).json()["ready"] is True
    assert set_status(client, shop, period["id"], "soft_closed").status_code == 200


def test_manual_postings_into_closed_periods(client, shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, business_date="2026-05-20")
    p = periods(client, shop)["2026-05-01"]
    set_status(client, shop, p["id"], "soft_closed")
    d = journal(client, shop, "accountant", two_lines(shop, amount="10"), entry_date="2026-05-25").json()
    r = submit(client, shop, d["id"])
    assert r.status_code == 422 and "may post into it" in r.json()["message"]   # not a closer
    fm = client.post(f"{FIN}/manual-journals", headers=shop["finance"], json={
        "company_id": str(shop["company_id"]), "entry_date": "2026-05-25", "description": "Late",
        "lines": two_lines(shop, amount="10")}).json()
    assert client.post(f"{FIN}/manual-journals/{fm['id']}/submit", headers=shop["finance"]).status_code == 200
    set_status(client, shop, p["id"], "locked")
    late = journal(client, shop, "finance", two_lines(shop, amount="10"), entry_date="2026-05-26").json()
    r = client.post(f"{FIN}/manual-journals/{late['id']}/submit", headers=shop["finance"])
    assert r.status_code == 422 and "locked" in r.json()["message"]                  # not even finance managers


def test_a_sale_into_a_closed_month_is_redirected_to_the_current_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, business_date="2026-04-10")
    p = periods(client, shop)["2026-04-01"]
    set_status(client, shop, p["id"], "soft_closed")
    sale = uuid4()
    publish_sale(shop, sale_id=sale, business_date="2026-04-12")
    entry = entries(shop, source_type="sale", source_id=sale)[0]
    assert str(entry[3]) != "2026-04-12"                                              # booked today instead
    assert "dated 2026-04-12, posted to the current period" in entry[4]
    stock_sale = uuid4()
    publish_sale(shop, sale_id=stock_sale, business_date="2026-04-12",
                 lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "1"}])
    assert all(str(e[3]) != "2026-04-12" for e in entries(shop, source_type="stock_movement")
               if e[4] and "Stock sale" in e[4])                                      # its stock entry too


def test_the_company_can_choose_to_refuse_late_documents(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"/api/v1/companies/{shop['company_id']}/settings"
    assert client.patch(url, headers=shop["owner"], json={"late_posting": "reject"}).status_code == 200
    try:
        with system(shop) as s:
            stock_before = s.execute(text(
                "select coalesce(sum(quantity), 0) from inventory.stock_balance")).scalar_one()
        with pytest.raises(ValidationFailed, match="closed"):
            publish_sale(shop, business_date="2026-04-20",
                         lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "1"}])
        with system(shop) as s:                                                       # the whole sale was undone
            assert s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance")).scalar_one() \
                == stock_before
        assert client.patch(url, headers=shop["owner"], json={"late_posting": "sometimes"}).status_code == 422
    finally:
        client.patch(url, headers=shop["owner"], json={"late_posting": "redirect"})


def test_closing_is_blocked_while_stock_and_books_disagree(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    """Stock moved while Finance was off is missing from the books: the period cannot close until it is caught up."""
    registry.disable(shop["tenant_id"], "finance")
    product = client.post("/api/v1/products/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": "OFFLINE", "name": "Booked later", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"]}).json()["id"]
    client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["juja_store"],
        "lines": [{"product_id": product, "quantity": "5", "unit_cost": "100"}]})
    registry.enable(shop["tenant_id"], "finance")
    p = client.post(f"{FIN}/periods", headers=shop["finance"], json={"company_id": str(shop["company_id"]),
                                                                    "day": "2026-10-13"}).json()
    r = set_status(client, shop, p["id"], "soft_closed")
    assert r.status_code == 422 and "stock ledger is worth" in r.json()["message"]
    from ziira.kernel.checks import run_integrity_checks

    found = [x for r_ in run_integrity_checks(shop["tenant_id"]) for x in r_.problems]
    assert any("have not been posted to the books" in x for x in found)
    run_integrity_checks(shop["tenant_id"], fix=True)                               # catch up from the movements
    assert [x for r_ in run_integrity_checks(shop["tenant_id"]) for x in r_.problems] == []
    assert client.get(f"{FIN}/periods/{p['id']}/checklist", headers=shop["finance"]).json()["ready"] is True
