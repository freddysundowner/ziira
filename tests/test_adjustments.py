"""Stock adjustments: draft, submit, approval matrix, posting, rejection, scope."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Adjust Co")
    co = str(s["company_id"])
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": co, "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"},
                  {"product_id": s["paint"], "quantity": "6", "unit_cost": "50", "batch_no": "B-LATE",
                   "expiry_date": "2027-09-01"},
                  {"product_id": s["paint"], "quantity": "4", "unit_cost": "50", "batch_no": "B-EARLY",
                   "expiry_date": "2027-03-01"}]})
    assert r.status_code == 201, r.text
    reasons = client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
    s["reason"] = next(x["id"] for x in reasons if x["category"] == "stock_adjustment" and x["code"] == "DAMAGED")
    s["write_off_reason"] = next(x["id"] for x in reasons if x["category"] == "write_off")
    return s


def draft(client, shop, lines, headers=None, **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/adjustments", headers=headers or shop["storekeeper"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "reason_code_id": shop["reason"],
        "lines": lines, **kw})


def cement(shop) -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select quantity from inventory.product_cost where product_id = :p"),
                         {"p": shop["cement"]}).scalar_one()


def line(shop, qty: str, product: str = "cement", **extra):  # type: ignore[no-untyped-def]
    return {"product_id": shop[product], "qty_change": qty, **extra}


# --------------------------------------------------------------------------- drafts
def test_a_draft_changes_nothing_and_gets_a_number(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = draft(client, shop, [line(shop, "-3")], note="Water damage")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "draft" and a["number"] == "ADJ-HQ-000001" and a["lines"][0]["qty_change"] == "-3.0000"
    assert cement(shop) == 100
    assert client.get(f"{INV}/adjustments/{a['id']}", headers=shop["manager"]).json()["number"] == a["number"]


def test_draft_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert draft(client, shop, [line(shop, "0")]).status_code == 422                       # nothing changes
    assert draft(client, shop, [line(shop, "1"), line(shop, "2")]).status_code == 422      # repeated product
    assert draft(client, shop, [line(shop, "1", "delivery")]).status_code == 422           # a service
    assert draft(client, shop, [line(shop, "1", "paint")]).status_code == 422              # which batch to add to?
    assert draft(client, shop, [line(shop, "1")], reason_code_id=shop["write_off_reason"]).status_code == 422
    assert draft(client, shop, [line(shop, "1")], reason_code_id=str(uuid4())).status_code == 422
    assert draft(client, shop, []).status_code == 422


def test_drafting_needs_stock_adjust_for_the_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert draft(client, shop, [line(shop, "1")], headers=shop["cashier"]).status_code == 403
    assert draft(client, shop, [line(shop, "1")], headers=shop["juja_keeper"]).status_code == 403   # other branch


def test_only_people_who_can_see_the_branch_can_read_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "1")]).json()
    assert client.get(f"{INV}/adjustments/{a['id']}", headers=shop["juja_keeper"]).status_code == 404
    mine = {x["id"] for x in client.get(f"{INV}/adjustments", headers=shop["storekeeper"]).json()}
    theirs = {x["id"] for x in client.get(f"{INV}/adjustments", headers=shop["juja_keeper"]).json()}
    assert a["id"] in mine and not theirs


# --------------------------------------------------------------------------- posting without approval
def submit(client, shop, adjustment_id, headers=None):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/adjustments/{adjustment_id}/submit", headers=headers or shop["storekeeper"])


def test_without_an_approval_rule_submit_posts_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "-3")], note="Dropped pallet").json()
    r = submit(client, shop, a["id"])
    assert r.status_code == 200 and r.json()["status"] == "posted" and r.json()["approved_by"] is None
    assert cement(shop) == 97
    moves = client.get(f"{INV}/movements", headers=shop["manager"], params={"source_id": a["id"]}).json()
    assert [(m["movement_type"], Dec(m["quantity"]), Dec(m["unit_cost"]), Dec(m["value"]), m["reason_code_id"])
            for m in moves] == [("adjustment", -3, 100, -300, shop["reason"])]
    assert submit(client, shop, a["id"]).status_code == 409                                   # already posted


def test_found_stock_is_valued_at_the_average_cost(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "2")], reason_code_id=next(
        x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=shop["owner"]).json()
        if x["category"] == "stock_adjustment" and x["code"] == "FOUND")).json()
    assert submit(client, shop, a["id"]).json()["status"] == "posted"
    assert cement(shop) == 99
    stock = client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["owner"]).json()
    assert (Dec(stock["average_cost"]), Dec(stock["value"])) == (100, 9900)


def test_an_adjustment_that_cannot_post_stays_a_draft(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "-500")]).json()
    r = submit(client, shop, a["id"])
    assert r.status_code == 422 and "Not enough stock" in r.json()["message"]
    assert client.get(f"{INV}/adjustments/{a['id']}", headers=shop["storekeeper"]).json()["status"] == "draft"
    assert cement(shop) == 99


def test_batch_tracked_stock_goes_out_first_expiry_first(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "-5", "paint")]).json()                    # 4 early + 6 late
    assert submit(client, shop, a["id"]).json()["status"] == "posted"
    moves = client.get(f"{INV}/movements", headers=shop["manager"], params={"source_id": a["id"]}).json()
    assert sorted(Dec(m["quantity"]) for m in moves) == [-4, -1]
    bal = client.get(f"{INV}/balances", headers=shop["manager"], params={"product_id": shop["paint"]}).json()
    assert [Dec(b["quantity"]) for b in bal] == [5]


# --------------------------------------------------------------------------- the approval matrix
@pytest.fixture(scope="module")
def rule(client, shop):  # type: ignore[no-untyped-def]
    """Adjustments worth 1,000 or more need a Branch Manager (company-wide) to approve."""
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "stock_adjustment",
        "approver_role_id": shop["roles"]["Branch Manager"], "min_amount": "1000"})
    assert r.status_code == 201, r.text
    return r.json()


def pending(client, shop, doc_id):  # type: ignore[no-untyped-def]
    return next(r for r in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                if r["doc_id"] == doc_id)


def decide(client, request_id, headers, approve=True, note=None):  # type: ignore[no-untyped-def]
    return client.post(f"/api/v1/approvals/{request_id}/decision", headers=headers,
                       json={"approve": approve, "note": note})


def test_small_adjustments_still_post_at_once(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "-5")]).json()                             # 500 < 1,000
    assert submit(client, shop, a["id"]).json()["status"] == "posted"


def test_a_large_adjustment_waits_for_approval_then_posts(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    before = cement(shop)
    a = draft(client, shop, [line(shop, "-20")], note="Roof leak").json()          # 2,000
    r = submit(client, shop, a["id"])
    assert r.json()["status"] == "pending_approval" and cement(shop) == before
    assert submit(client, shop, a["id"]).status_code == 409                        # not a draft any more
    request = pending(client, shop, a["id"])
    assert Dec(request["amount"]) == 2000
    # The storekeeper who wrote it, and a branch-level manager, cannot decide it
    assert decide(client, request["id"], shop["storekeeper"]).status_code == 403
    assert decide(client, request["id"], shop["manager"]).status_code == 403
    # A company-wide manager can
    r = decide(client, request["id"], shop["boss"])
    assert r.status_code == 200, r.text
    done = client.get(f"{INV}/adjustments/{a['id']}", headers=shop["manager"]).json()
    assert done["status"] == "posted" and done["approved_by"] is not None
    assert cement(shop) == before - 20
    moves = client.get(f"{INV}/movements", headers=shop["manager"], params={"source_id": a["id"]}).json()
    assert moves[0]["movement_type"] == "adjustment"


def test_a_rejected_adjustment_changes_nothing(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    before = cement(shop)
    a = draft(client, shop, [line(shop, "-30")]).json()
    submit(client, shop, a["id"])
    request = pending(client, shop, a["id"])
    assert decide(client, request["id"], shop["boss"], approve=False).status_code == 422      # reason needed
    assert decide(client, request["id"], shop["boss"], approve=False, note="Count it first").status_code == 200
    assert client.get(f"{INV}/adjustments/{a['id']}", headers=shop["manager"]).json()["status"] == "rejected"
    assert cement(shop) == before


def test_the_creator_cannot_approve_their_own_adjustment(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    a = draft(client, shop, [line(shop, "-25")], headers=shop["boss"]).json()
    submit(client, shop, a["id"], headers=shop["boss"])
    request = pending(client, shop, a["id"])
    assert decide(client, request["id"], shop["boss"]).status_code == 403                    # separation of duties


def test_the_approver_needs_the_stock_approve_permission(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    """A role can be named in the matrix, but only people who hold stock.approve can release stock."""
    roles = shop["roles"]
    # Finance Manager holds approvals.decide but not stock.approve; make the matrix ask for it
    client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "stock_adjustment", "step": 2,
        "approver_role_id": roles["Finance Manager"], "min_amount": "5000"})
    fin = shop["user"]("finance", "Finance Manager", None)
    a = draft(client, shop, [line(shop, "-55")]).json()                                      # 5,500: two steps
    submit(client, shop, a["id"])
    assert decide(client, pending(client, shop, a["id"])["id"], shop["boss"]).status_code == 200   # step 1
    step2 = next(r for r in client.get("/api/v1/approvals/pending", headers=fin).json() if r["doc_id"] == a["id"])
    r = decide(client, step2["id"], fin)
    assert r.status_code == 403 and "stock.approve" in r.json()["message"]
    assert client.get(f"{INV}/adjustments/{a['id']}", headers=shop["manager"]).json()["status"] == "pending_approval"
