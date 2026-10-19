"""Time and Billing end to end: projects, rate cards, timesheets, timers, approval with separation of duties, unbilled work,
invoicing from approved time (tax, rounding, rollback), releasing on cancel, retainers, milestones, isolation."""

from datetime import date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system

TB = "/api/v1/timebilling"
TODAY = datetime.now(ZoneInfo("Africa/Nairobi")).date()
ISO = TODAY.isoformat()
# "yesterday" must be in the same Monday-to-Sunday week as today, or a week sent in would not hold it (on a Monday: today)
YESTERDAY = (TODAY - timedelta(days=1 if TODAY.weekday() else 0)).isoformat()


def monday(weeks_back: int) -> "date":
    """The Monday of a week in the past (each test uses a week of its own, so submitting one never closes another)."""
    return TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=weeks_back)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Time Co", stock="5")
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.timebilling.hooks  # noqa: F401

    registry.enable(s["tenant_id"], "timebilling")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    co = str(s["company_id"])
    r = client.put(f"{TB}/settings", headers=s["fm"], json={"company_id": co, "service_product_id": s["delivery"]})
    assert r.status_code == 200, r.text
    s["co"] = co
    s["client_customer"] = credit_customer(client, s, name="Acme Ltd", limit="1000000", terms=10)
    s["pid"] = {}
    for who in ("cashier", "manager", "fm", "boss"):
        s["pid"][who] = str(one(s, "select id from kernel.app_user where email = :e", e=f"{who}@{s['code']}.test"))
    return s


def project(client, shop, code, **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": shop["co"], "client_id": shop["client_customer"]["id"], "code": code, "name": f"Project {code}",
            "branch_id": str(shop["branch_id"]), **kw}
    r = client.post(f"{TB}/projects", headers=shop["manager"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def log(client, shop, who, pid, minutes, day=ISO, **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{TB}/entries", headers=shop[who], json={
        "project_id": pid, "work_date": day, "minutes": minutes, **kw})


def submit(client, shop, who):  # type: ignore[no-untyped-def]
    return client.post(f"{TB}/weeks/submit", headers=shop[who], json={"company_id": shop["co"], "week_start": ISO})


def week(client, shop, who):  # type: ignore[no-untyped-def]
    return client.get(f"{TB}/weeks/mine", headers=shop[who], params={"company_id": shop["co"], "week_start": ISO}).json()


def approve(client, shop, week_id, who="manager"):  # type: ignore[no-untyped-def]
    return client.post(f"{TB}/weeks/{week_id}/approve", headers=shop[who], json={})


def bill_rate(client, shop, rate, **kw):  # type: ignore[no-untyped-def]
    r = client.post(f"{TB}/rates", headers=shop["fm"], json={
        "company_id": shop["co"], "kind": "bill", "rate": rate, "effective_from": "2026-01-01", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def unbilled(client, shop, **params):  # type: ignore[no-untyped-def]
    return client.get(f"{TB}/unbilled", headers=shop["manager"], params={"company_id": shop["co"], **params}).json()


# --------------------------------------------------------------------------- permissions and isolation
def test_the_matrix_of_who_may_do_what(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": shop["co"], "client_id": shop["client_customer"]["id"], "code": "PERM", "name": "Perm"}
    assert client.post(f"{TB}/projects", headers=shop["cashier"], json=body).status_code == 403
    assert client.post(f"{TB}/projects", headers=shop["storekeeper"], json=body).status_code == 403
    assert client.get(f"{TB}/projects", headers=shop["storekeeper"], params={"company_id": shop["co"]}).status_code == 403
    assert client.post(f"{TB}/rates", headers=shop["manager"], json={
        "company_id": shop["co"], "kind": "bill", "rate": "10", "effective_from": ISO}).status_code == 403
    assert client.put(f"{TB}/settings", headers=shop["manager"], json={
        "company_id": shop["co"], "minute_step": 5}).status_code == 403
    assert client.get(f"{TB}/projects", params={"company_id": shop["co"]}).status_code in (401, 403)
    assert client.post(f"{TB}/invoice-reviews", headers=shop["cashier"], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"]}).status_code == 403
    assert client.get(f"{TB}/unbilled", headers=shop["cashier"], params={"company_id": shop["co"]}).status_code == 403


def test_another_business_sees_nothing(client, shop, tenants) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "ISO1")
    other = shop  # a second shop is costly: use the plain tenants fixture, which has no timebilling at all
    from tests.conftest import sign_in

    a = sign_in(client, "tenant-a", "owner@tenant-a.test").headers
    assert client.get(f"{TB}/projects/{p['id']}", headers=a).status_code in (403, 404)
    assert other["co"]


# --------------------------------------------------------------------------- logging time
def test_time_is_logged_in_minute_steps_and_never_in_the_future(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "STEP")
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "minute_step": 15}).status_code == 200
    bad = log(client, shop, "cashier", p["id"], 20)
    assert bad.status_code == 422 and "15 minutes" in bad.json()["message"]
    assert log(client, shop, "cashier", p["id"], 30).status_code == 201
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert log(client, shop, "cashier", p["id"], 15, day=tomorrow).status_code == 422
    assert log(client, shop, "cashier", p["id"], 24 * 60).status_code == 422                     # 30 + 1440 > a day
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "minute_step": 1}).status_code == 200


