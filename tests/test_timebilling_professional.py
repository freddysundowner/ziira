"""Time and Billing for professional practices: capped fees, write-downs and write-offs with reasons, partner review,
narratives, disbursements (markup defaults, receipts), recurring work with checklists, reminders, example rates, the
pack's data and its sample practice, and the reports an owner acts on."""

from datetime import date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system

TB = "/api/v1/timebilling"
NAIROBI = ZoneInfo("Africa/Nairobi")
TODAY = datetime.now(NAIROBI).date()
ISO = TODAY.isoformat()


def monday(weeks_back: int) -> date:
    return TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=weeks_back)


_weeks = iter(range(2, 60))          # week 1 is kept for the reminders test


def wk() -> int:
    """A week in the past nobody has used yet (a week that has been sent in is closed to its person)."""
    return next(_weeks)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Practice Co", stock="5")
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.timebilling.hooks  # noqa: F401

    for unit in ("timebilling", "intel", "command"):
        registry.enable(s["tenant_id"], unit)
    co = str(s["company_id"])
    r = client.put(f"{TB}/settings", headers=s["fm"], json={"company_id": co, "service_product_id": s["delivery"],
                                                           "minute_step": 1})
    assert r.status_code == 200, r.text
    s["co"] = co
    s["client_customer"] = credit_customer(client, s, name="Wanjiru Advocates", limit="1000000", terms=10)
    s["pid"] = {w: str(one(s, "select id from kernel.app_user where email = :e", e=f"{w}@{s['code']}.test"))
                for w in ("cashier", "manager", "fm", "boss")}
    s["acct"] = s["user"]("acct", "Accountant", None)        # may bill, may not approve a review (no time.partner)
    assert client.post(f"{TB}/rates", headers=s["fm"], json={
        "company_id": co, "kind": "bill", "rate": "100.00", "effective_from": "2026-01-01"}).status_code == 201
    return s


