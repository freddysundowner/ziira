"""Intelligence's own checks, over what the platform records: approvals, wide access, odd hours, the exceptions inbox."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.modules.intel.services import engine

INTEL = "/api/v1/intel"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Controls Co")
    registry.enable(s["tenant_id"], "intel")
    return s


def run(shop, code: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=date.today(), only={code})


def findings(client, shop, code: str, status: str | None = None):  # type: ignore[no-untyped-def]
    params = {"check_code": code, **({"status": status} if status else {})}
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def user_id(client, shop, name: str) -> str:  # type: ignore[no-untyped-def]
    return next(u["id"] for u in client.get("/api/v1/users", headers=shop["owner"]).json() if u["full_name"] == name)


def test_an_approval_decided_by_its_requester_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    manager, boss = user_id(client, shop, "manager"), user_id(client, shop, "boss")
    role = shop["roles"]["Branch Manager"]
    with system(shop) as s:
        rule = uuid4()
        s.execute(text("insert into kernel.approval_rule (id, tenant_id, company_id, doc_type, approver_role_id, "
                       "forbid_creator, min_amount) values (:i, :t, :c, 'stock_adjustment', :r, false, 500)"),
                  {"i": str(rule), "t": str(shop["tenant_id"]), "c": str(shop["company_id"]), "r": role})
        for requested, decided in ((manager, manager), (manager, boss)):
            s.execute(text("insert into kernel.approval_request (tenant_id, rule_id, doc_type, doc_id, status, "
                           "requested_by, decided_by, decided_at) values (:t, :r, 'stock_adjustment', :d, 'approved', "
                           ":rb, :db, now())"),
                      {"t": str(shop["tenant_id"]), "r": str(rule), "d": str(uuid4()), "rb": requested, "db": decided})
    assert run(shop, "controls.approval_by_requester").created == 1                # only the self-approved one
    f = findings(client, shop, "controls.approval_by_requester")[0]
    assert f["severity"] == "high" and "manager approved their own stock adjustment request" in f["summary"]
    assert float(f["amount"]) == 500
    assert run(shop, "controls.approval_by_requester").created == 0                # seen again: the same finding


def test_wide_access_is_flagged_for_a_recent_grant(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert run(shop, "controls.new_wide_access").created >= 1
    summaries = [f["summary"] for f in findings(client, shop, "controls.new_wide_access")]
    assert any(s.startswith("boss was given the role Branch Manager over the whole company") for s in summaries)
    assert not any(s.startswith("manager was given") for s in summaries)           # a branch-level role is not wide


def audit_rows(shop, user: str, hour: int, count: int, day: date) -> None:  # type: ignore[no-untyped-def]
    when = datetime(day.year, day.month, day.day, hour, 30, tzinfo=UTC)
    with system(shop) as s:
        for _ in range(count):
            s.execute(text("insert into kernel.audit_log (tenant_id, occurred_at, user_id, channel, action, entity_type, "
                           "hash) values (:t, :w, :u, 'web', 'post', 'stock.adjustment', 'x')"),
                      {"t": str(shop["tenant_id"]), "w": when, "u": user})


def test_a_burst_of_activity_at_night_is_flagged_but_daytime_work_is_not(client, shop) -> None:  # type: ignore[no-untyped-def]
    yesterday = date.today() - timedelta(days=1)
    keeper, manager = user_id(client, shop, "storekeeper"), user_id(client, shop, "manager")
    audit_rows(shop, keeper, 2, 12, yesterday)                                      # 02:30: outside 06:00 to 22:00
    audit_rows(shop, manager, 2, 9, yesterday)                                      # a few: below the limit
    audit_rows(shop, manager, 11, 40, yesterday)                                    # lots, but at 11:30
    assert run(shop, "controls.after_hours_activity").created == 1
    f = findings(client, shop, "controls.after_hours_activity")[0]
    assert f["severity"] == "low" and float(f["value"]) == 12
    assert f["summary"].startswith("storekeeper made 12 changes") and "outside 06:00 to 22:00" in f["summary"]
    # tuned limits change the outcome: a business that works nights
    client.patch(f"{INTEL}/checks/controls.after_hours_activity", headers=shop["owner"], json={"params": {"start_hour": 0}})
    assert run(shop, "controls.after_hours_activity").created == 0
    client.patch(f"{INTEL}/checks/controls.after_hours_activity", headers=shop["owner"], json={"params": {"start_hour": 6}})


def test_the_time_zone_decides_what_is_after_hours(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = date.today() - timedelta(days=2)
    cashier = user_id(client, shop, "cashier")
    audit_rows(shop, cashier, 23, 15, day)                                         # 23:30 UTC = 08:30 next morning in Tokyo
    company = str(shop["company_id"])
    client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"], json={"timezone": "Asia/Tokyo"})
    run(shop, "controls.after_hours_activity")
    names = [f["summary"].split(" made")[0] for f in findings(client, shop, "controls.after_hours_activity")]
    assert "cashier" not in names
    client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"], json={"timezone": "UTC"})
    run(shop, "controls.after_hours_activity")
    names = [f["summary"].split(" made")[0] for f in findings(client, shop, "controls.after_hours_activity")]
    assert "cashier" in names


def raise_items(shop, count: int, days_old: int, severity: str = "medium") -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        for i in range(count):
            s.execute(text("insert into kernel.exception_item (tenant_id, unit_name, kind, severity, company_id, message, "
                           "dedupe_key, amount, created_at) values (:t, 'x', 'k', :sv, :c, 'm', :k, 100, "
                           "now() - make_interval(days => :d))"),
                      {"t": str(shop["tenant_id"]), "c": str(shop["company_id"]), "sv": severity, "d": days_old,
                       "k": f"backlog-{days_old}-{i}-{uuid4()}"})


def test_exceptions_nobody_reviewed_are_flagged_and_clear_when_worked(client, shop) -> None:  # type: ignore[no-untyped-def]
    raise_items(shop, 2, 10)
    assert run(shop, "controls.exceptions_backlog").created == 0                   # below the limit of 3
    raise_items(shop, 2, 10, severity="high")
    raise_items(shop, 3, 1)                                                        # recent ones do not count
    assert run(shop, "controls.exceptions_backlog").created == 1
    f = findings(client, shop, "controls.exceptions_backlog")[0]
    assert f["severity"] == "high" and f["summary"].startswith("4 exceptions have waited more than 7 days")
    assert "2 of them serious" in f["summary"] and float(f["amount"]) == 400
    with system(shop) as s:
        s.execute(text("update kernel.exception_item set status = 'resolved' where status = 'open'"))
    assert run(shop, "controls.exceptions_backlog").resolved == 1                  # a state: closes by itself
    assert findings(client, shop, "controls.exceptions_backlog", status="resolved")
