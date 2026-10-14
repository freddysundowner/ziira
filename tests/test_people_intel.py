"""Intelligence checks and Command Center figures over People: a real business, real payroll runs, the real engine.

The business (no statutory rules, so net pay equals gross pay and every figure can be worked out by hand):

  Ann   HQ    basic 50000, raised to 65000 from 2026-09-01 (a raise proposed and approved in September)
  Ben   HQ    basic 20000, mobile money details set up on 2026-09-20 (his first)
  Cara  Juja  basic 100000
  Eve   Juja  basic 40000, bank details changed on 2026-09-22
  Dan   HQ    basic 30000, joined on 2026-09-15 (so 16 of the 30 days of September are paid: 16000)

August (paid): Ann, Ben, Cara, Eve.  September (paid): all five.  Today is 2026-10-14.
"""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any

import pytest
from sqlalchemy import text

from tests.people_helpers import PEOPLE, make_people_shop, new_employee
from tests.stock_helpers import system
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import baselines, engine
from ziira.modules.people.intel_checks import (
    ChangesBeforePayroll,
    LeaveWaiting,
    OvertimeHoursMetric,
    PaidWithoutAttendance,
    PayApprovedBySameUser,
    PayJumpWithoutChange,
    PayrollOverdue,
    UnusualOvertime,
)

TODAY = date(2026, 10, 14)
RUNS = f"{PEOPLE}/payroll-runs"
INTEL = "/api/v1/intel"


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    """Run a statement in the business's database (to set the clock back on records, or read them)."""
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def period(start: str, end: str, pay: str) -> dict[str, str]:
    return {"period_start": start, "period_end": end, "pay_date": pay}


def finish_run(client, shop, body: dict[str, str], *, pay: bool = True) -> str:  # type: ignore[no-untyped-def]
    """Create, calculate, submit, approve (by someone else) and optionally pay a payroll run."""
    made = client.post(RUNS, headers=shop["finance"], json={"company_id": shop["company"], **body})
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    steps = [("calculate", "finance"), ("submit", "finance"), ("approve", "owner")] + ([("pay", "finance")] if pay else [])
    for action, who in steps:
        r = client.post(f"{RUNS}/{rid}/{action}", headers=shop[who], json={} if action == "pay" else None)
        assert r.status_code == 200, (action, r.text)
    return str(rid)


def staff(client, shop, name, branch, basic, *, hire="2025-01-06", start="2025-01-06", bank=None):  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, name, branch_id=str(branch), hire_date=hire)
    terms = client.post(f"{PEOPLE}/employees/{e['id']}/terms", headers=shop["hr"], json={
        "basic_pay": basic, "valid_from": start}).json()
    assert client.post(f"{PEOPLE}/terms/{terms['id']}/approve", headers=shop["finance"]).status_code == 200
    if bank:
        b = client.post(f"{PEOPLE}/employees/{e['id']}/bank-accounts", headers=shop["hr"], json={
            "method": bank[0], "account_no": bank[1], "bank_name": "First Bank" if bank[0] == "bank" else None}).json()
        assert client.post(f"{PEOPLE}/bank-accounts/{b['id']}/approve", headers=shop["finance"]).status_code == 200
    return e


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "People Intel Co")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    hq, juja = s["branch_id"], s["juja"]
    s["ann"] = staff(client, s, "Ann Otieno", hq, "50000")
    s["ben"] = staff(client, s, "Ben Kamau", hq, "20000", bank=("mobile_money", "0712345678"))
    s["cara"] = staff(client, s, "Cara Wanjiru", juja, "100000")
    s["eve"] = staff(client, s, "Eve Achieng", juja, "40000", bank=("bank", "01234567890"))
    s["currency"] = sql(s, "select base_currency from kernel.company")[0][0]
    sql(s, "update people.employee set created_at = '2025-01-06'")
    sql(s, "update people.employment_terms set created_at = '2025-01-06'")
    sql(s, "update people.employee_bank_account set valid_from = '2025-01-06' where employee_id = :e",
        e=s["eve"]["id"])
    sql(s, "update people.employee_bank_account set valid_from = '2026-09-20' where employee_id = :e",
        e=s["ben"]["id"])
    s["aug"] = finish_run(client, s, period("2026-08-01", "2026-08-31", "2026-08-31"))
    # September's changes: Ann's raise, Eve's new bank details, and Dan joins
    raise_ = client.post(f"{PEOPLE}/employees/{s['ann']['id']}/terms", headers=s["hr"], json={
        "basic_pay": "65000", "valid_from": "2026-09-01"}).json()
    assert client.post(f"{PEOPLE}/terms/{raise_['id']}/approve", headers=s["finance"]).status_code == 200
    s["ann_raise"] = raise_["id"]
    eve_bank = client.post(f"{PEOPLE}/employees/{s['eve']['id']}/bank-accounts", headers=s["hr"], json={
        "method": "bank", "account_no": "09876543210", "bank_name": "First Bank"}).json()
    assert client.post(f"{PEOPLE}/bank-accounts/{eve_bank['id']}/approve", headers=s["finance"]).status_code == 200
    s["dan"] = staff(client, s, "Dan Mutua", hq, "30000", hire="2026-09-15", start="2026-09-15")
    s["sept"] = finish_run(client, s, period("2026-09-01", "2026-09-30", "2026-09-30"))
    # the clock: when each thing really happened
    sql(s, "update people.employment_terms set created_at = '2026-09-20' where id = :i", i=s["ann_raise"])
    sql(s, "update people.employee_bank_account set valid_from = '2026-09-22' where id = :i", i=eve_bank["id"])
    sql(s, "update people.employee_bank_account set valid_to = '2026-09-22' where employee_id = :e and id <> :i",
        e=s["eve"]["id"], i=eve_bank["id"])
    sql(s, "update people.employee set created_at = '2026-09-20' where id = :i", i=s["dan"]["id"])
    sql(s, "update people.employment_terms set created_at = '2026-09-20' where employee_id = :e", e=s["dan"]["id"])
    for run_id, created, submitted, approved in ((s["aug"], "2026-08-28", "2026-08-29", "2026-08-31 10:00+00"),
                                                  (s["sept"], "2026-09-28", "2026-09-29", "2026-09-30 10:00+00")):
        sql(s, "update people.payroll_run set created_at = cast(:c as timestamptz), submitted_at = cast(:s as timestamptz), "
               "approved_at = cast(:a as timestamptz) where id = :i", c=created, s=submitted, a=approved, i=run_id)
    return s