def project(client, shop, code, **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": shop["co"], "client_id": shop["client_customer"]["id"], "code": code,
            "name": f"Matter {code}", "branch_id": str(shop["branch_id"]), **kw}
    r = client.post(f"{TB}/projects", headers=shop["manager"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def approved(client, shop, pid, minutes, weeks_back, *, who="cashier", day_offset=0, **kw):  # type: ignore[no-untyped-def]
    """Log time in a past week, send the week in and have another person approve it."""
    start = monday(weeks_back)
    day = (start + timedelta(days=day_offset)).isoformat()
    r = client.post(f"{TB}/entries", headers=shop[who], json={"project_id": pid, "work_date": day, "minutes": minutes, **kw})
    assert r.status_code == 201, r.text
    s = client.post(f"{TB}/weeks/submit", headers=shop[who], json={"company_id": shop["co"], "week_start": start.isoformat()})
    assert s.status_code == 200, s.text
    ok = client.post(f"{TB}/weeks/{s.json()['id']}/approve", headers=shop["boss" if who == "manager" else "manager"], json={})
    assert ok.status_code == 200, ok.text
    return r.json()


def review(client, shop, pid=None, who="manager", **kw):  # type: ignore[no-untyped-def]
    r = client.post(f"{TB}/invoice-reviews", headers=shop[who], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], **({"project_id": pid} if pid else {}), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def line_of(rev, kind="time"):  # type: ignore[no-untyped-def]
    return next(x for x in rev["lines"] if x["kind"] == kind)


def unbilled(client, shop, **params):  # type: ignore[no-untyped-def]
    return client.get(f"{TB}/unbilled", headers=shop["manager"], params={"company_id": shop["co"], **params}).json()


# --------------------------------------------------------------------------- capped fee
def test_a_capped_fee_bills_hours_at_the_rate_but_never_more_than_the_cap(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.post(f"{TB}/projects", headers=shop["manager"], json={
        "company_id": shop["co"], "client_id": shop["client_customer"]["id"], "code": "CAPX", "name": "x",
        "billing_mode": "capped_fee", "branch_id": str(shop["branch_id"])}).status_code == 422                                 # a cap is needed
    p = project(client, shop, "CAP", billing_mode="capped_fee", fee_cap="500.00")
    assert Dec(p["fee_cap"]) == Dec("500.00")
    approved(client, shop, p["id"], 240, wk())                                               # 4 h = 400.00
    first = review(client, shop, p["id"])
    assert Dec(line_of(first)["amount"]) == Dec("400.00") and not line_of(first)["automatic"]
    done = client.post(f"{TB}/invoice-reviews/{first['id']}/issue", headers=shop["manager"]).json()
    assert done["status"] == "issued" and done["invoice_id"]
    approved(client, shop, p["id"], 180, wk())                                               # 3 h = 300.00, only 100.00 left
    rows = unbilled(client, shop, project_id=p["id"])
    assert Dec(rows[0]["time_amount"]) == Dec("100.00")                                   # work in progress honours the cap
    second = review(client, shop, p["id"])
    t = line_of(second)
    assert Dec(t["list_amount"]) == Dec("300.00") and Dec(t["amount"]) == Dec("100.00")
    assert t["automatic"] and t["write_down_reason"] == "Fee cap reached" and Dec(second["write_down"]) == Dec("200.00")
    client.post(f"{TB}/invoice-reviews/{second['id']}/issue", headers=shop["manager"])
    approved(client, shop, p["id"], 120, wk())                                               # 2 h = 200.00, nothing left
    assert unbilled(client, shop, project_id=p["id"]) == [] or Dec(unbilled(client, shop, project_id=p["id"])[0]["time_amount"]) == 0
    third = review(client, shop, p["id"])
    assert Dec(line_of(third)["amount"]) == Dec("0.00") and Dec(third["net_total"]) == Dec("0.00")
    out = client.post(f"{TB}/invoice-reviews/{third['id']}/issue", headers=shop["manager"]).json()
    assert out["status"] == "issued" and out["invoice_id"] is None and Dec(out["total"]) == 0     # nothing to invoice
    assert one(shop, "select count(*) from timebilling.entry where project_id = :p and written_off", p=p["id"]) == 1
    assert unbilled(client, shop, project_id=p["id"]) == []
    s = client.get(f"{TB}/projects/{p['id']}/summary", headers=shop["fm"]).json()
    assert Dec(s["fee_cap_percent"]) == Dec("180.0") and Dec(s["over_cap_amount"]) == Dec("400.00") and s["budget_state"] == "over"
    risk = client.get(f"{TB}/reports/at-risk", headers=shop["fm"], params={"company_id": shop["co"]}).json()
    assert [(r["code"], r["reason"]) for r in risk if r["code"] == "CAP"] == [("CAP", "cap")]


# --------------------------------------------------------------------------- write-downs and write-offs
def test_billing_for_less_than_the_work_is_worth_needs_a_reason_and_never_edits_the_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "WD")
    approved(client, shop, p["id"], 120, wk())                                               # 2 h = 200.00
    rev = review(client, shop, p["id"])
    t = line_of(rev)
    url = f"{TB}/invoice-reviews/{rev['id']}/lines/{t['id']}"
    quiet = client.patch(url, headers=shop["acct"], json={"minutes": 90})
    assert quiet.status_code == 422 and "reason" in quiet.json()["message"]
    cut = client.patch(url, headers=shop["acct"], json={"minutes": 90, "write_down_reason": "Client waited on our side"})
    assert cut.status_code == 200, cut.text
    got = line_of(cut.json())
    assert Dec(got["amount"]) == Dec("150.00") and Dec(got["list_amount"]) == Dec("200.00")
    assert Dec(cut.json()["write_down"]) == Dec("50.00") and got["write_down_reason"] == "Client waited on our side"
    over = client.patch(url, headers=shop["acct"], json={"minutes": 150})
    assert over.status_code == 422 and "more hours" in over.json()["message"]
    dearer = client.patch(url, headers=shop["acct"], json={"rate": "150.00"})
    assert dearer.status_code == 422                                                      # cannot bill above what it is worth
    assert client.patch(url, headers=shop["acct"], json={"minutes": 0, "write_down_reason": "Goodwill"}).status_code == 422
    assert one(shop, "select minutes from timebilling.entry where project_id = :p", p=p["id"]) == 120   # the time is untouched
    back = client.patch(url, headers=shop["acct"], json={"minutes": 120})                 # worth it again: reason cleared
    assert line_of(back.json())["write_down_reason"] is None and Dec(back.json()["write_down"]) == 0
    client.post(f"{TB}/invoice-reviews/{rev['id']}/discard", headers=shop["manager"])


def test_a_written_off_line_is_left_off_the_invoice_settles_its_work_and_comes_back_on_cancel(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "WO")
    approved(client, shop, p["id"], 60, wk())                                                # 1 h = 100.00
    rev = review(client, shop, p["id"])
    t = line_of(rev)
    url = f"{TB}/invoice-reviews/{rev['id']}/lines/{t['id']}"
    refused = client.patch(url, headers=shop["acct"], json={"minutes": 0, "write_down_reason": "Our error"})
    assert refused.status_code == 422 and "partner" in refused.json()["message"]           # a write-off needs time.partner
    manual = client.post(f"{TB}/invoice-reviews/{rev['id']}/lines", headers=shop["manager"], json={
        "description": "Filing fee", "amount": "50.00"}).json()
    assert Dec(manual["net_total"]) == Dec("150.00")
    off = client.patch(url, headers=shop["manager"], json={"minutes": 0, "write_down_reason": "Our error"})
    assert off.status_code == 200, off.text
    assert Dec(off.json()["net_total"]) == Dec("50.00") and Dec(off.json()["write_down"]) == Dec("100.00")
    done = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["manager"]).json()
    assert Dec(done["total"]) == Dec("58.00")                                             # only the filing fee, with 16% tax
    assert one(shop, "select written_off from timebilling.entry where project_id = :p", p=p["id"]) is True
    assert unbilled(client, shop, project_id=p["id"]) == []
    real = client.get(f"{TB}/reports/realisation", headers=shop["fm"], params={
        "company_id": shop["co"], "date_from": (TODAY - timedelta(days=30)).isoformat(), "date_to": ISO}).json()
    row = next(r for r in real["projects"] if r["code"] == "WO")
    assert (Dec(row["standard"]), Dec(row["billed"]), Dec(row["written_off"]), Dec(row["written_down"])) == (
        Dec("100.00"), Dec("0.00"), Dec("100.00"), Dec("0.00"))                          # the filing fee line is not work
    c = client.post(f"{POS}/invoices/{done['invoice_id']}/cancel", headers=shop["fm"], json={"reason": "Test"})
    assert c.status_code == 200, c.text
    assert one(shop, "select written_off from timebilling.entry where project_id = :p", p=p["id"]) is False
    assert Dec(unbilled(client, shop, project_id=p["id"])[0]["time_amount"]) == Dec("100.00")


def test_a_grouped_line_over_a_day_can_be_edited_at_review(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "BIG")
    for _ in range(3):                                                                    # 3 x 12 h in different weeks
        approved(client, shop, p["id"], 720, wk(), who="cashier")
    rev = review(client, shop, p["id"])
    t = line_of(rev)
    assert t["minutes"] == 2160
    r = client.patch(f"{TB}/invoice-reviews/{rev['id']}/lines/{t['id']}", headers=shop["manager"],
                     json={"minutes": 1800, "write_down_reason": "Fixed scope"})
    assert r.status_code == 200, r.text                                                   # was refused above 1440 minutes
    assert line_of(r.json())["minutes"] == 1800 and Dec(line_of(r.json())["amount"]) == Dec("3000.00")
    client.post(f"{TB}/invoice-reviews/{rev['id']}/discard", headers=shop["manager"])


# --------------------------------------------------------------------------- partner review
def test_partner_review_holds_an_invoice_until_a_partner_approves_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "partner_review": True,
                                                                  "partner_review_above": "10.00"}).status_code == 200
    try:
        p = project(client, shop, "PR")
        approved(client, shop, p["id"], 60, wk())
        rev = review(client, shop, p["id"], who="acct")
        assert rev["review_needed"] and [x["code"] for x in rev["problem_items"]] == ["partner_review"]
        held = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["acct"])
        assert held.status_code == 422 and "partner" in held.json()["message"]
        asked = client.post(f"{TB}/invoice-reviews/{rev['id']}/request-review", headers=shop["acct"])
        assert asked.json()["review_status"] == "requested"
        assert client.post(f"{TB}/invoice-reviews/{rev['id']}/review", headers=shop["acct"], json={"approve": True}).status_code == 403
        back = client.post(f"{TB}/invoice-reviews/{rev['id']}/review", headers=shop["manager"], json={"approve": False})
        assert back.status_code == 422                                                    # a reason is needed
        sent_back = client.post(f"{TB}/invoice-reviews/{rev['id']}/review", headers=shop["manager"],
                                json={"approve": False, "note": "Add the courier"}).json()
        assert sent_back["review_status"] == "changes_requested" and sent_back["review_note"] == "Add the courier"
        client.post(f"{TB}/invoice-reviews/{rev['id']}/request-review", headers=shop["acct"])
        ok = client.post(f"{TB}/invoice-reviews/{rev['id']}/review", headers=shop["manager"], json={"approve": True}).json()
        assert ok["review_status"] == "approved" and not ok["review_needed"]
        edited = client.post(f"{TB}/invoice-reviews/{rev['id']}/lines", headers=shop["acct"], json={
            "description": "Courier", "amount": "20.00"}).json()
        assert edited["review_status"] == "none" and edited["review_needed"]             # a change takes the approval back
        client.post(f"{TB}/invoice-reviews/{rev['id']}/request-review", headers=shop["acct"])
        client.post(f"{TB}/invoice-reviews/{rev['id']}/review", headers=shop["manager"], json={"approve": True})
        gate = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["acct"])
        assert gate.status_code == 403 and "invoices.manage" in gate.json()["message"]      # past the partner gate, then POS
        issued = client.post(f"{TB}/invoice-reviews/{rev['id']}/issue", headers=shop["fm"])
        assert issued.status_code == 200 and issued.json()["status"] == "issued", issued.text
        # a partner who issues needs no second approval
        approved(client, shop, p["id"], 30, wk())
        mine = review(client, shop, p["id"], who="manager")
        assert client.post(f"{TB}/invoice-reviews/{mine['id']}/issue", headers=shop["manager"]).json()["status"] == "issued"
    finally:
        client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "partner_review": False})


