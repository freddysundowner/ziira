"""Bank reconciliation: tick the ledger lines that are on the statement until the cleared balance equals it."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import FIN, make_books_shop, publish_sale

BR = f"{FIN}/bank-reconciliations"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Recon Co")
    s["accountant"] = s["user"]("accountant", "Accountant", None)
    s["finance"] = s["user"]("finance", "Finance Manager", None)
    s["company"] = str(s["company_id"])
    books = client.post(f"{FIN}/companies/{s['company']}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in books}
    return s


def manual(client, shop, day, debit_code, credit_code, amount, description):  # type: ignore[no-untyped-def]
    made = client.post(f"{FIN}/manual-journals", headers=shop["accountant"], json={
        "company_id": shop["company"], "entry_date": day, "description": description, "lines": [
            {"account_id": shop["acc"][debit_code], "debit": amount},
            {"account_id": shop["acc"][credit_code], "credit": amount}]})
    assert made.status_code == 201, made.text
    done = client.post(f"{FIN}/manual-journals/{made.json()['id']}/submit", headers=shop["accountant"])
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text


def start(client, shop, code="1020", day="2026-10-15", balance="4200.00", who="accountant"):  # type: ignore[no-untyped-def]
    return client.post(BR, headers=shop[who], json={
        "company_id": shop["company"], "account_id": shop["acc"][code], "statement_date": day,
        "statement_balance": balance})


def by_description(detail, text):  # type: ignore[no-untyped-def]
    found = [x for x in detail["cleared"] + detail["uncleared"] if text in (x["description"] or "")]
    assert len(found) == 1, (text, found)
    return found[0]


@pytest.fixture(scope="module")
def bank(client, shop):  # type: ignore[no-untyped-def]
    """The bank account's books: 5000 in, 800 out, 1200 in (October 2, 5, 8) and 300 out on October 20."""
    manual(client, shop, "2026-10-02", "1020", "3000", "5000", "Capital introduced CAP1")
    manual(client, shop, "2026-10-05", "6000", "1020", "800", "Rent for October")
    manual(client, shop, "2026-10-08", "1020", "4000", "1200", "Deposit of takings")
    manual(client, shop, "2026-10-20", "6200", "1020", "300", "Electricity")
    return True


# --------------------------------------------------------------------------- the whole cycle
def test_reconciling_a_bank_account_month_by_month(client, shop, bank) -> None:  # type: ignore[no-untyped-def]
    # The statement up to 15 October shows 4200: the 1200 deposit has not reached the bank yet.
    r = start(client, shop)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "in_progress" and d["account_code"] == "1020"
    assert Dec(d["book_balance"]) == 5400 and Dec(d["statement_balance"]) == 4200
    assert Dec(d["cleared_balance"]) == 0 and Dec(d["difference"]) == 4200
    assert sorted(Dec(x["amount"]) for x in d["uncleared"]) == [-800, 1200, 5000]       # the 20 October line is later
    path = f"{BR}/{d['id']}"
    early = client.post(f"{path}/complete", headers=shop["accountant"])
    assert early.status_code == 409 and "short of" in early.json()["message"]
    ids = [by_description(d, "Capital introduced")["line_id"], by_description(d, "Rent")["line_id"]]
    cleared = client.post(f"{path}/clear", headers=shop["accountant"], json={"line_ids": ids}).json()
    assert Dec(cleared["cleared_balance"]) == 4200 and Dec(cleared["difference"]) == 0
    assert Dec(cleared["outstanding"]) == 1200 and [x["amount"] for x in cleared["uncleared"]] == ["1200.00"]
    done = client.post(f"{path}/complete", headers=shop["accountant"])
    assert done.status_code == 200 and done.json()["status"] == "completed" and done.json()["completed_by"]
    assert client.post(f"{path}/clear", headers=shop["accountant"], json={"line_ids": ids}).status_code == 409
    assert client.delete(path, headers=shop["accountant"]).status_code == 409                  # final
    assert client.post(f"{path}/complete", headers=shop["accountant"]).status_code == 409
    assert start(client, shop, day="2026-10-15", balance="1").status_code == 422               # not back in time
    # The next statement (31 October): 5100 = the deposit (1200) and the electricity (-300) on top of 4200.
    nxt = start(client, shop, day="2026-10-31", balance="5100.00")
    assert nxt.status_code == 201, nxt.text
    d2 = nxt.json()
    assert Dec(d2["cleared_balance"]) == 4200 and Dec(d2["difference"]) == 900                  # earlier work is kept
    assert sorted(Dec(x["amount"]) for x in d2["uncleared"]) == [-300, 1200]                     # cleared lines are gone
    both = [x["line_id"] for x in d2["uncleared"]]
    after = client.post(f"{BR}/{d2['id']}/clear", headers=shop["accountant"], json={"line_ids": both}).json()
    assert Dec(after["difference"]) == 0
    assert client.post(f"{BR}/{d2['id']}/complete", headers=shop["accountant"]).status_code == 200
    listed = client.get(BR, headers=shop["accountant"], params={"company_id": shop["company"]}).json()
    assert [x["status"] for x in listed] == ["completed", "completed"]
    assert client.get(BR, headers=shop["accountant"], params={"status": "in_progress"}).json() == []
    assert client.get(f"{BR}/{d['id']}", headers=shop["accountant"]).json()["status"] == "completed"


