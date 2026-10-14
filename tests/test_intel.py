"""Intelligence: the checks engine, the life of a finding, who sees what, alerts, asking people, and the checks' settings.

The checks themselves belong to the units that own the data; here two small fake checks stand in so the engine is
tested on its own.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import extensions
from ziira.modules.intel.public import (
    INTEL_BASELINE_METRIC,
    INTEL_CHECK,
    BaselineMetric,
    Candidate,
    CheckContext,
    IntelCheck,
    Record,
    Sample,
)
from ziira.modules.intel.services import alerts, baselines, engine

INTEL = "/api/v1/intel"
PLAN: dict[str, Any] = {"candidates": [], "oneoff": [], "raise": False, "params": None}


class FakeCheck(IntelCheck):
    """Reports whatever the test planned. A state: when it stops reporting a problem, the problem is closed."""

    code = "test.state"
    title = "A state check"
    area = "stock"
    description = "For tests"
    default_severity = "medium"
    params = {"limit": 5, "named": "x"}

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        if PLAN["raise"]:
            raise RuntimeError("boom")
        PLAN["params"] = ctx.params
        return [c(ctx.company_id) for c in PLAN["candidates"]]


class FakeOneOff(IntelCheck):
    """An event: a finding stays until a person deals with it, even when the check stops reporting it."""

    code = "test.oneoff"
    title = "An event check"
    area = "controls"
    params: dict[str, Any] = {}
    auto_resolves = False

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        return [c(ctx.company_id) for c in PLAN["oneoff"]]


class FakeMetric(BaselineMetric):
    code = "test.metric"
    title = "A metric"

    def samples(self, session, company_id, date_from, date_to) -> list[Sample]:  # type: ignore[no-untyped-def]
        return [Sample("a", Decimal(v)) for v in (2, 4, 4, 4, 5, 5, 7, 9)] + [Sample("b", Decimal(10))]


def cand(fp: str, severity: str = "medium", branch: UUID | None = None, amount: str | None = "100") -> Any:
    def make(company_id: UUID) -> Candidate:
        return Candidate(fingerprint=fp, severity=severity, summary=f"Problem {fp}", recommended_action="Look into it",
                         company_id=company_id, branch_id=branch, amount=Decimal(amount) if amount else None,
                         period_start=date(2026, 10, 1), records=(Record("test.thing", uuid4(), f"Thing {fp}"),),
                         figures={"count": "3"})
    return make


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401 - defines the extension points

    points = extensions._points
    for point, impls in ((INTEL_CHECK, (FakeCheck, FakeOneOff)), (INTEL_BASELINE_METRIC, (FakeMetric,))):
        for impl in impls:
            extensions._add_implementation(points[point], "intel", impl)
    s = make_stock_shop(client, registry, "Intel Co")
    registry.enable(s["tenant_id"], "intel")
    yield s
    for point, impls in ((INTEL_CHECK, (FakeCheck, FakeOneOff)), (INTEL_BASELINE_METRIC, (FakeMetric,))):
        for impl in impls:
            points[point].implementations.remove(("intel", impl))


@pytest.fixture(autouse=True)
def reset_plan() -> None:
    PLAN.update(candidates=[], oneoff=[], raise_=False, params=None)
    PLAN["raise"] = False


FAKES = {"test.state", "test.oneoff"}


def run(shop, **kw):  # type: ignore[no-untyped-def]
    """Run the two fake checks only (Intelligence's own checks have their own tests)."""
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only=kw.pop("only", FAKES), **kw)


def findings(client, headers, **params):  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def by_summary(items: list[dict[str, Any]], fp: str) -> dict[str, Any]:
    return next(f for f in items if f["summary"] == f"Problem {fp}")