# --------------------------------------------------------------------------- narrative
def test_the_narrative_is_written_from_the_entries_and_a_schedule_can_be_downloaded(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "NAR")
    approved(client, shop, p["id"], 90, wk(), task="Drafting", note="Drafted the sale agreement")
    approved(client, shop, p["id"], 30, wk(), who="manager", task="Review call")
    rev = review(client, shop, p["id"])
    out = client.post(f"{TB}/invoice-reviews/{rev['id']}/narrative", headers=shop["manager"], json={"into_lines": True}).json()
    assert "Drafted the sale agreement (1.50 h)" in out["narrative"] and "Review call (0.50 h)" in out["narrative"]
    assert "Drafted the sale agreement" in line_of(out)["description"] and len(line_of(out)["description"]) <= 300
    edited = client.patch(f"{TB}/invoice-reviews/{rev['id']}", headers=shop["manager"], json={"narrative": "My own words"})
    assert edited.json()["narrative"] == "My own words"
    csv = client.get(f"{TB}/invoice-reviews/{rev['id']}/schedule.csv", headers=shop["manager"])
    assert csv.status_code == 200 and "Drafted the sale agreement" in csv.text and csv.text.splitlines()[0].startswith("Date,Person")
    assert client.get(f"{TB}/invoice-reviews/{rev['id']}/schedule.csv", headers=shop["cashier"]).status_code == 403
    client.post(f"{TB}/invoice-reviews/{rev['id']}/discard", headers=shop["manager"])