def test_a_project_that_is_not_active_takes_no_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "HOLD")
    assert client.patch(f"{TB}/projects/{p['id']}", headers=shop["manager"], json={"status": "on_hold"}).status_code == 200
    r = log(client, shop, "cashier", p["id"], 30)
    assert r.status_code == 422 and "on hold" in r.json()["message"]


def test_the_timer_runs_pauses_and_stops_into_an_entry(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "TIMER")
    h = shop["cashier"]
    key = {"Idempotency-Key": str(uuid4())}
    s1 = client.post(f"{TB}/timer/start", headers={**h, **key}, json={"project_id": p["id"], "task": "Calls"})
    assert s1.status_code == 201 and s1.json()["running"] is True
    assert client.post(f"{TB}/timer/start", headers={**h, **key}, json={"project_id": p["id"], "task": "Calls"}).status_code == 201
    second = client.post(f"{TB}/timer/start", headers=h, json={"project_id": p["id"]})
    assert second.status_code == 409                                                       # one timer per person
    assert client.post(f"{TB}/timer/pause", headers=h).json()["running"] is False
    assert client.post(f"{TB}/timer/pause", headers=h).status_code == 200                  # twice: no change
    assert client.get(f"{TB}/timer", headers=h).json()["task"] == "Calls"
    assert client.get(f"{TB}/timer", headers=shop["manager"]).json() is None
    hardly = client.post(f"{TB}/timer/stop", headers=h, json={})
    assert hardly.status_code == 422                                                       # ran for a second or so
    stopped = client.post(f"{TB}/timer/stop", headers=h, json={"minutes": 45})
    assert stopped.status_code == 200, stopped.text
    e = stopped.json()
    assert e["minutes"] == 45 and e["source"] == "timer" and e["started_at"] and e["ended_at"]
    assert client.get(f"{TB}/timer", headers=h).json() is None
    assert client.post(f"{TB}/timer/discard", headers=h).status_code == 404


def test_the_grid_saves_cells_and_is_safe_to_send_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "GRID")
    h = shop["manager"]
    cells = [{"project_id": p["id"], "work_date": YESTERDAY, "minutes": 120, "task": "Design"},
             {"project_id": p["id"], "work_date": ISO, "minutes": 60, "task": "Review"}]     # another task: on a Monday both days are one
    first = client.put(f"{TB}/grid", headers=h, json={"cells": cells})
    assert first.status_code == 200 and len(first.json()) == 2
    again = client.put(f"{TB}/grid", headers=h, json={"cells": cells})
    assert again.json() == []                                                                # nothing changed
    n = one(shop, "select count(*) from timebilling.entry where project_id = :p", p=p["id"])
    assert n == 2
    cleared = client.put(f"{TB}/grid", headers=h, json={"cells": [{**cells[1], "minutes": 0}]})
    assert cleared.status_code == 200
    assert one(shop, "select count(*) from timebilling.entry where project_id = :p", p=p["id"]) == 1


# --------------------------------------------------------------------------- the whole flow: time -> approval -> invoice
class Flow:
    """State shared by the ordered tests below."""
    project: dict = {}
    invoice: dict = {}
    review: dict = {}


def test_rates_pick_the_most_specific_row(client, shop) -> None:  # type: ignore[no-untyped-def]
    Flow.project = project(client, shop, "FLOW")
    bill_rate(client, shop, "100.00")                                           # everyone
    bill_rate(client, shop, "150.00", project_id=Flow.project["id"])             # this project
    bill_rate(client, shop, "120.00", user_id=shop["pid"]["manager"])            # the manager, any project
    cost = client.post(f"{TB}/rates", headers=shop["fm"], json={
        "company_id": shop["co"], "kind": "cost", "rate": "40.00", "effective_from": "2026-01-01"})
    assert cost.status_code == 201
    pick = client.get(f"{TB}/rates/explain", headers=shop["fm"], params={
        "company_id": shop["co"], "day": ISO, "project_id": Flow.project["id"], "user_id": shop["pid"]["manager"]})
    assert Dec(pick.json()["rate"]["rate"]) == 150                               # project (32) beats person (8)
    other = client.get(f"{TB}/rates/explain", headers=shop["fm"], params={
        "company_id": shop["co"], "day": ISO, "user_id": shop["pid"]["manager"]})
    assert Dec(other.json()["rate"]["rate"]) == 120
    # costs are for those who may see them
    assert [r["kind"] for r in client.get(f"{TB}/rates", headers=shop["manager"], params={"company_id": shop["co"]}).json()] \
        == ["bill", "bill", "bill"]


