"""Shifts, attendance (by hand and from the till) and leave."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.people_helpers import PEOPLE, make_people_shop, new_employee
from tests.stock_helpers import system
from ziira.sdk import Event, publish


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "Time Co")
    users = {u["email"].split("@")[0]: u["id"] for u in client.get("/api/v1/users", headers=s["owner"]).json()}
    hq = str(s["branch_id"])
    s["ann"] = new_employee(client, s, "Ann Cashier", branch_id=hq, user_id=users["cashier"], hire_date="2025-01-06")
    s["ben"] = new_employee(client, s, "Ben Manager", branch_id=hq, user_id=users["manager"], hire_date="2025-01-06")
    s["cara"] = new_employee(client, s, "Cara Juja", branch_id=str(s["juja"]), hire_date="2025-01-06")
    s["annual"] = client.post(f"{PEOPLE}/leave-types", headers=s["hr"], json={
        "company_id": s["company"], "name": "Annual", "days_per_year": "10"}).json()
    s["unpaid"] = client.post(f"{PEOPLE}/leave-types", headers=s["hr"], json={
        "company_id": s["company"], "name": "Unpaid", "is_paid": False}).json()
    return s


# --------------------------------------------------------------------------- shifts and attendance
def test_shifts(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": shop["company"], "name": "Day", "start_time": "08:00", "end_time": "17:00"}
    made = client.post(f"{PEOPLE}/shifts", headers=shop["hr"], json=body)
    assert made.status_code == 201, made.text
    shop["day_shift"] = made.json()["id"]
    assert client.post(f"{PEOPLE}/shifts", headers=shop["hr"], json=body).status_code == 409
    night = client.post(f"{PEOPLE}/shifts", headers=shop["hr"], json={**body, "name": "Night", "start_time": "20:00",
                                                                     "end_time": "06:00"})
    assert night.status_code == 201
    for bad in ({"name": " "}, {"end_time": "08:00"}, {"start_time": "25:00"}, {"branch_id": str(uuid4())}):
        assert client.post(f"{PEOPLE}/shifts", headers=shop["hr"], json={**body, "name": "X", **bad}
                           ).status_code in (404, 422), bad
    branch = client.post(f"{PEOPLE}/shifts", headers=shop["manager"], json={
        **body, "name": "Branch day", "branch_id": str(shop["branch_id"])})
    assert branch.status_code == 201                                                          # a manager at their branch
    assert client.post(f"{PEOPLE}/shifts", headers=shop["manager"], json={**body, "name": "Wide"}).status_code == 403
    assert client.post(f"{PEOPLE}/shifts", headers=shop["cashier"], json=body).status_code == 403
    assert len(client.get(f"{PEOPLE}/shifts", headers=shop["hr"], params={"company_id": shop["company"]}).json()) == 3


def attend(client, shop, who="hr", employee=None, **kw):  # type: ignore[no-untyped-def]
    body = {"employee_id": (employee or shop["ann"])["id"], "work_date": "2026-09-01", **kw}
    return client.post(f"{PEOPLE}/attendance", headers=shop[who], json=body)


def test_attendance_hours_and_overtime(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = attend(client, shop, clock_in="2026-09-01T08:00:00+00:00", clock_out="2026-09-01T19:30:00+00:00",
               shift_id=shop["day_shift"])
    assert r.status_code == 201, r.text
    a = r.json()
    assert Dec(a["hours"]) == Dec("11.5") and Dec(a["overtime_hours"]) == Dec("2.5") and a["source"] == "manual"
    assert attend(client, shop, clock_in="2026-09-01T08:00:00+00:00", clock_out="2026-09-01T09:00:00+00:00",
                  shift_id=shop["day_shift"]).status_code == 409                              # one record a day and shift
    plain = attend(client, shop, work_date="2026-09-02", hours="8")
    assert plain.status_code == 201 and Dec(plain.json()["overtime_hours"]) == 0
    given = attend(client, shop, work_date="2026-09-03", hours="9.5", overtime_hours="1.5")
    assert Dec(given.json()["overtime_hours"]) == Dec("1.5")
    assert attend(client, shop, work_date="2026-09-03", hours="1").status_code == 409         # even without a shift
    fixed = client.patch(f"{PEOPLE}/attendance/{a['id']}", headers=shop["hr"], json={
        "clock_out": "2026-09-01T17:30:00+00:00"})
    assert fixed.status_code == 200 and Dec(fixed.json()["hours"]) == Dec("9.5")
    assert Dec(fixed.json()["overtime_hours"]) == Dec("0.5")                                  # worked out again
    assert client.patch(f"{PEOPLE}/attendance/{a['id']}", headers=shop["hr"], json={"source": "x"}).status_code == 422
    assert client.patch(f"{PEOPLE}/attendance/{uuid4()}", headers=shop["hr"], json={"hours": "1"}).status_code == 404


def test_attendance_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"clock_in": "2026-09-05T10:00:00+00:00", "clock_out": "2026-09-05T09:00:00+00:00"},
                {"clock_in": "2026-09-05T00:00:00+00:00", "clock_out": "2026-09-06T08:00:00+00:00"},
                {"clock_in": "2026-09-05T10:00:00+00:00"}, {"hours": "25"}, {"hours": "-1"},
                {"hours": "4", "overtime_hours": "5"}, {"work_date": "2024-01-01", "hours": "8"},
                {"work_date": "2999-01-01", "hours": "8"}, {"shift_id": str(uuid4()), "hours": "8"},
                {"work_date": "soon", "hours": "8"}):
        assert attend(client, shop, **{"work_date": "2026-09-05", **bad}).status_code == 422, bad
    assert attend(client, shop, employee={"id": str(uuid4())}, hours="8").status_code == 404


def test_attendance_scope_and_summary(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert attend(client, shop, who="manager", employee=shop["ben"], work_date="2026-09-10", hours="8"
                  ).status_code == 201                                                       # own branch
    assert attend(client, shop, who="manager", employee=shop["cara"], work_date="2026-09-10", hours="8"
                  ).status_code == 404                                                       # another branch: not theirs
    assert attend(client, shop, who="cashier", hours="8", work_date="2026-09-11").status_code == 403
    assert attend(client, shop, employee=shop["cara"], work_date="2026-09-10", hours="8").status_code == 201
    mine = client.get(f"{PEOPLE}/attendance", headers=shop["manager"], params={"limit": 200}).json()
    assert mine and all(x["branch_id"] == str(shop["branch_id"]) for x in mine)
    window = {"company_id": shop["company"], "date_from": "2026-09-01", "date_to": "2026-09-30"}
    rows = client.get(f"{PEOPLE}/attendance/summary", headers=shop["hr"], params=window).json()
    by_name = {r["full_name"]: r for r in rows}
    assert by_name["Ann Cashier"]["days"] == 3 and Dec(by_name["Ann Cashier"]["hours"]) == Dec("9.5") + 8 + Dec("9.5")
    assert Dec(by_name["Ann Cashier"]["overtime_hours"]) == Dec("0.5") + Dec("1.5")
    assert by_name["Cara Juja"]["days"] == 1
    only = client.get(f"{PEOPLE}/attendance/summary", headers=shop["manager"], params=window).json()
    assert {r["full_name"] for r in only} == {"Ann Cashier", "Ben Manager"}
    assert client.get(f"{PEOPLE}/attendance/summary", headers=shop["hr"], params={
        **window, "date_to": "2026-08-01"}).status_code == 422
    filtered = client.get(f"{PEOPLE}/attendance", headers=shop["hr"], params={
        "employee_id": shop["cara"]["id"], "date_from": "2026-09-10", "date_to": "2026-09-10"}).json()
    assert len(filtered) == 1


def till_event(shop, kind, user_id, day, **extra):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        publish(s, Event(kind, "pos.till_session", uuid4(), {
            "company_id": shop["company_id"], "branch_id": shop["branch_id"], "business_date": day,
            "cashier_id": user_id, **extra}))


def test_a_cashier_opening_and_closing_a_till_clocks_in_and_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = date.today().isoformat()
    till_event(shop, "till.opened", shop["ann"]["user_id"], day)
    till_event(shop, "till.opened", shop["ann"]["user_id"], day)                              # a second till: no second record
    till_event(shop, "till.opened", str(uuid4()), day)                                        # not an employee: ignored
    till_event(shop, "till.opened", shop["ann"]["user_id"], "garbage")                        # bad payload: ignored
    rows = client.get(f"{PEOPLE}/attendance", headers=shop["hr"], params={
        "employee_id": shop["ann"]["id"], "date_from": day, "date_to": day}).json()
    assert len(rows) == 1 and rows[0]["source"] == "pos_login" and rows[0]["clock_in"] and rows[0]["clock_out"] is None
    till_event(shop, "till.closed", shop["ann"]["user_id"], day, variance="0")
    row = client.get(f"{PEOPLE}/attendance", headers=shop["hr"], params={
        "employee_id": shop["ann"]["id"], "date_from": day, "date_to": day}).json()[0]
    assert row["clock_out"] and Dec(row["hours"]) < 1
    ben_day = client.get(f"{PEOPLE}/attendance", headers=shop["hr"], params={
        "employee_id": shop["ben"]["id"], "date_from": day, "date_to": day}).json()
    assert ben_day == []


# --------------------------------------------------------------------------- leave
def ask(client, shop, who="cashier", **kw):  # type: ignore[no-untyped-def]
    body = {"leave_type_id": shop["annual"]["id"], "start_date": "2026-11-02", "end_date": "2026-11-06", **kw}
    return client.post(f"{PEOPLE}/leave-requests", headers=shop[who], json=body)


def test_leave_types(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{PEOPLE}/leave-types"
    assert client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "name": "Annual"}
                       ).status_code == 409
    for bad in ({"name": " "}, {"days_per_year": "0"}, {"days_per_year": "400"}):
        assert client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "name": "X", **bad}
                           ).status_code == 422, bad
    assert client.post(path, headers=shop["manager"], json={"company_id": shop["company"], "name": "Y"}
                       ).status_code == 403
    assert {t["name"] for t in client.get(path, headers=shop["cashier"], params={
        "company_id": shop["company"]}).json()} >= {"Annual", "Unpaid"}


def test_an_employee_asks_for_leave_and_a_manager_approves_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = ask(client, shop)                                                                      # Mon 2 - Fri 6 November
    assert r.status_code == 201, r.text
    leave = r.json()
    assert leave["employee_id"] == shop["ann"]["id"] and Dec(leave["days"]) == 5 and leave["status"] == "pending"
    over = ask(client, shop, start_date="2026-11-04", end_date="2026-11-10")
    assert over.status_code == 409 and "overlaps" in over.json()["message"]
    assert client.post(f"{PEOPLE}/leave-requests/{leave['id']}/approve", headers=shop["cashier"], json={}
                       ).status_code == 403                                                   # an employee cannot approve
    ok = client.post(f"{PEOPLE}/leave-requests/{leave['id']}/approve", headers=shop["manager"],
                     json={"note": "Enjoy"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approved_by"]
    assert client.post(f"{PEOPLE}/leave-requests/{leave['id']}/approve", headers=shop["manager"], json={}
                       ).status_code == 409
    assert [x["id"] for x in client.get(f"{PEOPLE}/me/leave-requests", headers=shop["cashier"]).json()] == [leave["id"]]
    assert client.get(f"{PEOPLE}/leave-requests/{leave['id']}", headers=shop["cashier"]).status_code == 200
    balance = client.get(f"{PEOPLE}/employees/{shop['ann']['id']}/leave-balances", headers=shop["cashier"],
                         params={"year": 2026}).json()
    annual = next(b for b in balance if b["leave_type"] == "Annual")
    assert Dec(annual["taken"]) == 5 and Dec(annual["left"]) == 5
    assert next(b for b in balance if b["leave_type"] == "Unpaid")["left"] is None             # unlimited


def test_days_are_working_days_half_days_and_the_business_weekend(client, shop) -> None:  # type: ignore[no-untyped-def]
    span = ask(client, shop, who="hr", employee_id=shop["ben"]["id"], start_date="2026-12-04",
               end_date="2026-12-07")                                                         # Fri, Sat, Sun, Mon
    assert span.status_code == 201 and Dec(span.json()["days"]) == 2
    half = ask(client, shop, who="hr", employee_id=shop["ben"]["id"], start_date="2026-12-14", end_date="2026-12-14",
               days="0.5")
    assert half.status_code == 201 and Dec(half.json()["days"]) == Dec("0.5")
    for bad in ({"days": "6"}, {"days": "0.3"}, {"days": "0"}, {"start_date": "2026-12-12", "end_date": "2026-12-13"},
                {"start_date": "2026-12-20", "end_date": "2026-12-19"}, {"start_date": "2024-01-01",
                                                                     "end_date": "2024-01-02"}):
        dates = {"start_date": "2026-12-21", "end_date": "2026-12-25", **bad}
        assert ask(client, shop, who="hr", employee_id=shop["ben"]["id"], **dates).status_code == 422, bad
    set_weekend = client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                               json={"weekend_days": ["fri", "sat"]})
    assert set_weekend.status_code == 200 and set_weekend.json()["weekend_days"] == ["fri", "sat"]
    gulf = ask(client, shop, who="hr", employee_id=shop["cara"]["id"], start_date="2027-01-03", end_date="2027-01-09")
    assert gulf.status_code == 201 and Dec(gulf.json()["days"]) == 5                          # Sun-Thu are working days
    client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                 json={"weekend_days": ["sat", "sun"]})
    for bad_days in (["mon", "tue", "wed", "thu"], ["noday"]):
        assert client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                            json={"weekend_days": bad_days}).status_code == 422


def test_the_yearly_entitlement_is_enforced_and_leave_can_be_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    big = ask(client, shop, who="hr", employee_id=shop["ann"]["id"], start_date="2026-11-23",
              end_date="2026-11-30")                                                          # 6 days; 5 already taken
    assert big.status_code == 201
    refused = client.post(f"{PEOPLE}/leave-requests/{big.json()['id']}/approve", headers=shop["manager"], json={})
    assert refused.status_code == 422 and "10.00 days a year" in refused.json()["message"]
    no = client.post(f"{PEOPLE}/leave-requests/{big.json()['id']}/reject", headers=shop["manager"],
                     json={"note": "Busy season"})
    assert no.status_code == 200 and no.json()["status"] == "rejected" and no.json()["decided_note"] == "Busy season"


def test_nobody_approves_their_own_leave_or_leave_in_another_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    mine = ask(client, shop, who="manager", start_date="2026-11-09", end_date="2026-11-09")
    assert mine.status_code == 201 and mine.json()["employee_id"] == shop["ben"]["id"]
    assert client.post(f"{PEOPLE}/leave-requests/{mine.json()['id']}/approve", headers=shop["manager"], json={}
                       ).status_code == 403
    assert client.post(f"{PEOPLE}/leave-requests/{mine.json()['id']}/approve", headers=shop["hr"], json={}
                       ).status_code == 200                                                   # someone else may
    cara = ask(client, shop, who="hr", employee_id=shop["cara"]["id"], start_date="2026-11-09", end_date="2026-11-09")
    path = f"{PEOPLE}/leave-requests/{cara.json()['id']}"
    assert client.post(f"{path}/approve", headers=shop["manager"], json={}).status_code == 404   # not their branch
    assert client.get(path, headers=shop["manager"]).status_code == 404
    assert ask(client, shop, who="cashier", employee_id=shop["ben"]["id"], start_date="2026-12-01",
               end_date="2026-12-01").status_code == 404                                      # not for someone else
    assert ask(client, shop, who="finance").status_code == 422                                # no employee record
    assert ask(client, shop, employee_id=str(uuid4())).status_code == 404
    assert ask(client, shop, leave_type_id=str(uuid4())).status_code == 422
    assert client.get(f"{PEOPLE}/leave-requests", headers=shop["cashier"]).status_code == 403


def test_cancelling_leave_and_the_unpaid_days_payroll_uses(client, shop) -> None:  # type: ignore[no-untyped-def]
    future = ask(client, shop, start_date="2027-03-01", end_date="2027-03-02").json()
    assert client.post(f"{PEOPLE}/leave-requests/{future['id']}/cancel", headers=shop["cashier"]).json()[
        "status"] == "cancelled"
    assert client.post(f"{PEOPLE}/leave-requests/{future['id']}/cancel", headers=shop["cashier"]).status_code == 409
    past = ask(client, shop, who="hr", employee_id=shop["ann"]["id"], leave_type_id=shop["unpaid"]["id"],
               start_date="2026-08-26", end_date="2026-09-03").json()                         # Wed 26 Aug - Thu 3 Sep
    assert Dec(past["days"]) == 7
    client.post(f"{PEOPLE}/leave-requests/{past['id']}/approve", headers=shop["hr"], json={})
    assert client.post(f"{PEOPLE}/leave-requests/{past['id']}/cancel", headers=shop["cashier"]).status_code == 409
    from ziira.modules.people.repository import people_repo
    from ziira.modules.people.services import leave as leave_service

    with system(shop) as s:
        ann = people_repo.get_employee(s, shop["ann"]["id"])
        assert leave_service.unpaid_days(s, ann, date(2026, 9, 1), date(2026, 9, 30)) == Dec("3.00")   # 1, 2, 3 Sept
        assert leave_service.unpaid_days(s, ann, date(2026, 8, 1), date(2026, 8, 31)) == Dec("4.00")   # 26, 27, 28, 31
        assert leave_service.unpaid_days(s, ann, date(2026, 10, 1), date(2026, 10, 31)) == Dec(0)