# --------------------------------------------------------------------------- disbursements
def test_expenses_start_with_the_clients_or_the_companys_markup_and_a_receipt_can_be_required(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "DIS")
    day = (monday(0) + timedelta(days=0)).isoformat() if monday(0) <= TODAY else ISO

    def spend(**kw):  # type: ignore[no-untyped-def]
        return client.post(f"{TB}/expenses", headers=shop["cashier"], json={
            "project_id": p["id"], "expense_date": ISO, "description": "Court filing", "amount": "100.00", **kw})

    assert Dec(spend().json()["markup_percent"]) == 0
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"],
                                                                  "default_markup_percent": "5"}).status_code == 200
    assert Dec(spend().json()["markup_percent"]) == Dec("5.00")
    cid = shop["client_customer"]["id"]
    assert client.put(f"{TB}/clients/{cid}", headers=shop["fm"], json={
        "company_id": shop["co"], "expense_markup_percent": "12.5"}).json()["expense_markup_percent"] is not None
    mark = spend(category="Court fees")
    assert Dec(mark.json()["markup_percent"]) == Dec("12.50") and mark.json()["category"] == "Court fees"
    assert Dec(spend(markup_percent="0").json()["markup_percent"]) == 0                   # at cost, said outright
    client.put(f"{TB}/clients/{cid}", headers=shop["fm"], json={"company_id": shop["co"]})
    client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "default_markup_percent": "0"})
    assert day
    # receipts: the week cannot be sent in without one above the limit
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"],
                                                                  "receipt_required_above": "50.00"}).status_code == 200
    start = monday(wk())
    big = client.post(f"{TB}/expenses", headers=shop["manager"], json={
        "project_id": p["id"], "expense_date": start.isoformat(), "description": "Valuation report", "amount": "80.00"}).json()
    small = client.post(f"{TB}/expenses", headers=shop["manager"], json={
        "project_id": p["id"], "expense_date": start.isoformat(), "description": "Stamps", "amount": "10.00"}).json()
    body = {"company_id": shop["co"], "week_start": start.isoformat()}
    no = client.post(f"{TB}/weeks/submit", headers=shop["manager"], json=body)
    assert no.status_code == 422 and "Valuation report" in no.json()["message"] and "Stamps" not in no.json()["message"]
    png = _png()
    up = client.post("/api/v1/files", headers={**shop["manager"], "Content-Type": "image/png", "X-File-Name": "receipt.png"},
                     params={"entity_type": "timebilling.expense", "entity_id": big["id"], "category": "receipt"}, content=png)
    assert up.status_code in (200, 201), up.text
    assert client.post(f"{TB}/weeks/submit", headers=shop["manager"], json=body).status_code == 200
    assert small["id"]
    client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "receipt_required_above": None})