def test_a_week_is_submitted_and_only_someone_else_approves_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    pid = Flow.project["id"]
    assert log(client, shop, "cashier", pid, 90, task="Design").status_code == 201        # 1.5 h
    assert log(client, shop, "cashier", pid, 30, task="Review", billable=False).status_code == 201
    assert log(client, shop, "cashier", pid, 120, day=YESTERDAY, task="Build").status_code == 201   # 2 h
    assert log(client, shop, "manager", pid, 60, task="Design").status_code == 201        # 1 h
    spent = client.post(f"{TB}/expenses", headers=shop["cashier"], json={
        "project_id": pid, "expense_date": ISO, "description": "Printing", "amount": "100.00", "markup_percent": "10"})
    assert spent.status_code == 201, spent.text
    # nothing is billable before approval
    assert unbilled(client, shop, project_id=pid) == []
    s = submit(client, shop, "cashier")
    assert s.status_code == 200 and s.json()["status"] == "submitted"
    # a submitted week is closed to changes
    assert log(client, shop, "cashier", pid, 15).status_code == 409
    wk = week(client, shop, "cashier")
    entry_id = next(e["id"] for e in wk["entries"] if e["task"] == "Design")
    assert client.patch(f"{TB}/entries/{entry_id}", headers=shop["cashier"], json={"minutes": 60}).status_code == 409
    # the author cannot approve (not even with the permission), a log-only user cannot at all
    assert approve(client, shop, s.json()["id"], "cashier").status_code == 403
    assert submit(client, shop, "manager").status_code == 200
    mine = week(client, shop, "manager")
    assert approve(client, shop, mine["week_id"], "manager").status_code == 403           # own week
    assert "own time" in approve(client, shop, mine["week_id"], "manager").json()["message"]
    ok = approve(client, shop, s.json()["id"])
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert approve(client, shop, s.json()["id"]).status_code == 409                       # already decided
    assert approve(client, shop, mine["week_id"], "boss").status_code == 200
    # rates were fixed at approval: the cashier gets the project rate, the manager the project rate (32 > 8)
    rows = client.get(f"{TB}/entries", headers=shop["fm"], params={"project_id": pid}).json()
    assert {Dec(e["bill_rate"]) for e in rows} == {Dec(150)}
    assert all(Dec(e["cost_rate"]) == 40 for e in rows if e["status"] == "approved")
    cashier_rows = client.get(f"{TB}/entries", headers=shop["cashier"], params={"project_id": pid}).json()
    assert all(e["cost_rate"] is None for e in cashier_rows)                              # costs hidden from staff


def test_unbilled_work_is_valued_at_the_approved_rates(client, shop) -> None:  # type: ignore[no-untyped-def]
    rows = unbilled(client, shop, project_id=Flow.project["id"])
    assert len(rows) == 1
    # billable: 1.5 + 2 + 1 = 4.5 h at 150.00 = 675.00 (the 30 non-billable minutes are not); expense 100 + 10% = 110.00
    assert rows[0]["minutes"] == 270 and Dec(rows[0]["time_amount"]) == Dec("675.00")
    assert Dec(rows[0]["expense_amount"]) == Dec("110.00") and Dec(rows[0]["amount"]) == Dec("785.00")
    assert rows[0]["age_days"] == (1 if TODAY.weekday() else 0) and sum(Dec(v) for v in rows[0]["buckets"].values()) == Dec("785.00")


def test_the_review_groups_rounds_and_can_be_edited_before_issuing(client, shop) -> None:  # type: ignore[no-untyped-def]
    h = shop["manager"]
    r = client.post(f"{TB}/invoice-reviews", headers=h, json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "project_id": Flow.project["id"]})
    assert r.status_code == 201, r.text
    rev = r.json()
    Flow.review = rev
    kinds = [x["kind"] for x in rev["lines"]]
    assert kinds == ["time", "expense"] and Dec(rev["net_total"]) == Dec("785.00")
    assert rev["lines"][0]["minutes"] == 270 and "4.50 h at 150.00" in rev["lines"][0]["description"]
    # the work is set aside: a second review for the same client has nothing left
    again = client.post(f"{TB}/invoice-reviews", headers=h, json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "project_id": Flow.project["id"]})
    assert again.status_code == 422
    # group by person: the cashier's 3.5 billable hours and the manager's 1 hour become two lines
    by_person = client.patch(f"{TB}/invoice-reviews/{rev['id']}", headers=h, json={"group_by": "person"}).json()
    assert sorted(x["minutes"] for x in by_person["lines"] if x["kind"] == "time") == [60, 210]
    # round up to 30 minutes per line: 210 -> 210, 60 -> 60; 15-minute step on a 7-minute total would round, here no change
    r15 = client.patch(f"{TB}/invoice-reviews/{rev['id']}", headers=h, json={"round_minutes": 60}).json()
    assert sorted(x["minutes"] for x in r15["lines"] if x["kind"] == "time") == [60, 240]       # 210 -> 240
    assert Dec(r15["net_total"]) == Dec("750.00") + Dec("110.00")                                  # 5 h at 150 + expense
    back = client.patch(f"{TB}/invoice-reviews/{rev['id']}", headers=h, json={"round_minutes": 0, "group_by": "project"})
    rev = back.json()
    Flow.review = rev
    # edit the wording and billed hours of the time line; drop the expense and put it back
    tl = rev["lines"][0]
    edited = client.patch(f"{TB}/invoice-reviews/{rev['id']}/lines/{tl['id']}", headers=h, json={
        "description": "Website design and build", "minutes": 240,
        "write_down_reason": "Goodwill: the client waited"}).json()
    assert Dec(edited["net_total"]) == Dec("600.00") + Dec("110.00") and edited["lines"][0]["description"].startswith("Website")
    no_exp = client.delete(f"{TB}/invoice-reviews/{rev['id']}/lines/{edited['lines'][1]['id']}", headers=h).json()
    assert [x["kind"] for x in no_exp["lines"]] == ["time"]
    assert Dec(unbilled(client, shop, project_id=Flow.project["id"])[0]["expense_amount"]) == Dec("110.00")
    manual = client.post(f"{TB}/invoice-reviews/{rev['id']}/lines", headers=h, json={
        "description": "Travel", "amount": "50.00"}).json()
    assert Dec(manual["net_total"]) == Dec("650.00")
    Flow.review = manual
    assert client.patch(f"{TB}/invoice-reviews/{rev['id']}/lines/{tl['id']}", headers=h, json={"minutes": 270}).status_code == 200