# --------------------------------------------------------------------------- the engine
def test_a_problem_found_is_a_finding_and_found_again_is_the_same_finding(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("e1")]
    first = run(shop)
    assert (first.created, first.updated) == (1, 0)
    second = run(shop)
    assert (second.created, second.updated) == (0, 1)
    items = [f for f in findings(client, shop["owner"], check_code="test.state") if f["summary"] == "Problem e1"]
    assert len(items) == 1
    detail = client.get(f"{INTEL}/findings/{items[0]['id']}", headers=shop["owner"]).json()
    assert detail["status"] == "new" and detail["severity"] == "medium" and detail["area"] == "stock"
    assert detail["records"][0]["label"] == "Thing e1" and detail["figures"] == {"count": "3"}
    assert [e["event"] for e in detail["events"]] == ["detected"]


def test_a_state_that_clears_closes_its_finding_and_a_return_reopens_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("e2")]
    run(shop)
    PLAN["candidates"] = []
    assert run(shop).resolved >= 1
    f = by_summary(findings(client, shop["owner"], status="resolved", check_code="test.state"), "e2")
    assert f["status"] == "resolved"
    PLAN["candidates"] = [cand("e2")]
    assert run(shop).reopened == 1
    f = by_summary(findings(client, shop["owner"], check_code="test.state"), "e2")
    assert f["status"] == "new"
    events = [e["event"] for e in client.get(f"{INTEL}/findings/{f['id']}", headers=shop["owner"]).json()["events"]]
    assert events == ["detected", "auto_resolved", "reopened"]


def test_an_event_finding_stays_until_a_person_deals_with_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["oneoff"] = [cand("o1")]
    run(shop)
    PLAN["oneoff"] = []
    run(shop)
    f = by_summary(findings(client, shop["owner"], check_code="test.oneoff"), "o1")
    assert f["status"] == "new"