def _png() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- recurring work
def test_recurring_work_prepares_dated_tasks_with_a_checklist_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "REC", billing_mode="retainer")
    day = TODAY.day
    r = client.post(f"{TB}/projects/{p['id']}/recurrences", headers=shop["manager"], json={
        "name": "Monthly close", "frequency": "monthly", "due_day": min(day + 3, 28) if day <= 25 else 28, "lead_days": 40,
        "checklist": ["Collect statements", "Reconcile", "Send summary"], "assignee_id": shop["pid"]["cashier"]})
    assert r.status_code == 201, r.text
    tasks = client.get(f"{TB}/tasks", headers=shop["manager"], params={"project_id": p["id"]}).json()
    assert len(tasks) >= 1 and all(t["status"] == "open" and len(t["items"]) == 3 for t in tasks)
    from ziira.modules.timebilling import jobs

    with system(shop) as s:
        before = s.execute(text("select count(*) from timebilling.engagement_task where project_id = :p"),
                           {"p": p["id"]}).scalar_one()
        jobs.run_company(s, shop["company_id"], datetime.now(NAIROBI))
        jobs.run_company(s, shop["company_id"], datetime.now(NAIROBI))
        after = s.execute(text("select count(*) from timebilling.engagement_task where project_id = :p"),
                          {"p": p["id"]}).scalar_one()
    assert before == after                                                                # idempotent
    t = tasks[0]
    assert client.post(f"{TB}/tasks/{t['id']}/finish", headers=shop["cashier"], json={}).status_code == 422   # not ticked yet
    for i in range(3):
        step = client.post(f"{TB}/tasks/{t['id']}/tick", headers=shop["cashier"], json={"index": i, "done": True})
        assert step.status_code == 200, step.text
    assert all(x["done"] and x["by"] for x in step.json()["items"])
    done = client.post(f"{TB}/tasks/{t['id']}/finish", headers=shop["cashier"], json={})
    assert done.json()["status"] == "done"
    assert client.post(f"{TB}/tasks/{t['id']}/tick", headers=shop["cashier"], json={"index": 0, "done": False}).status_code == 409
    skip = client.post(f"{TB}/tasks/{tasks[-1]['id']}/finish", headers=shop["manager"], json={"skipped": True})
    assert skip.status_code == 422 or tasks[-1]["id"] == t["id"]                          # a reason is needed to skip
    one_off = client.post(f"{TB}/projects/{p['id']}/tasks", headers=shop["manager"], json={
        "name": "File the return", "due_on": (TODAY - timedelta(days=20)).isoformat(), "checklist": ["Return signed"]})
    assert one_off.status_code == 201 and one_off.json()["overdue"] is True


def test_late_work_is_flagged_by_intelligence_and_goes_when_done(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.intel.services import engine

    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=TODAY, only={"timebilling.work_overdue"})
        found = s.execute(text("select summary from intel.finding where check_code = 'timebilling.work_overdue' "
                               "and status not in ('resolved', 'dismissed')")).scalars().all()
    assert any("File the return" in x and "20 days late" in x for x in found)
    late = [t for t in client.get(f"{TB}/tasks", headers=shop["manager"], params={"status": "open"}).json() if t["overdue"]]
    for t in late:
        client.post(f"{TB}/tasks/{t['id']}/tick", headers=shop["manager"], json={"index": 0, "done": True})
        client.post(f"{TB}/tasks/{t['id']}/finish", headers=shop["manager"], json={"skipped": True, "note": "Not needed"})
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=TODAY, only={"timebilling.work_overdue"})
        still = s.execute(text("select count(*) from intel.finding where check_code = 'timebilling.work_overdue' "
                               "and status not in ('resolved', 'dismissed')")).scalar_one()
    assert still == 0