def test_issuing_makes_one_invoice_with_tax_and_marks_the_work_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    h = shop["manager"]
    rid = Flow.review["id"]
    before = one(shop, "select count(*) from pos.sales_invoice")
    issued = client.post(f"{TB}/invoice-reviews/{rid}/issue", headers=h)
    assert issued.status_code == 200, issued.text
    out = issued.json()
    # net: time 270 min at 150 = 675.00 + travel 50.00 = 725.00; at 16% inclusive grossing: 675 -> 783.00, 50 -> 58.00 = 841.00
    assert out["status"] == "issued" and Dec(out["total"]) == Dec("841.00") and Dec(out["tax_total"]) == Dec("116.00")
    assert out["invoice_number"].startswith("INV-HQ-")
    Flow.invoice = out
    assert one(shop, "select count(*) from pos.sales_invoice") == before + 1
    # asking again returns the same invoice and makes nothing
    assert client.post(f"{TB}/invoice-reviews/{rid}/issue", headers=h).json()["invoice_id"] == out["invoice_id"]
    assert one(shop, "select count(*) from pos.sales_invoice") == before + 1
    inv = client.get(f"{POS}/invoices/{out['invoice_id']}", headers=shop["fm"]).json()
    assert inv["customer_id"] == shop["client_customer"]["id"] and Dec(inv["total"]) == Dec("841.00")
    assert one(shop, "select count(*) from timebilling.entry where invoice_id = :i", i=out["invoice_id"]) == 3
    # the work no longer shows as unbilled, and the review can no longer be edited or discarded
    left = unbilled(client, shop, project_id=Flow.project["id"])                              # only the expense I took off
    assert [(r["minutes"], Dec(r["expense_amount"])) for r in left] == [(0, Dec("110.00"))]
    assert client.patch(f"{TB}/invoice-reviews/{rid}", headers=h, json={"memo": "x"}).status_code == 409
    assert client.post(f"{TB}/invoice-reviews/{rid}/discard", headers=h).status_code == 409
    # an approved week with invoiced time cannot be reopened
    wk = week(client, shop, "cashier")
    assert client.post(f"{TB}/weeks/{wk['week_id']}/reopen", headers=shop["boss"], json={"note": "fix"}).status_code == 409


def test_cancelling_the_invoice_releases_the_work_and_it_can_be_billed_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    inv = Flow.invoice
    c = client.post(f"{POS}/invoices/{inv['invoice_id']}/cancel", headers=shop["fm"], json={"reason": "Wrong client rate"})
    assert c.status_code == 200, c.text
    assert one(shop, "select count(*) from timebilling.entry where invoice_id is not null and project_id = :p",
               p=Flow.project["id"]) == 0
    assert one(shop, "select status from timebilling.invoice_batch where id = :b", b=inv["id"]) == "cancelled"
    rows = unbilled(client, shop, project_id=Flow.project["id"])
    assert rows[0]["minutes"] == 270 and Dec(rows[0]["expense_amount"]) == Dec("110.00")      # the expense is back too
    # bill it again; the new invoice is a different one
    r = client.post(f"{TB}/invoice-reviews", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "project_id": Flow.project["id"]}).json()
    again = client.post(f"{TB}/invoice-reviews/{r['id']}/issue", headers=shop["manager"]).json()
    # 675.00 + 110.00 grossed up at 16%: 783.00 + 127.60 = 910.60
    assert again["invoice_id"] != inv["invoice_id"] and Dec(again["total"]) == Dec("910.60")