def test_ticks_can_be_taken_off_and_everything_up_to_a_date_cleared(client, shop) -> None:  # type: ignore[no-untyped-def]
    manual(client, shop, "2026-11-02", "1020", "3000", "700", "November capital")
    manual(client, shop, "2026-11-03", "6000", "1020", "100", "November rent")
    d = start(client, shop, day="2026-11-10", balance="5600.00").json()
    path = f"{BR}/{d['id']}"
    assert Dec(d["cleared_balance"]) == 5100
    by_date = client.post(f"{path}/clear", headers=shop["accountant"], json={"until": "2026-11-02"}).json()
    assert Dec(by_date["cleared_balance"]) == 5800 and len(by_date["uncleared"]) == 1
    undone = client.post(f"{path}/clear", headers=shop["accountant"], json={
        "line_ids": [by_date["cleared"][0]["line_id"]], "cleared": False}).json()
    assert Dec(undone["cleared_balance"]) == 5100 and len(undone["uncleared"]) == 2
    both = client.post(f"{path}/clear", headers=shop["accountant"], json={"until": "2026-11-10"}).json()
    assert Dec(both["cleared_balance"]) == 5700 and Dec(both["difference"]) == -100            # statement is 100 short
    refused = client.post(f"{path}/complete", headers=shop["accountant"])
    assert refused.status_code == 409 and "over" in refused.json()["message"]
    assert client.post(f"{path}/clear", headers=shop["accountant"], json={"until": "2026-11-10"}).status_code == 200
    gone = client.delete(path, headers=shop["accountant"])                                      # throw it away
    assert gone.status_code == 204 and client.get(path, headers=shop["accountant"]).status_code == 404
    again = start(client, shop, day="2026-11-10", balance="5700.00").json()                       # lines are free again
    assert len(again["uncleared"]) == 2 and Dec(again["cleared_balance"]) == 5100
    assert client.delete(f"{BR}/{again['id']}", headers=shop["accountant"]).status_code == 204


def test_an_mpesa_account_is_reconciled_too(client, shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, net="1000", tax="160", business_date="2026-10-04",
                 payments=[{"method": "mobile_money", "amount": "1160.00"}])
    d = start(client, shop, code="1030", day="2026-10-31", balance="1160.00")
    assert d.status_code == 201, d.text
    done = client.post(f"{BR}/{d.json()['id']}/clear", headers=shop["accountant"], json={"until": "2026-10-31"}).json()
    assert Dec(done["difference"]) == 0
    assert client.post(f"{BR}/{d.json()['id']}/complete", headers=shop["accountant"]).status_code == 200


# --------------------------------------------------------------------------- statement lines
def test_statement_lines_suggest_and_clear_matches(client, shop) -> None:  # type: ignore[no-untyped-def]
    manual(client, shop, "2026-12-02", "1020", "3000", "2500", "Owner deposit DEP9001")
    manual(client, shop, "2026-12-04", "6000", "1020", "640", "December rent")
    d = start(client, shop, day="2026-12-10", balance="7510.00").json()   # 5100 + November 600 + 2500 - 640 - 50
    path = f"{BR}/{d['id']}/suggestions"
    csv = ("date,reference,description,amount\n2026-12-02,DEP9001,Deposit,2500.00\n"
           "2026-12-05,,Rent cheque,-640.00\n2026-12-09,CHG,Bank charges,-50.00\n")
    proposal = client.post(path, headers=shop["accountant"], json={"csv": csv})
    assert proposal.status_code == 200, proposal.text
    p = proposal.json()
    assert p["applied"] is False and len(p["suggestions"]) == 2
    assert {x["reason"].split(",")[0] for x in p["suggestions"]} == {"Same reference and amount", "Same amount"}
    assert [x["reference"] for x in p["unmatched"]] == ["CHG"]                    # not in the books: enter it first
    assert Dec(p["reconciliation"]["cleared_balance"]) == 5100                       # only proposed, nothing cleared
    manual(client, shop, "2026-12-09", "6400", "1020", "50", "Bank charges")
    applied = client.post(path, headers=shop["accountant"], json={"csv": csv, "apply": True}).json()
    assert applied["applied"] is True and len(applied["suggestions"]) == 3 and applied["unmatched"] == []
    r = applied["reconciliation"]
    assert Dec(r["cleared_balance"]) == 5100 + 2500 - 640 - 50 and Dec(r["difference"]) == 600   # November is still open
    rest = client.post(f"{BR}/{d['id']}/clear", headers=shop["accountant"], json={"until": "2026-11-30"}).json()
    assert Dec(rest["difference"]) == 0
    as_json = client.post(path, headers=shop["accountant"], json={"lines": [
        {"date": "2026-12-09", "reference": "X", "amount": "-1.00"}]})
    assert as_json.status_code == 200 and len(as_json.json()["unmatched"]) == 1
    for bad in ({}, {"lines": [], "csv": None}, {"csv": "x", "lines": [{"date": "2026-12-09", "amount": "1"}]},
                {"csv": "2026-12-01,A,x,notmoney"}, {"lines": [{"date": "2026-12-09", "amount": "0"}]},
                {"lines": [{"date": "soon", "amount": "5"}]}):
        assert client.post(path, headers=shop["accountant"], json=bad).status_code == 422, bad
    assert client.delete(f"{BR}/{d['id']}", headers=shop["accountant"]).status_code == 204