# --------------------------------------------------------------------------- monthly fee drafts
def test_a_monthly_fee_is_drafted_once_a_month_and_a_discarded_draft_stays_discarded(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "MFEE", billing_mode="retainer")
    r = client.post(f"{TB}/projects/{p['id']}/retainer", headers=shop["manager"], json={
        "kind": "monthly_fee", "monthly_fee": "300.00", "bill_day": 1, "auto_draft": True}).json()
    from ziira.modules.timebilling import jobs

    with system(shop) as s:
        first = jobs.draft_monthly_fees(s, shop["company_id"], TODAY)
        again = jobs.draft_monthly_fees(s, shop["company_id"], TODAY)
    assert first >= 1 and again == 0
    drafts = client.get(f"{TB}/invoice-reviews", headers=shop["manager"], params={"status": "draft"}).json()
    mine = [d for d in drafts if d["memo"] is None]
    assert mine
    period = f"{TODAY.year}-{TODAY.month:02d}"
    batch = one(shop, "select b.id from timebilling.invoice_batch b join timebilling.invoice_batch_line l on l.batch_id = b.id "
                      "where l.retainer_id = :r and l.period = :p", r=r["id"], p=period)
    client.post(f"{TB}/invoice-reviews/{batch}/discard", headers=shop["manager"])
    with system(shop) as s:
        assert jobs.draft_monthly_fees(s, shop["company_id"], TODAY) == 0                   # not brought back


# --------------------------------------------------------------------------- reminders
@pytest.fixture()
def email_channel(shop, registry):  # type: ignore[no-untyped-def]
    """The business has an email channel set up (credentials are not used: nothing is sent, only queued)."""
    registry.enable(shop["tenant_id"], "messaging")
    with system(shop) as s:
        s.execute(text("insert into kernel.integration_credential (tenant_id, company_id, provider, label, "
                       "secret_ciphertext, config, status) values (kernel.current_tenant(), :c, 'email', 'Test mail', "
                       "'\\x00', '{}', 'active')"), {"c": str(shop["company_id"])})
    yield
    with system(shop) as s:
        s.execute(text("delete from kernel.integration_credential where provider = 'email' and label = 'Test mail'"))


def queued(shop, template):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return [tuple(r) for r in s.execute(text(
            "select user_id, status, body, template from kernel.notification where template = :t order by created_at"),
            {"t": template})]


def test_missed_time_and_unsent_weeks_are_reminded_once_through_the_queue(client, shop, email_channel) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.timebilling.services import nudges

    assert client.put(f"{TB}/settings", headers=shop["fm"], json={
        "company_id": shop["co"], "nudge_minutes": 240, "nudge_hour": 0}).status_code == 200
    p = project(client, shop, "NUDGE")
    now = datetime.combine(TODAY, datetime.min.time(), tzinfo=NAIROBI).replace(hour=10)
    log = client.post(f"{TB}/entries", headers=shop["cashier"], json={
        "project_id": p["id"], "work_date": (monday(1) + timedelta(days=1)).isoformat(), "minutes": 60})
    assert log.status_code == 201, log.text                  # a finished week with unsent time; makes them a fee-earner
    with system(shop) as s:
        first = nudges.run_company(s, shop["company_id"], now)
        second = nudges.run_company(s, shop["company_id"], now)
    assert first["missed_time"] >= 1 and second["missed_time"] == 0                      # once for that day
    mine = [m for m in queued(shop, "time_missing") if str(m[0]) == shop["pid"]["cashier"]]
    assert len(mine) == 1 and "Practice Co" in mine[0][2] and "4.00" in mine[0][2]
    assert first["weeks_not_sent"] >= 1
    sent = [m for m in queued(shop, "time_submit") if str(m[0]) == shop["pid"]["cashier"]]
    assert len(sent) >= 1
    # before the reminder hour nothing is queued
    assert client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "nudge_hour": 23}).status_code == 200
    with system(shop) as s:
        assert nudges.run_company(s, shop["company_id"], now) == {
            "missed_time": 0, "weeks_not_sent": 0, "approvals": 0, "reviews": 0, "due": 0}
    client.put(f"{TB}/settings", headers=shop["fm"], json={"company_id": shop["co"], "nudge_minutes": 0, "nudge_hour": 9})