def test_a_dismissed_problem_is_not_raised_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("d1")]
    run(shop)
    f = by_summary(findings(client, shop["owner"], check_code="test.state"), "d1")
    r = client.post(f"{INTEL}/findings/{f['id']}/dismiss", headers=shop["owner"], json={"reason": "Known and fine"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    run(shop)
    assert not [x for x in findings(client, shop["owner"], check_code="test.state") if x["summary"] == "Problem d1"]
    closed = by_summary(findings(client, shop["owner"], status="dismissed"), "d1")
    assert closed["status"] == "dismissed"


def test_a_failing_check_does_not_stop_the_others_and_is_reported(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["raise"] = True
    PLAN["oneoff"] = [cand("f1")]
    result = run(shop)
    assert "test.state" in result.failed and result.created == 1
    with system(shop) as s:
        row = s.execute(text("select message from kernel.exception_item where kind = 'check_failed'")).first()
    assert row is not None and "could not run" in row.message


def test_bad_candidates_are_ignored(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("b1", severity="catastrophic"), cand("b2"), cand("b2")]
    result = run(shop)
    assert result.created == 1
    assert not [f for f in findings(client, shop["owner"]) if f["summary"] == "Problem b1"]


# --------------------------------------------------------------------------- who sees what, and what people do
def test_people_see_only_findings_in_their_scope(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("s-hq", branch=shop["branch_id"]), cand("s-juja", branch=shop["juja"]), cand("s-co")]
    run(shop)
    mine = {f["summary"] for f in findings(client, shop["manager"], check_code="test.state")}
    assert "Problem s-hq" in mine and "Problem s-juja" not in mine and "Problem s-co" not in mine
    company_wide = {f["summary"] for f in findings(client, shop["boss"], check_code="test.state")}
    assert {"Problem s-hq", "Problem s-juja", "Problem s-co"} <= company_wide
    other = by_summary(findings(client, shop["boss"], check_code="test.state"), "s-juja")
    assert client.get(f"{INTEL}/findings/{other['id']}", headers=shop["manager"]).status_code == 404
    assert client.get(f"{INTEL}/findings", headers=shop["juja_keeper"]).status_code == 403
    summary = client.get(f"{INTEL}/findings/summary", headers=shop["manager"]).json()
    assert summary["open"] >= 1 and set(summary["by_severity"]) <= {"info", "low", "medium", "high", "critical"}


def test_the_assigned_person_can_explain_and_nobody_else_without_manage(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("x1", branch=shop["branch_id"])]
    run(shop)
    f = by_summary(findings(client, shop["owner"], check_code="test.state"), "x1")
    path = f"{INTEL}/findings/{f['id']}"
    assert client.post(f"{path}/explain", headers=shop["manager"], json={"note": "I did it"}).status_code == 403
    manager_id = next(u for u in client.get("/api/v1/users", headers=shop["owner"]).json() if u["full_name"] == "manager")["id"]
    assert client.post(f"{path}/assign", headers=shop["owner"], json={"user_id": manager_id}).status_code == 200
    assert client.post(f"{path}/explain", headers=shop["manager"], json={"note": ""}).status_code in (400, 422)
    r = client.post(f"{path}/explain", headers=shop["manager"], json={"note": "Delivery was refused, restocked at 3pm"})
    assert r.status_code == 200 and r.json()["status"] == "explained"
    assert r.json()["explanation"].startswith("Delivery was refused")
    assert client.post(f"{path}/resolve", headers=shop["manager"], json={}).status_code == 403   # respond is not manage
    done = client.post(f"{path}/resolve", headers=shop["owner"], json={"note": "Checked"})
    assert done.status_code == 200 and done.json()["status"] == "resolved"
    assert client.post(f"{path}/acknowledge", headers=shop["owner"], json={}).status_code == 422  # closed: no way back
    events = [e["event"] for e in done.json()["events"]]
    assert events == ["detected", "assigned", "explained", "resolved"]
    assert all(e["user_name"] for e in done.json()["events"][1:])


def test_dismissing_needs_a_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("x2")]
    run(shop)
    f = by_summary(findings(client, shop["owner"], check_code="test.state"), "x2")
    assert client.post(f"{INTEL}/findings/{f['id']}/dismiss", headers=shop["owner"], json={"reason": "  "}).status_code == 422


def test_asking_someone_to_explain_needs_the_business_to_allow_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("a1", branch=shop["branch_id"])]
    run(shop)
    f = by_summary(findings(client, shop["owner"], check_code="test.state"), "a1")
    manager_id = next(u for u in client.get("/api/v1/users", headers=shop["owner"]).json() if u["full_name"] == "manager")["id"]
    body = {"user_id": manager_id, "message": "Please check the delivery note."}
    denied = client.post(f"{INTEL}/findings/{f['id']}/ask", headers=shop["owner"], json=body)
    assert denied.status_code == 422 and "intel_action_level" in denied.text
    company = str(shop["company_id"])
    assert client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"],
                        json={"intel_action_level": 2}).status_code == 200
    ok = client.post(f"{INTEL}/findings/{f['id']}/ask", headers=shop["owner"], json=body)
    assert ok.status_code == 200 and ok.json()["owner_user_id"] == manager_id
    assert ok.json()["events"][-1]["event"] == "asked"
    # a person who cannot answer for that branch cannot be asked
    juja = next(u for u in client.get("/api/v1/users", headers=shop["owner"]).json() if u["full_name"] == "jujakeeper")["id"]
    assert client.post(f"{INTEL}/findings/{f['id']}/ask", headers=shop["owner"],
                       json={"user_id": juja, "message": ""}).status_code == 422
    mine = findings(client, shop["manager"], assigned_to_me="true")
    assert any(x["id"] == f["id"] for x in mine)


# --------------------------------------------------------------------------- alerts
def queued(shop, ref_id: str) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return list(s.execute(text("select recipient, channel, body from kernel.notification where ref_id = :r"),
                              {"r": ref_id}).all())