def test_an_invoice_the_customer_may_not_have_rolls_everything_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    poor = credit_customer(client, shop, name="Small Credit", limit="100", terms=5)
    p = client.post(f"{TB}/projects", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": poor["id"], "code": "POOR", "name": "Poor", "branch_id": str(shop["branch_id"])}).json()
    assert log(client, shop, "boss", p["id"], 240).status_code == 201
    assert client.post(f"{TB}/weeks/submit", headers=shop["boss"], json={
        "company_id": shop["co"], "week_start": ISO}).status_code == 200
    wk = week(client, shop, "boss")
    assert approve(client, shop, wk["week_id"], "manager").status_code == 200
    rev = client.post(f"{TB}/invoice-reviews", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": poor["id"]}).json()
    fail = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["manager"])
    assert fail.status_code == 422 and "credit limit" in fail.json()["message"]
    assert one(shop, "select status from timebilling.invoice_batch where id = :b", b=rev["id"]) == "draft"
    assert one(shop, "select count(*) from timebilling.entry where project_id = :p and invoice_id is not null",
               p=p["id"]) == 0
    assert one(shop, "select count(*) from pos.sales_invoice where source_id = :b", b=rev["id"]) == 0
    # discarding returns the work to unbilled
    assert client.post(f"{TB}/invoice-reviews/{rev['id']}/discard", headers=shop["manager"]).status_code == 200
    assert unbilled(client, shop, project_id=p["id"])[0]["minutes"] == 240


def test_a_rejected_week_goes_back_and_can_be_corrected(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "REJ")
    e = log(client, shop, "storekeeper", p["id"], 60)
    assert e.status_code == 403                                                              # no time.log
    old = monday(3).isoformat()
    assert log(client, shop, "cashier", p["id"], 60, day=old).status_code == 201
    s = client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={"company_id": shop["co"], "week_start": old})
    assert s.status_code == 200
    no_note = client.post(f"{TB}/weeks/{s.json()['id']}/reject", headers=shop["manager"], json={"note": ""})
    assert no_note.status_code == 422
    rej = client.post(f"{TB}/weeks/{s.json()['id']}/reject", headers=shop["manager"], json={"note": "Wrong project"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    wk = client.get(f"{TB}/weeks/mine", headers=shop["cashier"], params={"company_id": shop["co"], "week_start": old}).json()
    assert wk["decision_note"] == "Wrong project" and all(x["status"] == "draft" for x in wk["entries"])
    fix = client.patch(f"{TB}/entries/{wk['entries'][0]['id']}", headers=shop["cashier"], json={"minutes": 45})
    assert fix.status_code == 200
    assert client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={
        "company_id": shop["co"], "week_start": old}).status_code == 200
    # the author can take a submitted week back
    rec = client.post(f"{TB}/weeks/{s.json()['id']}/recall", headers=shop["cashier"])
    assert rec.status_code == 200 and rec.json()["status"] == "draft"


def test_a_company_approval_rule_decides_through_the_inbox(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": shop["co"], "doc_type": "timesheet", "approver_role_id": shop["roles"]["Branch Manager"],
        "min_amount": "0"})
    assert r.status_code == 201, r.text
    p = project(client, shop, "RULE")
    day = monday(5).isoformat()
    assert log(client, shop, "cashier", p["id"], 60, day=day).status_code == 201
    s = client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={"company_id": shop["co"], "week_start": day})
    assert s.status_code == 200, s.text
    assert s.json()["approval_pending"] is True
    direct = approve(client, shop, s.json()["id"], "manager")
    assert direct.status_code == 409 and "inbox" in direct.json()["message"]
    pending = next(x for x in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                   if x["doc_id"] == s.json()["id"])
    done = client.post(f"/api/v1/approvals/{pending['id']}/decision", headers=shop["boss"], json={"approve": True})
    assert done.status_code == 200, done.text
    assert one(shop, "select status from timebilling.week where id = :w", w=s.json()["id"]) == "approved"
    client.post("/api/v1/approvals/rules/off", headers=shop["owner"])              # (rule stays; later tests avoid weeks)
    with system(shop) as sess:
        sess.execute(text("update kernel.approval_rule set is_active = false where doc_type = 'timesheet'"))


# --------------------------------------------------------------------------- retainers and milestones
def test_an_hours_retainer_is_drawn_down_and_only_the_overage_is_billed(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "RET", billing_mode="retainer")
    r = client.post(f"{TB}/projects/{p['id']}/retainer", headers=shop["manager"], json={"kind": "hours",
                                                                                         "opening_minutes": 180})
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["balance_minutes"] == 180
    assert client.post(f"{TB}/projects/{p['id']}/retainer", headers=shop["manager"], json={"kind": "hours"}).status_code == 409
    day = monday(6).isoformat()
    assert log(client, shop, "cashier", p["id"], 120, day=day).status_code == 201           # all covered: 180 -> 60
    assert log(client, shop, "cashier", p["id"], 120, day=(monday(6) + timedelta(days=1)).isoformat()).status_code == 201
    # 60 minutes remain, so 60 of the second entry are covered and 60 are billed
    s = client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={"company_id": shop["co"], "week_start": day})
    assert approve(client, shop, s.json()["id"]).status_code == 200
    got = client.get(f"{TB}/retainers/{ret['id']}", headers=shop["manager"]).json()
    assert got["balance_minutes"] == 0
    hist = client.get(f"{TB}/retainers/{ret['id']}/history", headers=shop["manager"]).json()
    assert sorted(h["minutes"] for h in hist) == [-120, -60, 180]
    rows = unbilled(client, shop, project_id=p["id"])
    assert rows[0]["minutes"] == 60 and Dec(rows[0]["time_amount"]) == Dec("100.00")          # the generic rate, 1 h
    # a top-up is billed and adds to the balance when issued; cancelling the invoice takes it off again
    top = client.post(f"{TB}/retainers/{ret['id']}/topup", headers=shop["manager"], json={"minutes": 600, "amount": "1000.00"})
    assert top.status_code == 201, top.text
    done = client.post(f"{TB}/invoice-reviews/{top.json()['id']}/issue", headers=shop["manager"]).json()
    assert Dec(done["total"]) == Dec("1160.00")
    assert client.get(f"{TB}/retainers/{ret['id']}", headers=shop["manager"]).json()["balance_minutes"] == 600
    client.post(f"{POS}/invoices/{done['invoice_id']}/cancel", headers=shop["fm"], json={"reason": "Test"})
    assert client.get(f"{TB}/retainers/{ret['id']}", headers=shop["manager"]).json()["balance_minutes"] == 0
    with system(shop) as sess:                                                                # the integrity check
        from ziira.modules.timebilling.hooks import TimeBillingCheck

        assert TimeBillingCheck().run(sess) == []