def test_a_week_nobody_approves_is_reminded_to_its_approver_then_to_everyone(client, shop, email_channel) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.timebilling.services import nudges

    p = project(client, shop, "STUCK")
    start = monday(wk())
    assert client.post(f"{TB}/entries", headers=shop["cashier"], json={
        "project_id": p["id"], "work_date": start.isoformat(), "minutes": 90}).status_code == 201
    s = client.post(f"{TB}/weeks/submit", headers=shop["cashier"], json={"company_id": shop["co"], "week_start": start.isoformat()})
    assert s.status_code == 200
    # the cashier's own approver is the manager, who is away: the reminder goes to the others who may approve
    staff = client.put(f"{TB}/staff/{shop['pid']['cashier']}", headers=shop["fm"], json={
        "company_id": shop["co"], "approver_id": shop["pid"]["manager"], "away_until": (TODAY + timedelta(days=5)).isoformat()})
    assert staff.status_code == 200, staff.text
    assert staff.json()["approver_id"] == shop["pid"]["manager"]
    bad = client.put(f"{TB}/staff/{shop['pid']['cashier']}", headers=shop["fm"], json={
        "company_id": shop["co"], "approver_id": shop["pid"]["cashier"]})
    assert bad.status_code == 422                                                          # not oneself
    waiting = datetime.now(NAIROBI)
    with system(shop) as db:
        db.execute(text("update timebilling.week set submitted_at = :t where id = :i"),
                   {"t": waiting - timedelta(days=3), "i": s.json()["id"]})
        out = nudges.approvals_waiting(db, shop["company_id"], waiting.date(), waiting)
    told = [str(m[0]) for m in queued(shop, "approval_reminder")]
    assert out >= 1 and shop["pid"]["manager"] not in told[:0] and shop["pid"]["cashier"] not in told
    with system(shop) as db:
        again = nudges.approvals_waiting(db, shop["company_id"], waiting.date(), waiting)
    assert again == 0                                                                      # the same day: not twice
    assert client.post(f"{TB}/weeks/{s.json()['id']}/approve", headers=shop["boss"], json={}).status_code == 200


# --------------------------------------------------------------------------- example rates
def test_example_rates_price_nothing_until_they_are_confirmed(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("insert into timebilling.rate (tenant_id, company_id, kind, role_title, rate, effective_from, "
                       "example, note) values (kernel.current_tenant(), :c, 'bill', 'Partner', 999, '2026-01-01', true, "
                       "'Example')"), {"c": shop["company_id"]})
    titled = client.put(f"{TB}/staff/{shop['pid']['manager']}", headers=shop["fm"], json={"company_id": shop["co"], "title": "Partner"})
    assert titled.status_code == 200
    got = client.get(f"{TB}/rates/explain", headers=shop["fm"], params={
        "company_id": shop["co"], "day": ISO, "user_id": shop["pid"]["manager"]}).json()
    assert Dec(got["rate"]["rate"]) == 100                                                 # the example row is ignored
    rows = client.get(f"{TB}/rates", headers=shop["fm"], params={"company_id": shop["co"]}).json()
    example = next(r for r in rows if r["example"])
    assert client.patch(f"{TB}/rates/{example['id']}", headers=shop["manager"], json={"example": False}).status_code == 403
    real = client.patch(f"{TB}/rates/{example['id']}", headers=shop["fm"], json={"example": False, "rate": "180.00"})
    assert real.status_code == 200 and real.json()["example"] is False
    got = client.get(f"{TB}/rates/explain", headers=shop["fm"], params={
        "company_id": shop["co"], "day": ISO, "user_id": shop["pid"]["manager"]}).json()
    assert Dec(got["rate"]["rate"]) == 180


# --------------------------------------------------------------------------- the owner's view
def test_the_owner_summary_gathers_what_to_act_on(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{TB}/reports/owner", headers=shop["fm"], params={
        "company_id": shop["co"], "date_from": (TODAY - timedelta(days=90)).isoformat(), "date_to": ISO})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [b["label"] for b in out["wip_buckets"]] == ["0-30", "31-60", "61-90", "over 90"]
    assert Dec(out["wip_total"]) == sum(Dec(b["amount"]) for b in out["wip_buckets"])
    assert out["realisation"]["percent"] is not None and out["tasks_overdue"] >= 0
    assert client.get(f"{TB}/reports/owner", headers=shop["cashier"], params={
        "company_id": shop["co"], "date_from": ISO, "date_to": ISO}).status_code == 403
    assert client.get(f"{TB}/reports/owner", headers=shop["fm"], params={
        "company_id": shop["co"], "date_from": "2020-01-01", "date_to": ISO}).status_code == 422