def run_check(shop, code: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def findings(client, shop, code: str, *statuses: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {"check_code": code, "limit": 100}
    if statuses:
        params["status"] = list(statuses)
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def detail(client, shop, finding: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return client.get(f"{INTEL}/findings/{finding['id']}", headers=shop["owner"]).json()


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    """The check run on its own with some limits changed, as the business may set them."""
    with system(shop) as s:
        known = baselines.load(s, shop["company_id"])
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=known.get)
        return check.run(s, ctx)


def named(items: list[dict[str, Any]], who: str) -> dict[str, Any]:
    return next(f for f in items if f["summary"].startswith(who))


# --------------------------------------------------------------------------- changes just before payroll
def test_people_added_or_changed_just_before_a_run_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    result = run_check(shop, "people.changes_before_payroll")
    assert result.created == 3 and not result.failed
    items = findings(client, shop, "people.changes_before_payroll")
    assert len(items) == 3
    cur = shop["currency"]
    dan, ann, eve = named(items, "Dan"), named(items, "Ann"), named(items, "Eve")
    assert "was added on 2026-09-20" in dan["summary"] and f"paid {cur} 16,000.00" in dan["summary"]
    assert dan["severity"] == "high" and Dec(dan["amount"]) == 16000 and dan["branch_id"] == str(shop["branch_id"])
    assert f"from {cur} 50,000.00 to {cur} 65,000.00 on 2026-09-20" in ann["summary"]
    assert Dec(ann["amount"]) == 65000 and ann["period_start"] == "2026-09-01" and ann["period_end"] == "2026-09-30"
    assert "payment details changed on 2026-09-22" in eve["summary"] and eve["branch_id"] == str(shop["juja"])
    assert Dec(eve["amount"]) == 40000
    labels = {r["type"] for r in detail(client, shop, ann)["records"]}
    assert labels == {"people.payroll_run", "people.employee", "people.employment_terms"}
    assert detail(client, shop, ann)["figures"]["basic_pay_after"] == "65000.00"
    # Ben's first-ever payment details, and Cara, are not changes; nothing in August's window either
    assert not any(f["summary"].startswith(("Ben", "Cara")) for f in items)
    assert all("2026-08-01" not in f["summary"] for f in items)


def test_changes_before_payroll_is_an_event_and_follows_its_window(client, shop) -> None:  # type: ignore[no-untyped-def]
    again = run_check(shop, "people.changes_before_payroll")
    assert (again.created, again.updated, again.resolved) == (0, 3, 0)           # same problems, same findings
    assert len(direct(shop, ChangesBeforePayroll(), days=14)) == 3
    # a 3 day window ends before anything changed (the changes were 10 days before the run was approved)
    assert direct(shop, ChangesBeforePayroll(), days=3) == []
    # a look-back of 10 days leaves out both runs (their pay dates are older), so there is nothing to read
    assert direct(shop, ChangesBeforePayroll(), lookback_days=10) == []


# --------------------------------------------------------------------------- paid, no attendance
def insert_attendance(shop, employee, day: date, hours: str = "8", overtime: str = "0") -> None:  # type: ignore[no-untyped-def]
    branch = shop["branch_id"] if employee["branch_id"] == str(shop["branch_id"]) else shop["juja"]
    sql(shop, "insert into people.attendance (tenant_id, employee_id, branch_id, work_date, hours, overtime_hours, source) "
              "values (:t, :e, :b, :d, :h, :o, 'manual')",
        t=str(shop["tenant_id"]), e=employee["id"], b=str(branch), d=day, h=hours, o=overtime)


def test_a_person_paid_with_no_attendance_is_flagged_where_attendance_is_used(client, shop) -> None:  # type: ignore[no-untyped-def]
    # August: nobody has attendance, so the business does not seem to use it: silence
    assert run_check(shop, "people.paid_without_attendance").created == 0
    leave_type = client.post(f"{PEOPLE}/leave-types", headers=shop["hr"], json={
        "company_id": shop["company"], "name": "Annual", "days_per_year": "21"}).json()["id"]
    shop["annual"] = leave_type
    for who in ("ann", "ben"):
        for d in (date(2026, 9, 1), date(2026, 9, 2)):
            insert_attendance(shop, shop[who], d)
    sql(shop, "insert into people.leave_request (tenant_id, employee_id, leave_type_id, start_date, end_date, days, status) "
              "values (:t, :e, :l, '2026-09-10', '2026-09-12', 3, 'approved')",
        t=str(shop["tenant_id"]), e=shop["cara"]["id"], l=leave_type)
    result = run_check(shop, "people.paid_without_attendance")
    assert result.created == 2
    items = findings(client, shop, "people.paid_without_attendance")
    dan, eve = named(items, "Dan"), named(items, "Eve")
    cur = shop["currency"]
    assert f"paid {cur} 16,000.00 gross for 2026-09-01 to 2026-09-30" in dan["summary"]
    assert "3 of 5 people paid in the same run do" in dan["summary"]
    assert dan["severity"] == "medium" and Dec(dan["amount"]) == 16000 and dan["branch_id"] == str(shop["branch_id"])
    assert Dec(eve["amount"]) == 40000 and eve["branch_id"] == str(shop["juja"])
    assert not any(f["summary"].startswith(("Ann", "Ben", "Cara")) for f in items)   # worked, or on approved leave
    # tuned: if the business only counts as using attendance when 70% have records, 60% is not enough
    assert direct(shop, PaidWithoutAttendance(), usage_pct="70.0") == []
    assert len(direct(shop, PaidWithoutAttendance(), usage_pct="60.0")) == 2


# --------------------------------------------------------------------------- unusual overtime
def test_overtime_far_above_a_persons_own_normal_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    ann, ben = shop["ann"], shop["ben"]
    for i in range(20):                                         # Ann: an hour a day from 14 Sep to 3 Oct (and none on 1-2 Sep)
        insert_attendance(shop, ann, date(2026, 9, 14) + timedelta(days=i), "9", "1")
    for i in range(5):                                          # Ben: an hour a day from 8 to 12 Oct (little history)
        insert_attendance(shop, ben, date(2026, 10, 8) + timedelta(days=i), "9", "1")
    insert_attendance(shop, ann, date(2026, 10, 12), "9.5", "1.5")      # a little more, below the 2 hour floor
    insert_attendance(shop, ann, date(2026, 10, 13), "16", "8")         # the spike
    insert_attendance(shop, ben, date(2026, 10, 13), "16", "8")         # the same spike, but no history to judge by
    with system(shop) as s:
        stored = baselines.refresh_company(s, shop["company_id"], TODAY, metrics=[OvertimeHoursMetric()])
    assert stored == 3                                          # Ann, Ben, and the HQ branch
    result = run_check(shop, "people.unusual_overtime")
    assert result.created == 2
    items = findings(client, shop, "people.unusual_overtime")
    ann_f = named(items, "Ann")
    assert ann_f["severity"] == "medium" and ann_f["branch_id"] == str(shop["branch_id"])
    assert "worked 8.00 hours of overtime on 2026-10-13" in ann_f["summary"] and "about 1.2 hours a day" in ann_f["summary"]
    assert Dec(ann_f["value"]) == 8 and ann_f["period_start"] == "2026-10-13"
    assert round(Dec(ann_f["expected_value"]), 1) == Dec("1.2")
    hq = next(f for f in items if f["entity_type"] == "kernel.branch")
    assert "recorded 16.00 hours of overtime on 2026-10-13" in hq["summary"] and Dec(hq["value"]) == 16
    assert hq["branch_id"] == str(shop["branch_id"])
    assert not any(f["summary"].startswith("Ben") for f in items)        # six observations: too little to know
    # tuned: a higher floor leaves the 8 hour day alone; a one-day window (today only) no longer reaches 13 Oct
    assert direct(shop, UnusualOvertime(), min_hours="20.0") == []
    assert direct(shop, UnusualOvertime(), recent_days=1) == []
    assert len(direct(shop, UnusualOvertime(), recent_days=2)) == 2


# --------------------------------------------------------------------------- approved by the proposer
def test_pay_proposed_and_approved_by_one_person_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert run_check(shop, "people.pay_self_approved").created == 0                    # the app made it two people
    sql(shop, "update people.employment_terms set approved_by = created_by, created_at = '2026-09-01' "
              "where employee_id = :e", e=shop["cara"]["id"])
    sql(shop, "update people.employee_bank_account set approved_by = created_by, created_at = '2026-09-21' "
              "where employee_id = :e", e=shop["ben"]["id"])
    result = run_check(shop, "people.pay_self_approved")
    assert result.created == 2
    items = findings(client, shop, "people.pay_self_approved")
    terms = next(f for f in items if "Basic pay" in f["summary"])
    bank = next(f for f in items if "payment details" in f["summary"])
    assert f"Basic pay of {shop['currency']} 100,000.00 for Cara Wanjiru was proposed and approved by the same person, hr" \
        in terms["summary"]
    assert terms["severity"] == "high" and Dec(terms["amount"]) == 100000 and terms["branch_id"] == str(shop["juja"])
    assert "Ben Kamau were proposed and approved by the same person, hr, on 2026-09-21" in bank["summary"]
    assert bank["branch_id"] == str(shop["branch_id"])
    assert direct(shop, PayApprovedBySameUser(), lookback_days=10) == []          # both older than ten days


# --------------------------------------------------------------------------- pay jumps
def test_a_pay_jump_with_no_recorded_reason_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    # nothing yet: Ann's rise is recorded as new terms, Dan is new, the others are the same as August
    assert run_check(shop, "people.pay_jump_unexplained").created == 0
    sql(shop, "update people.payslip set gross_pay = 30000 where run_id = :r and employee_id = :e",
        r=shop["sept"], e=shop["ben"]["id"])                                    # Ben: 20000 -> 30000, nothing recorded
    sql(shop, "update people.payslip set gross_pay = 60000, detail = detail || '{\"unpaid_leave_days\": \"12\"}'::jsonb "
              "where run_id = :r and employee_id = :e", r=shop["sept"], e=shop["cara"]["id"])   # -40%, but unpaid leave
    result = run_check(shop, "people.pay_jump_unexplained")
    assert result.created == 1
    [f] = findings(client, shop, "people.pay_jump_unexplained")
    cur = shop["currency"]
    assert f["summary"] == (f"Gross pay for Ben Kamau was {cur} 30,000.00 for 2026-09-01 to 2026-09-30, 50.0% up on "
                            f"{cur} 20,000.00 last time, and no pay change is recorded.")
    assert f["severity"] == "medium" and Dec(f["amount"]) == 10000 and Dec(f["value"]) == 30000
    assert Dec(f["expected_value"]) == 20000 and f["branch_id"] == str(shop["branch_id"])
    assert {r["type"] for r in detail(client, shop, f)["records"]} == {"people.payslip", "people.payroll_run",
                                                                       "people.employee"}
    assert direct(shop, PayJumpWithoutChange(), percent="60.0") == []                # 50% is within a 60% limit
    assert len(direct(shop, PayJumpWithoutChange(), percent="10.0")) == 1
    # a recorded pay item explains it: Ben gets an allowance, and the flag no longer applies
    component = client.post(f"{PEOPLE}/pay-components", headers=shop["hr"], json={
        "company_id": shop["company"], "code": "HOUSE", "name": "House allowance", "kind": "earning"}).json()["id"]
    assert client.post(f"{PEOPLE}/employees/{shop['ben']['id']}/pay-items", headers=shop["hr"], json={
        "component_id": component, "amount": "10000", "valid_from": "2026-09-01"}).status_code == 201
    assert direct(shop, PayJumpWithoutChange()) == []


# --------------------------------------------------------------------------- leave waiting
def add_leave(shop, employee, created: str, status: str = "pending") -> str:  # type: ignore[no-untyped-def]
    rows = sql(shop, "insert into people.leave_request (tenant_id, employee_id, leave_type_id, start_date, end_date, days, "
                     "status, created_at) values (:t, :e, :l, '2026-10-20', '2026-10-22', 3, :s, cast(:c as timestamptz)) "
                     "returning id", t=str(shop["tenant_id"]), e=employee["id"], l=shop["annual"], s=status, c=created)
    return str(rows[0][0])


def test_leave_waiting_too_long_is_flagged_and_closes_when_decided(client, shop) -> None:  # type: ignore[no-untyped-def]
    ann_leave = add_leave(shop, shop["ann"], "2026-10-01 10:00+00")             # 13 days
    shop["ben_leave"] = add_leave(shop, shop["ben"], "2026-10-12 10:00+00")     # 2 days: not long
    add_leave(shop, shop["cara"], "2026-10-01 10:00+00", "approved")            # decided
    assert run_check(shop, "people.leave_waiting").created == 1
    [f] = findings(client, shop, "people.leave_waiting")
    assert f["summary"] == ("Ann Otieno asked for 3.00 days of Annual leave (2026-10-20 to 2026-10-22) 13 days ago "
                            "and nobody has decided.")
    assert f["severity"] == "low" and f["branch_id"] == str(shop["branch_id"]) and Dec(f["value"]) == 13
    assert [r["id"] for r in detail(client, shop, f)["records"]] == [ann_leave]
    assert len(direct(shop, LeaveWaiting(), days=1)) == 2                       # tuned: Ben's two days now count
    assert direct(shop, LeaveWaiting(), days=20) == []
    sql(shop, "update people.leave_request set status = 'approved' where id = :i", i=ann_leave)
    closed = run_check(shop, "people.leave_waiting")
    assert closed.resolved == 1
    assert findings(client, shop, "people.leave_waiting") == []
    assert [x["id"] for x in findings(client, shop, "people.leave_waiting", "resolved")] == [f["id"]]


# --------------------------------------------------------------------------- runs left behind
def test_a_run_left_unapproved_or_unpaid_after_its_pay_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    # June: approved but never paid (pay date 106 days ago). July: calculated, never approved (75 days ago).
    # Each is Ann 50000 + Ben 20000 + Cara 100000 + Eve 40000 = 210000 (no attendance in those months).
    shop["june"] = finish_run(client, shop, period("2026-06-01", "2026-06-30", "2026-06-30"), pay=False)
    made = client.post(RUNS, headers=shop["finance"], json={
        "company_id": shop["company"], **period("2026-07-01", "2026-07-31", "2026-07-31")})
    shop["july"] = made.json()["id"]
    assert client.post(f"{RUNS}/{shop['july']}/calculate", headers=shop["finance"]).status_code == 200
    # the Sept payslips were changed by hand earlier; the earlier runs are not what is being checked here
    assert run_check(shop, "people.payroll_overdue").created == 2
    items = findings(client, shop, "people.payroll_overdue")
    june = next(f for f in items if f["period_start"] == "2026-06-01")
    july = next(f for f in items if f["period_start"] == "2026-07-01")
    cur = shop["currency"]
    assert june["severity"] == "high" and "still approved but not paid, 106 days late" in june["summary"]
    assert f"Net pay of {cur} 210,000.00 is waiting" in june["summary"] and Dec(june["amount"]) == 210000
    assert july["severity"] == "medium" and "not yet approved (it is calculated), 75 days late" in july["summary"]
    assert june["branch_id"] is None and Dec(july["value"]) == 75 and Dec(july["expected_value"]) == 3
    # tuned: a 100 day grace leaves only June
    only = direct(shop, PayrollOverdue(), days=100)
    assert [c.period_start for c in only] == [date(2026, 6, 1)]
    assert direct(shop, PayrollOverdue(), days=200) == []
    # paying June closes its finding; Sept and August (paid on time) never appeared
    assert client.post(f"{RUNS}/{shop['june']}/pay", headers=shop["finance"], json={}).status_code == 200
    again = run_check(shop, "people.payroll_overdue")
    assert again.resolved == 1 and again.updated == 1
    assert [f["period_start"] for f in findings(client, shop, "people.payroll_overdue")] == ["2026-07-01"]


# --------------------------------------------------------------------------- Command Center figures
def test_people_figures_for_the_command_center(client, shop) -> None:  # type: ignore[no-untyped-def]
    hq, juja = str(shop["branch_id"]), str(shop["juja"])
    new_employee(client, shop, "Gus Nobranch", hire_date="2026-10-01")             # no branch: company-wide only
    fay = new_employee(client, shop, "Fay Leaver", branch_id=hq, hire_date="2025-01-06")
    left = client.post(f"{PEOPLE}/employees/{fay['id']}/terminate", headers=shop["hr"],
                       json={"termination_date": "2026-09-30"})
    assert left.status_code == 200, left.text
    add_leave(shop, shop["eve"], "2026-10-13 10:00+00")                                # Juja: pending; Ben (HQ) pending too
    insert_attendance(shop, shop["eve"], date(2026, 10, 14), "12", "4")                # Juja overtime today
    insert_attendance(shop, shop["eve"], date(2026, 9, 30), "14", "6")                 # last month: not counted
    assert client.post(RUNS, headers=shop["finance"], json={
        "company_id": shop["company"], **period("2026-11-01", "2026-11-30", "2026-11-30")}).status_code == 201   # draft
    dec = client.post(RUNS, headers=shop["finance"], json={
        "company_id": shop["company"], **period("2026-12-01", "2026-12-31", "2026-12-31")}).json()["id"]
    assert client.post(f"{RUNS}/{dec}/cancel", headers=shop["finance"]).status_code == 200      # cancelled: not counted
    with system(shop) as s:
        assert pulse.refresh_company(s, shop["company_id"], TODAY) >= 11
    rows = sql(shop, "select metric, branch_id, value from command.pulse_figure where day = :d and metric like 'people.%'",
               d=TODAY)
    got = {(r.metric, str(r.branch_id) if r.branch_id else None): Dec(r.value) for r in rows}

    # headcount: Ann, Ben, Dan at HQ (Fay left on 30 Sep); Cara, Eve at Juja; Gus has no branch
    assert got[("people.headcount", None)] == 6 and got[("people.headcount", hq)] == 3
    assert got[("people.headcount", juja)] == 2
    # leave awaiting: Ben (HQ) and Eve (Juja); Ann's was approved, Cara's was never pending
    assert got[("people.leave_waiting", None)] == 2 and got[("people.leave_waiting", hq)] == 1
    assert got[("people.leave_waiting", juja)] == 1
    # overtime hours in October: Ann 1+1+1 (1-3 Oct) + 1.5 + 8 = 12.5; Ben 5 x 1 + 8 = 13; Eve 4 today
    assert got[("people.overtime_hours_month", hq)] == Dec("25.5") and got[("people.overtime_hours_month", juja)] == 4
    assert got[("people.overtime_hours_month", None)] == Dec("29.5")
    # runs not yet paid: July (calculated) and November (draft); June, August, September are paid, December cancelled
    assert got[("people.payroll_runs_unpaid", None)] == 2
    assert ("people.payroll_runs_unpaid", hq) not in got
    with system(shop) as s:
        pulse.refresh_company(s, shop["company_id"], TODAY)
    assert sql(shop, "select count(*) from command.pulse_figure where day = :d and metric = 'people.headcount'",
               d=TODAY)[0][0] == 3                                                  # replaced, not doubled


def test_figures_reach_the_overview_by_scope(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/command/overview", headers=shop["owner"], params={"day": "2026-10-14"})
    assert r.status_code == 200, r.text
    mine = {f["metric"]: Dec(f["value"]) for f in r.json()["figures"] if f["branch_id"] is None}
    assert mine["people.headcount"] == 6 and mine["people.payroll_runs_unpaid"] == 2
    manager = client.get("/api/v1/command/overview", headers=shop["manager"], params={"day": "2026-10-14"})
    if manager.status_code == 200:                                              # a branch manager sees their branch
        theirs = {f["metric"]: Dec(f["value"]) for f in manager.json()["figures"]
                  if f["metric"].startswith("people.")}
        assert theirs.get("people.headcount", 3) == 3