def test_a_monthly_fee_retainer_covers_the_time_and_is_billed_once_a_month(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "FEE", billing_mode="retainer")
    r = client.post(f"{TB}/projects/{p['id']}/retainer", headers=shop["manager"], json={
        "kind": "monthly_fee", "monthly_fee": "500.00"}).json()
    day = monday(7).isoformat()
    assert log(client, shop, "cashier", p["id"], 300, day=day).status_code == 201
    s = client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={"company_id": shop["co"], "week_start": day})
    assert approve(client, shop, s.json()["id"]).status_code == 200
    assert unbilled(client, shop, project_id=p["id"]) == []                                  # time is covered by the fee
    fee = client.post(f"{TB}/retainers/{r['id']}/fee", headers=shop["manager"], json={"period": "2026-03"})
    assert fee.status_code == 201 and Dec(fee.json()["net_total"]) == Dec("500.00")
    assert client.post(f"{TB}/retainers/{r['id']}/fee", headers=shop["manager"], json={"period": "2026-03"}).status_code == 409
    assert client.post(f"{TB}/retainers/{r['id']}/fee", headers=shop["manager"], json={"period": "2026-04"}).status_code == 201


def test_fixed_fee_projects_are_billed_by_milestone(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "FIX", billing_mode="fixed_fee", fixed_fee="3000.00")
    m1 = client.post(f"{TB}/projects/{p['id']}/milestones", headers=shop["manager"], json={"name": "Design", "amount": "1000.00"}).json()
    client.post(f"{TB}/projects/{p['id']}/milestones", headers=shop["manager"], json={"name": "Build", "amount": "2000.00"})
    assert client.post(f"{TB}/projects/{project(client, shop, 'TM')['id']}/milestones", headers=shop["manager"],
                       json={"name": "x", "amount": "1"}).status_code == 422                 # not a fixed-fee project
    nothing = client.post(f"{TB}/invoice-reviews", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "project_id": p["id"]})
    assert nothing.status_code == 422                                                         # nothing is ready yet
    assert client.patch(f"{TB}/milestones/{m1['id']}", headers=shop["manager"], json={"status": "ready"}).status_code == 200
    rev = client.post(f"{TB}/invoice-reviews", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "project_id": p["id"]}).json()
    assert [x["kind"] for x in rev["lines"]] == ["milestone"] and Dec(rev["net_total"]) == Dec("1000.00")
    done = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["manager"]).json()
    assert Dec(done["total"]) == Dec("1160.00")
    ms = client.get(f"{TB}/projects/{p['id']}/milestones", headers=shop["manager"]).json()
    assert [(m["name"], m["status"]) for m in ms] == [("Design", "invoiced"), ("Build", "planned")]
    assert client.patch(f"{TB}/milestones/{m1['id']}", headers=shop["manager"], json={"status": "planned"}).status_code == 409


# --------------------------------------------------------------------------- reports
def test_project_summary_utilisation_and_csv(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = client.get(f"{TB}/projects/{Flow.project['id']}/summary", headers=shop["fm"]).json()
    # logged: cashier 90 + 30 + 120, manager 60 = 300 minutes, of which 270 billable
    assert s["logged_minutes"] == 300 and s["billable_minutes"] == 270
    # cost: 5 h at 40.00 = 200.00 plus the 100.00 spent; billed: the second invoice's lines, 675.00 + 110.00
    assert Dec(s["cost"]) == Dec("300.00") and Dec(s["billed_amount"]) == Dec("785.00")
    assert Dec(s["margin"]) == Dec("485.00") and Dec(s["margin_percent"]) == Dec("61.8")
    plain = client.get(f"{TB}/projects/{Flow.project['id']}/summary", headers=shop["manager"]).json()
    assert plain["cost"] is None and plain["margin"] is None                                  # costs only for those allowed
    u = client.get(f"{TB}/reports/utilisation", headers=shop["manager"], params={
        "company_id": shop["co"], "date_from": YESTERDAY, "date_to": ISO}).json()
    cash = next(x for x in u if x["user_id"] == shop["pid"]["cashier"])
    assert cash["logged_minutes"] >= 240 and Dec(cash["percent"]) > 0
    csv = client.get(f"{TB}/reports/entries.csv", headers=shop["manager"], params={"date_from": YESTERDAY, "date_to": ISO})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("Date,Person")
    assert client.get(f"{TB}/reports/entries.csv", headers=shop["cashier"], params={
        "date_from": YESTERDAY, "date_to": ISO}).status_code == 403


# --------------------------------------------------------------------------- Intelligence, Command Center and privacy
def seed_entry(shop, pid, who, day, minutes, *, billable=True, status="approved", rate="100.00"):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text(
            "insert into timebilling.entry (tenant_id, company_id, branch_id, user_id, project_id, work_date, minutes, "
            "billable, status, bill_rate) select :t, company_id, branch_id, :u, id, :d, :m, :b, :s, :r "
            "from timebilling.project where id = :p"),
            {"t": str(shop["tenant_id"]), "u": shop["pid"][who], "d": day, "m": minutes, "b": billable, "s": status,
             "r": rate if status == "approved" else None, "p": pid})