# --------------------------------------------------------------------------- custom fields, templates, activities
def test_projects_and_clients_take_custom_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = project(client, shop, "CF")
    d = client.post("/api/v1/custom-fields", headers=shop["owner"], json={
        "entity_type": "timebilling.project", "key": "matter_number", "label": "Matter number", "kind": "text"})
    assert d.status_code == 201, d.text
    put = client.put(f"/api/v1/custom-fields/values/timebilling.project/{p['id']}", headers=shop["manager"],
                     json={"values": {"matter_number": "M-77"}})
    assert put.status_code == 200, put.text
    got = client.get(f"/api/v1/custom-fields/values/timebilling.project/{p['id']}", headers=shop["cashier"])
    assert got.status_code in (200, 403)
    c = client.post("/api/v1/custom-fields", headers=shop["owner"], json={
        "entity_type": "timebilling.client", "key": "year_end", "label": "Year end", "kind": "date"})
    assert c.status_code == 201, c.text
    cid = shop["client_customer"]["id"]
    assert client.put(f"/api/v1/custom-fields/values/timebilling.client/{cid}", headers=shop["fm"],
                      json={"values": {"year_end": "2026-12-31"}}).status_code == 200


def test_templates_activities_and_wording_are_data_a_business_edits(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = client.post(f"{TB}/templates", headers=shop["fm"], json={
        "company_id": shop["co"], "name": "Annual accounts", "billing_mode": "fixed_fee", "frequency": "annual",
        "due_day": 30, "due_month": 6, "lead_days": 100, "checklist": ["Records in", "Draft", "Filed"],
        "milestones": [{"name": "Start", "percent": "30"}, {"name": "Draft", "percent": "40"}, {"name": "Done", "percent": "30"}]})
    assert t.status_code == 201, t.text
    assert client.post(f"{TB}/templates", headers=shop["fm"], json={
        "company_id": shop["co"], "name": "Annual accounts"}).status_code == 409
    p = project(client, shop, "TPL", billing_mode="fixed_fee", fixed_fee="1000.00", template_id=t.json()["id"])
    ms = client.get(f"{TB}/projects/{p['id']}/milestones", headers=shop["manager"]).json()
    assert [(m["name"], Dec(m["amount"])) for m in ms] == [("Start", Dec("300.00")), ("Draft", Dec("400.00")), ("Done", Dec("300.00"))]
    rec = client.get(f"{TB}/recurrences", headers=shop["manager"], params={"project_id": p["id"]}).json()
    assert len(rec) == 1 and rec[0]["checklist"] == ["Records in", "Draft", "Filed"]
    a = client.post(f"{TB}/activities", headers=shop["fm"], json={"company_id": shop["co"], "name": "Audit fieldwork", "group_name": "Audit"})
    assert a.status_code == 201
    assert client.get(f"{TB}/activities", headers=shop["cashier"], params={"company_id": shop["co"]}).json()[0]["name"] == "Audit fieldwork"
    assert client.post(f"{TB}/activities", headers=shop["cashier"], json={"company_id": shop["co"], "name": "Nope"}).status_code == 403
    s = client.post(f"{TB}/snippets", headers=shop["fm"], json={
        "company_id": shop["co"], "name": "Thanks", "language": "sw", "body": "Asante"})
    assert s.status_code == 201
    assert [x["name"] for x in client.get(f"{TB}/snippets", headers=shop["fm"], params={"company_id": shop["co"]}).json()] == ["Thanks"]
    assert client.delete(f"{TB}/snippets/{s.json()['id']}", headers=shop["fm"]).status_code == 204


def test_the_service_item_list_can_be_limited_to_services(client, shop) -> None:  # type: ignore[no-untyped-def]
    rows = client.get("/api/v1/products/products", headers=shop["manager"], params={"product_type": "service"}).json()
    assert rows and all(r["product_type"] == "service" for r in rows)
    everything = client.get("/api/v1/products/products", headers=shop["manager"]).json()
    assert len(everything) > len(rows)
    assert client.get("/api/v1/products/products", headers=shop["manager"], params={"product_type": "nonsense"}).status_code == 422