def test_alerts_go_only_where_the_business_asked_and_only_to_those_who_may_see(client, shop) -> None:  # type: ignore[no-untyped-def]
    company = str(shop["company_id"])
    PLAN["candidates"] = [cand("al-low", severity="low"), cand("al-high", severity="high", branch=shop["branch_id"])]
    run(shop)
    with system(shop) as s:
        assert alerts.send_alerts(s, shop["company_id"]) == 0                           # channel is off by default
    assert client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"],
                        json={"intel_alert_channel": "email"}).status_code == 200
    with system(shop) as s:
        assert alerts.send_alerts(s, shop["company_id"]) >= 1
    high = by_summary(findings(client, shop["owner"], check_code="test.state"), "al-high")
    low = by_summary(findings(client, shop["owner"], check_code="test.state"), "al-low")
    assert high["status"] == "sent" and low["status"] == "new"                         # below the severity bar: waits
    sent = {r.recipient for r in queued(shop, high["id"])}
    assert f"manager@{shop['code']}.test" in sent and f"owner@{shop['code']}.test" in sent
    assert f"jujakeeper@{shop['code']}.test" not in sent and not queued(shop, low["id"])
    with system(shop) as s:
        assert alerts.send_alerts(s, shop["company_id"]) == 0                           # never alerted twice
    assert len(queued(shop, high["id"])) == len(sent)
    client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"], json={"intel_alert_channel": "off"})


# --------------------------------------------------------------------------- settings of the checks
def test_a_business_can_switch_a_check_off_and_change_its_limits(client, shop) -> None:  # type: ignore[no-untyped-def]
    listed = {c["code"]: c for c in client.get(f"{INTEL}/checks", headers=shop["owner"]).json()}
    assert listed["test.state"]["params"] == {"limit": 5, "named": "x"} and listed["test.state"]["enabled"]
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["manager"], json={"enabled": False}).status_code == 403
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"params": {"nope": 1}}).status_code == 422
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"params": {"limit": "abc"}}).status_code == 422
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"params": {"limit": -1}}).status_code == 422
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"params": {"limit": "9.5"}}).status_code == 422
    r = client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"params": {"limit": "9"}})
    assert r.status_code == 200 and r.json()["params"]["limit"] == 9 and r.json()["defaults"]["limit"] == 5
    PLAN["candidates"] = [cand("p1")]
    run(shop)
    assert PLAN["params"]["limit"] == 9 and PLAN["params"]["named"] == "x"
    assert client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"enabled": False}).json()["enabled"] is False
    PLAN["params"] = None
    result = run(shop)
    assert PLAN["params"] is None and "test.state" not in result.failed             # switched off: it did not run
    client.patch(f"{INTEL}/checks/test.state", headers=shop["owner"], json={"enabled": True, "params": {"limit": 5}})


def test_run_now_works_for_a_manager_and_is_scoped(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("r1")]
    body = {"company_id": str(shop["company_id"]), "checks": ["test.state"]}
    assert client.post(f"{INTEL}/run", headers=shop["manager"], json=body).status_code == 403
    r = client.post(f"{INTEL}/run", headers=shop["owner"], json=body)
    assert r.status_code == 200 and r.json()["checks_run"] == 1 and r.json()["created"] == 1
    assert client.post(f"{INTEL}/run", headers=shop["owner"], json={"company_id": str(uuid4())}).status_code == 422


# --------------------------------------------------------------------------- baselines
def test_baselines_are_learned_per_dimension(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        stored = baselines.refresh_company(s, shop["company_id"], date(2026, 10, 14), metrics=[FakeMetric()])
        assert stored == 2
        learned = baselines.load(s, shop["company_id"])
    a, b = learned.get("test.metric", "a"), learned.get("test.metric", "b")
    assert a is not None and (a.mean, a.stddev, a.sample_size) == (5, 2, 8)
    assert b is not None and b.mean == 10 and b.stddev == 0
    assert learned.get("test.metric", "zzz") is None and learned.get("other", "a") is None


# --------------------------------------------------------------------------- running by hand
def test_the_command_line_runs_the_recurring_checks_now(client, shop, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    PLAN["candidates"] = [cand("cli1")]
    assert cli.main(["run-task", shop["code"], "intel.run_checks"]) == 0
    assert "Ran intel.run_checks" in capsys.readouterr().out
    assert any(f["summary"] == "Problem cli1" for f in findings(client, shop["owner"], check_code="test.state"))
    assert cli.main(["run-task", shop["code"], "no.such_task"]) == 1
    assert "Unknown recurring task" in capsys.readouterr().err