def client_project(client, shop, code, name, **kw):  # type: ignore[no-untyped-def]
    c = credit_customer(client, shop, name=name, limit="1000000")
    r = client.post(f"{TB}/projects", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": c["id"], "code": code, "name": f"Work for {name}",
        "branch_id": str(shop["branch_id"]), **kw})
    assert r.status_code == 201, r.text
    return c, r.json()


def run_check(shop, code):  # type: ignore[no-untyped-def]
    from ziira.modules.intel.services import engine

    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def findings(shop, code):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(
            "select id, entity_id, severity, amount, branch_id, status, summary, value, expected_value, evidence "
            "from intel.finding where check_code = :c order by first_seen_at"), {"c": code}).all()


def tune(client, shop, code, **params):  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/intel/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


def test_old_unbilled_work_is_flagged_with_its_value(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "timebilling.unbilled_ageing"
    old_c, old_p = client_project(client, shop, "AGE1", "Slow Payer Ltd")
    new_c, new_p = client_project(client, shop, "AGE2", "Fresh Work Ltd")
    seed_entry(shop, old_p["id"], "manager", TODAY - timedelta(days=45), 150)             # 2.5 h at 100.00 = 250.00
    seed_entry(shop, old_p["id"], "manager", TODAY - timedelta(days=44), 90)              # 1.5 h = 150.00
    seed_entry(shop, new_p["id"], "manager", TODAY - timedelta(days=5), 600)
    run_check(shop, code)
    mine = [f for f in findings(shop, code) if str(f.entity_id) == old_c["id"]]
    assert len(mine) == 1 and mine[0].amount == Dec("400.00") and str(mine[0].branch_id) == str(shop["branch_id"])
    assert "4.00 hours" in mine[0].summary and "45 days" in mine[0].summary and "Slow Payer Ltd" in mine[0].summary
    assert not [f for f in findings(shop, code) if str(f.entity_id) == new_c["id"]]       # only 5 days old
    tune(client, shop, code, unbilled_days=60)                                              # tuned: 45 days is fine now
    run_check(shop, code)
    assert [f.status for f in findings(shop, code) if str(f.entity_id) == old_c["id"]] != ["new"]
    tune(client, shop, code, unbilled_days=30)


def test_a_project_over_its_budget_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "timebilling.project_over_budget"
    _, over = client_project(client, shop, "BUD1", "Budget Over", budget_minutes=120)
    _, fine = client_project(client, shop, "BUD2", "Budget Fine", budget_minutes=600)
    seed_entry(shop, over["id"], "cashier", TODAY - timedelta(days=2), 180, status="draft")        # 150% of 2 h
    seed_entry(shop, fine["id"], "cashier", TODAY - timedelta(days=2), 60, status="draft")
    run_check(shop, code)
    found = {str(f.entity_id): f for f in findings(shop, code)}
    assert over["id"] in found and fine["id"] not in found
    assert found[over["id"]].value == Dec("150.0") and "BUD1" in found[over["id"]].summary
    assert found[over["id"]].severity == "high"                                              # 150 >= 100 + 25


def test_unsent_and_unapproved_timesheets_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, p = client_project(client, shop, "TS1", "Timesheet Ltd")
    old = monday(4)
    week_of = f"{old.day} {old:%b %Y}"          # findings show dates in the business's format
    seed_entry(shop, p["id"], "boss", old, 240, status="draft")
    run_check(shop, "timebilling.timesheets_not_submitted")
    mine = [f for f in findings(shop, "timebilling.timesheets_not_submitted") if str(f.entity_id) == shop["pid"]["boss"]
            and week_of in f.summary]
    assert len(mine) == 1 and "4.00 hours" in mine[0].summary
    with system(shop) as s:
        s.execute(text(
            "insert into timebilling.week (tenant_id, company_id, user_id, week_start, status, submitted_at, minutes) "
            "values (:t, :c, :u, :w, 'submitted', now() - interval '10 days', 240)"),
            {"t": str(shop["tenant_id"]), "c": shop["co"], "u": shop["pid"]["fm"], "w": monday(12)})
    run_check(shop, "timebilling.approval_waiting")
    waiting = findings(shop, "timebilling.approval_waiting")
    assert any("240" not in f.summary and "4.00 hours" in f.summary and "waiting 10 days" in f.summary for f in waiting)
    # once the week is sent in, the first finding closes by itself
    with system(shop) as s:
        s.execute(text(
            "insert into timebilling.week (tenant_id, company_id, user_id, week_start, status, minutes) "
            "values (:t, :c, :u, :w, 'submitted', 240)"),
            {"t": str(shop["tenant_id"]), "c": shop["co"], "u": shop["pid"]["boss"], "w": old})
    run_check(shop, "timebilling.timesheets_not_submitted")
    assert [f.status for f in findings(shop, "timebilling.timesheets_not_submitted")
            if str(f.entity_id) == shop["pid"]["boss"] and week_of in f.summary][0] != "new"


def test_a_retainer_running_out_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "timebilling.retainer_nearly_used"
    _, low = client_project(client, shop, "RETL", "Retainer Low", billing_mode="retainer")
    _, full = client_project(client, shop, "RETF", "Retainer Full", billing_mode="retainer")
    for p, balance in ((low, 60), (full, 540)):
        r = client.post(f"{TB}/projects/{p['id']}/retainer", headers=shop["manager"], json={
            "kind": "hours", "opening_minutes": 600})
        assert r.status_code == 201
        with system(shop) as s:                                                              # use some of it
            s.execute(text("update timebilling.retainer set balance_minutes = :b where id = :i"),
                      {"b": balance, "i": r.json()["id"]})
            s.execute(text(
                "insert into timebilling.retainer_txn (tenant_id, retainer_id, kind, minutes, occurred_on) "
                "values (:t, :i, 'drawdown', :m, :d)"),
                {"t": str(shop["tenant_id"]), "i": r.json()["id"], "m": balance - 600, "d": TODAY})
    run_check(shop, code)
    found = [f for f in findings(shop, code) if "RETL" in f.summary or "RETF" in f.summary]
    assert len(found) == 1 and found[0].value == Dec("90.0") and "RETL" in found[0].summary
    assert "1.00 hours left" in found[0].summary


def test_a_fall_in_the_billable_share_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "timebilling.billable_ratio_drop"
    _, p = client_project(client, shop, "RATIO", "Ratio Ltd")
    for i in range(14, 70):                                       # before: 8 h a day, all but 1 h billable
        with system(shop) as s:
            s.execute(text(
                "insert into timebilling.entry (tenant_id, company_id, branch_id, user_id, project_id, work_date, "
                "minutes, billable, status) select :t, company_id, branch_id, :u, id, :d, 420, true, 'draft' "
                "from timebilling.project where id = :p"),
                {"t": str(shop["tenant_id"]), "u": shop["pid"]["fm"], "d": TODAY - timedelta(days=i), "p": p["id"]})
        seed_entry(shop, p["id"], "boss", TODAY - timedelta(days=i), 60, billable=False, status="draft")
    for i in range(0, 14):                                        # now: half is not billable
        seed_entry(shop, p["id"], "fm", TODAY - timedelta(days=i), 240, status="draft")
        seed_entry(shop, p["id"], "boss", TODAY - timedelta(days=i), 240, billable=False, status="draft")
    run_check(shop, code)
    found = findings(shop, code)
    assert len(found) == 1 and found[0].value < found[0].expected_value
    assert found[0].expected_value > Dec("80") and found[0].value < Dec("65")


def test_the_command_center_figures_and_the_integrity_check(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.timebilling.hooks import TimeBillingCheck
    from ziira.modules.timebilling.pulse import TimeBillingPulse

    with system(shop) as s:
        figs = {(f.metric, f.branch_id): f for f in TimeBillingPulse().figures(s, shop["company_id"], TODAY)}
        assert figs[("timebilling.unbilled_value", None)].value > 0
        assert ("timebilling.timesheets_waiting", None) in figs
        assert figs[("timebilling.billable_hours_today", None)].kind == "count"
        assert TimeBillingCheck().run(s) == []


def test_client_notes_are_found_exported_and_erased(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.personal_data import Subject
    from ziira.modules.timebilling.privacy import TimeBillingPersonalData

    c, _ = client_project(client, shop, "PRIV", "Priv Client")
    r = client.put(f"{TB}/clients/{c['id']}", headers=shop["fm"], json={
        "company_id": shop["co"], "payment_terms_days": 14, "billing_notes": "Ask for Wanjiru Kamau in accounts"})
    assert r.status_code == 200 and r.json()["payment_terms_days"] == 14
    provider = TimeBillingPersonalData()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], Subject(raw="Wanjiru Kamau", name="Wanjiru Kamau"))
        assert [x.kind for x in found] == ["client_notes"]
        assert "Wanjiru" in str(provider.export(s, found[0]))
        out = provider.anonymise(s, found[0], "request")
        assert out.status == "anonymised"
        assert provider.find(s, shop["company_id"], Subject(raw="Wanjiru Kamau", name="Wanjiru Kamau")) == []