# --------------------------------------------------------------------------- rules and permissions
def test_validation(client, shop, bank) -> None:  # type: ignore[no-untyped-def]
    for code in ("1010", "4000", "1100", "1200", "1300", "6000"):                 # not bank, M-Pesa or card accounts
        assert start(client, shop, code=code, day="2027-01-31").status_code == 422, code
    stranger = client.post(BR, headers=shop["accountant"], json={
        "company_id": shop["company"], "account_id": str(uuid4()), "statement_date": "2027-01-31",
        "statement_balance": "1"})
    assert stranger.status_code == 422
    first = start(client, shop, day="2027-01-31", balance="0")
    assert first.status_code == 201, first.text
    assert start(client, shop, day="2027-02-28", balance="0").status_code == 409                  # one at a time
    path = f"{BR}/{first.json()['id']}"
    other_line = client.get(path, headers=shop["accountant"]).json()["uncleared"][0]["line_id"]
    assert client.post(f"{path}/clear", headers=shop["accountant"], json={"line_ids": [str(uuid4())]}
                       ).status_code == 422                                                       # not this account's line
    assert client.post(f"{path}/clear", headers=shop["accountant"], json={}).status_code == 422
    assert client.post(f"{path}/clear", headers=shop["accountant"], json={
        "line_ids": [other_line], "until": "2027-01-01"}).status_code == 422                      # one or the other
    assert client.post(BR, headers=shop["accountant"], json={
        "company_id": shop["company"], "account_id": shop["acc"]["1020"], "statement_date": "soon",
        "statement_balance": "1"}).status_code == 422
    assert client.get(f"{BR}/{uuid4()}", headers=shop["accountant"]).status_code == 404
    assert client.get(BR, headers=shop["accountant"], params={"status": "weird"}).status_code == 422
    assert client.delete(path, headers=shop["accountant"]).status_code == 204


def test_who_may_reconcile(client, shop, bank) -> None:  # type: ignore[no-untyped-def]
    for who in ("cashier", "storekeeper", "manager"):
        assert start(client, shop, day="2027-03-31", who=who).status_code == 403, who
        assert client.get(BR, headers=shop[who]).status_code == 403, who
    mine = start(client, shop, day="2027-03-31", balance="0", who="finance")
    assert mine.status_code == 201, mine.text
    path = f"{BR}/{mine.json()['id']}"
    assert client.get(path, headers=shop["manager"]).status_code == 403
    assert client.post(f"{path}/complete", headers=shop["cashier"]).status_code == 403
    assert client.delete(path, headers=shop["cashier"]).status_code == 403
    assert client.get(path, headers=shop["accountant"]).status_code == 200                       # company-wide roles see it
    assert client.delete(path, headers=shop["finance"]).status_code == 204


def test_a_period_cannot_close_with_a_reconciliation_in_progress(client, shop, bank) -> None:  # type: ignore[no-untyped-def]
    opened = start(client, shop, day="2027-05-31", balance="0")
    assert opened.status_code == 201, opened.text
    manual(client, shop, "2027-05-10", "6000", "1020", "10", "May rent")
    period = client.post(f"{FIN}/periods", headers=shop["finance"], json={
        "company_id": shop["company"], "day": "2027-05-10"}).json()
    checklist = client.get(f"{FIN}/periods/{period['id']}/checklist", headers=shop["finance"]).json()
    assert checklist["ready"] is False and "reconciliation is still in progress for account(s) 1020" in " ".join(
        checklist["problems"])
    refused = client.post(f"{FIN}/periods/{period['id']}/status", headers=shop["finance"], json={"status": "soft_closed"})
    assert refused.status_code == 422
    assert client.delete(f"{BR}/{opened.json()['id']}", headers=shop["finance"]).status_code == 204
    assert client.get(f"{FIN}/periods/{period['id']}/checklist", headers=shop["finance"]).json()["ready"] is True
