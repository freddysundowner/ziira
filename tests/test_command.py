"""Command Center: figures from the units, what each person may see, briefs, and when they are sent."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import extensions
from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, PulseSource
from ziira.modules.command.services import briefs, pulse

CMD = "/api/v1/command"
PLAN: dict[str, Any] = {"fail": False, "branches": {}}


class FakeSource(PulseSource):
    """Sales of 1000 a day for the company, split between two branches; more the day before."""

    code = "test.sales"

    def figures(self, session, company_id: UUID, day: date) -> list[Figure]:  # type: ignore[no-untyped-def]
        if PLAN["fail"]:
            raise RuntimeError("source down")
        base = 1000 + day.day               # a different number each day, so "against yesterday" can be checked
        hq, juja = PLAN["branches"]["hq"], PLAN["branches"]["juja"]
        return [Figure("sales.total", "Sales", "money", Decimal(base), higher_is_better=True),
                Figure("sales.total", "Sales", "money", Decimal(base - 400), branch_id=hq, higher_is_better=True),
                Figure("sales.total", "Sales", "money", Decimal(400), branch_id=juja, higher_is_better=True),
                Figure("sales.voids", "Voids", "count", Decimal(2), higher_is_better=False)]


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401 - defines the extension point

    extensions._add_implementation(extensions._points[COMMAND_PULSE_SOURCE], "command", FakeSource)
    s = make_stock_shop(client, registry, "Command Co")
    # these tests are written in UTC hours: say so (test tenants are otherwise created in LOCALE["timezone"])
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "messaging")
    registry.enable(s["tenant_id"], "command")
    PLAN["branches"] = {"hq": s["branch_id"], "juja": s["juja"]}
    yield s
    extensions._points[COMMAND_PULSE_SOURCE].implementations.remove(("command", FakeSource))


@pytest.fixture(autouse=True)
def calm() -> None:
    PLAN["fail"] = False


def collect(shop, day: date) -> int:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return pulse.refresh_company(s, shop["company_id"], day)


def add_finding(shop, summary: str, severity: str, branch: UUID | None, amount: str = "100") -> UUID:  # type: ignore[no-untyped-def]
    fid = uuid4()
    with system(shop) as s:
        s.execute(text(
            "insert into intel.finding (id, tenant_id, check_code, fingerprint, area, severity, company_id, branch_id, "
            "summary, recommended_action, amount, evidence) values (:i, :t, 'test.x', :fp, 'controls', :sv, :c, :b, "
            ":su, 'Look into it', :am, '{}')"),
            {"i": str(fid), "t": str(shop["tenant_id"]), "fp": str(fid), "sv": severity, "c": str(shop["company_id"]),
             "b": str(branch) if (branch := branch) else None, "su": summary, "am": amount})
    return fid


# --------------------------------------------------------------------------- figures
def test_units_supply_figures_and_a_failing_source_is_reported_not_fatal(shop) -> None:  # type: ignore[no-untyped-def]
    first = collect(shop, date(2026, 10, 14))
    assert first >= 4                                                   # ours, and any the enabled units add
    assert collect(shop, date(2026, 10, 14)) == first                   # again: replaced, not doubled
    PLAN["fail"] = True
    collect(shop, date(2026, 10, 13))                                   # our source fails; the others still report
    with system(shop) as s:
        flagged = s.execute(text("select message from kernel.exception_item where kind = 'pulse_failed'")).first()
        ours = s.execute(text("select count(*) from command.pulse_figure where day = '2026-10-14' "
                              "and metric like 'sales.%'")).scalar_one()
        failed_day = s.execute(text("select count(*) from command.pulse_figure where day = '2026-10-13' "
                                    "and metric like 'sales.%'")).scalar_one()
    assert flagged is not None and "test.sales" in flagged.message and ours == 4 and failed_day == 0


def test_each_person_sees_the_figures_of_their_scope_against_the_day_before(client, shop) -> None:  # type: ignore[no-untyped-def]
    collect(shop, date(2026, 10, 14))
    collect(shop, date(2026, 10, 13))
    r = client.get(f"{CMD}/overview", headers=shop["owner"], params={"day": "2026-10-14"})
    assert r.status_code == 200, r.text
    body = r.json()
    company = next(f for f in body["figures"] if f["metric"] == "sales.total" and f["branch_id"] is None)
    assert (Decimal(company["value"]), Decimal(company["previous"])) == (1014, 1013)
    assert body["currency"] and body["company_name"]
    ours = [f for f in body["figures"] if f["metric"].startswith("sales.")]
    assert {f["branch_name"] for f in ours if f["branch_id"]} == {"Head office", "Juja"}
    # a branch manager sees their own branch's figures only, not the company's or the other branch's
    shown = client.get(f"{CMD}/overview", headers=shop["manager"], params={"day": "2026-10-14"}).json()["figures"]
    mine = [f for f in shown if f["metric"].startswith("sales.")]
    assert [f["branch_name"] for f in mine] == ["Head office"] and Decimal(mine[0]["value"]) == 614
    assert all(f["branch_id"] is not None for f in shown)               # nothing company-wide leaks to a branch role
    assert client.get(f"{CMD}/overview", headers=shop["juja_keeper"]).status_code == 403   # no command.view


def test_the_overview_lists_the_findings_that_need_the_person(client, shop) -> None:  # type: ignore[no-untyped-def]
    add_finding(shop, "Overview: HQ void spike", "high", shop["branch_id"], "5000")
    add_finding(shop, "Overview: Juja stock gap", "medium", shop["juja"], "100")
    add_finding(shop, "Overview: company-wide", "low", None)
    owner = client.get(f"{CMD}/overview", headers=shop["owner"], params={"day": "2026-10-14"}).json()
    assert owner["open_findings"] >= 3 and owner["findings_by_severity"].get("high", 0) >= 1
    assert owner["top_findings"][0]["severity"] in ("high", "critical")           # most serious first
    manager = client.get(f"{CMD}/overview", headers=shop["manager"], params={"day": "2026-10-14"}).json()
    summaries = {f["summary"] for f in manager["top_findings"]}
    assert "Overview: HQ void spike" in summaries
    assert "Overview: Juja stock gap" not in summaries and "Overview: company-wide" not in summaries


def test_manual_collection_needs_the_manage_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.post(f"{CMD}/pulse/refresh", headers=shop["manager"]).status_code == 403
    assert client.post(f"{CMD}/pulse/refresh", headers=shop["owner"]).status_code == 204


# --------------------------------------------------------------------------- schedules and briefs
def test_a_person_chooses_when_and_how_they_get_their_brief(client, shop) -> None:  # type: ignore[no-untyped-def]
    mine = f"{CMD}/schedules/mine"
    assert client.put(f"{mine}/weekly", headers=shop["owner"], json={"send_time": "08:00", "channel": "in_app"}).status_code == 422
    assert client.put(f"{mine}/daily", headers=shop["owner"], json={"send_time": "08:00", "channel": "sms"}).status_code == 422  # no phone
    r = client.put(f"{mine}/daily", headers=shop["owner"], json={"send_time": "07:30", "channel": "email"})
    assert r.status_code == 200 and r.json()["channel"] == "email" and r.json()["send_time"] == "07:30:00"
    again = client.put(f"{mine}/daily", headers=shop["owner"], json={"send_time": "06:00", "channel": "in_app"})
    assert again.json()["id"] == r.json()["id"] and again.json()["send_time"] == "06:00:00"   # updated, not duplicated
    assert client.put(f"{mine}/weekly", headers=shop["owner"],
                      json={"send_time": "08:00", "weekday": 3, "channel": "in_app"}).status_code == 200
    assert {s["kind"] for s in client.get(mine, headers=shop["owner"]).json()} == {"daily", "weekly"}
    assert client.get(mine, headers=shop["manager"]).json() == []                      # nobody sees another's
    everyone = client.get(f"{CMD}/schedules", headers=shop["owner"])
    assert everyone.status_code == 200 and len(everyone.json()) >= 2
    assert client.get(f"{CMD}/schedules", headers=shop["manager"]).status_code == 403
    assert client.delete(f"{mine}/weekly", headers=shop["owner"]).status_code == 204
    assert {s["kind"] for s in client.get(mine, headers=shop["owner"]).json()} == {"daily"}


def sent_briefs(client, headers) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{CMD}/briefs", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_due_briefs_are_sent_once_a_day_at_the_right_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.put(f"{CMD}/schedules/mine/daily", headers=shop["manager"], json={"send_time": "07:30", "channel": "email"})
    before = len(sent_briefs(client, shop["manager"]))
    wednesday = datetime(2026, 3, 4, 5, 0, tzinfo=UTC)
    with system(shop) as s:
        assert briefs.send_due(s, now=wednesday) == 0                                  # 05:00: before every schedule
    with system(shop) as s:
        collect(shop, date(2026, 10, 13))
        sent = briefs.send_due(s, now=wednesday.replace(hour=8))
    assert sent >= 1
    mine = sent_briefs(client, shop["manager"])
    assert len(mine) == before + 1 and mine[0]["kind"] == "daily" and mine[0]["delivered_via"] == "email"
    with system(shop) as s:
        assert briefs.send_due(s, now=wednesday.replace(hour=9)) == 0                  # already sent today
    with system(shop) as s:
        queued = s.execute(text("select subject, body, recipient from kernel.notification where ref_id = :r"),
                           {"r": mine[0]["id"]}).all()
    assert len(queued) == 1 and queued[0].recipient == f"manager@{shop['code']}.test"
    assert "daily summary" in queued[0].subject
    detail = client.get(f"{CMD}/briefs/{mine[0]['id']}", headers=shop["manager"]).json()
    assert detail["read_at"] is None or detail["body"]                                  # opening marks it read
    assert "Head office" not in detail["body"] or "Juja" not in detail["body"]          # a branch manager's brief: their branch
    assert "Overview: Juja stock gap" not in detail["body"]                             # ...and their findings only
    assert client.get(f"{CMD}/briefs/{mine[0]['id']}", headers=shop["owner"]).status_code == 404


def test_a_weekly_brief_comes_on_its_weekday_in_the_companys_time_zone(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.put(f"{CMD}/schedules/mine/weekly", headers=shop["boss"], json={"send_time": "07:00", "weekday": 1, "channel": "in_app"})
    company = str(shop["company_id"])
    assert client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"],
                        json={"timezone": "Pacific/Auckland"}).status_code == 200
    # Sunday 2026-10-18 20:30 UTC is Monday 2026-10-19 09:30 in Auckland (UTC+13): due there, not in UTC
    moment = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)
    with system(shop) as s:
        assert briefs.send_due(s, now=moment) >= 1
    assert any(b["kind"] == "weekly" and b["brief_date"] == "2026-10-19" for b in sent_briefs(client, shop["boss"]))
    client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"], json={"timezone": "UTC"})
    assert client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"],
                        json={"timezone": "Not/AZone"}).status_code == 422


def test_preview_and_send_now(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = client.post(f"{CMD}/briefs/preview", headers=shop["owner"], params={"kind": "daily"})
    assert p.status_code == 200 and "daily summary" in p.json()["subject"] and p.json()["short"]
    first = client.post(f"{CMD}/briefs/send-now", headers=shop["owner"], params={"kind": "daily", "channel": "in_app"})
    assert first.status_code == 200 and first.json()["delivered_via"] == "in_app"
    second = client.post(f"{CMD}/briefs/send-now", headers=shop["owner"], params={"kind": "daily"})
    assert second.status_code == 422                                                     # once per day and kind
    assert client.post(f"{CMD}/briefs/preview", headers=shop["juja_keeper"]).status_code == 403


def test_a_missing_contact_falls_back_to_the_app(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{CMD}/briefs/send-now", headers=shop["owner"], params={"kind": "weekly", "channel": "sms"})
    assert r.status_code == 200 and r.json()["delivered_via"] == "in_app"                # the owner has no phone number


# --------------------------------------------------------------------------- dashboard layout
def test_a_person_arranges_their_dashboard(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{CMD}/dashboard/widgets"
    assert client.get(path, headers=shop["owner"]).json() == []
    layout = [{"widget_code": "sales", "settings": {"range": "week"}}, {"widget_code": "findings"}]
    r = client.put(path, headers=shop["owner"], json=layout)
    assert r.status_code == 200 and [w["position"] for w in r.json()] == [0, 1]
    assert [w["widget_code"] for w in client.get(path, headers=shop["owner"]).json()] == ["sales", "findings"]
    assert client.get(path, headers=shop["manager"]).json() == []                        # each person's own
    assert client.put(path, headers=shop["owner"], json=[{"widget_code": "a"}, {"widget_code": "a"}]).status_code == 422
