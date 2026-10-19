"""Intelligence checks and Command Center figures over Jobs: stuck jobs, estimates nobody answered, finished work never
invoiced, repeat returns, finished items nobody collected. A real business, the real engine, today is 2026-10-14."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.jobs_helpers import JOBS, make_jobs_shop, move, new_job
from tests.stock_helpers import system
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import engine
from ziira.modules.jobs.intel_checks import (
    CourtesyCarOverdue,
    EstimateNotAnswered,
    JobStuck,
    PartOverdue,
    PartsNotInvoiced,
    ReadyNotCollected,
    RepeatReturns,
)

TODAY = date(2026, 10, 14)
INTEL = "/api/v1/intel"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_jobs_shop(client, registry, "Jobs Intel Co")


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


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


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=lambda metric, key: None)
        return check.run(s, ctx)


def job_at(client, shop, title: str, stage: str, since: str, **extra):  # type: ignore[no-untyped-def]
    """A job moved to a stage, then dated back: its stage began at `since`."""
    job = new_job(client, shop, title=title, **extra)
    path = {"in_progress": ["in_progress"], "waiting_for_parts": ["diagnosing", "waiting_for_parts"],
            "diagnosing": ["diagnosing"], "ready": ["in_progress", "ready"], "received": []}[stage]
    for code in path:
        assert move(client, shop, job, code).status_code == 200
    sql(shop, "update jobs.job set status_changed_at = cast(:d as timestamptz), "
              "ready_at = case when ready_at is null then null else cast(:d as timestamptz) end where id = :i",
        d=since, i=job["id"])
    return job


# --------------------------------------------------------------------------- stuck in a stage
def test_a_job_that_has_not_moved_for_too_long_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    slow = job_at(client, shop, "Slow repair", "in_progress", "2026-09-20 08:00+00")          # 24 days, working
    parts = job_at(client, shop, "Needs a part", "waiting_for_parts", "2026-09-01 08:00+00")    # 43 days, waiting
    job_at(client, shop, "Fine repair", "diagnosing", "2026-10-12 08:00+00")                    # 2 days
    job_at(client, shop, "Short wait", "waiting_for_parts", "2026-10-05 08:00+00")              # 9 days waiting: under 14
    result = run_check(shop, "jobs.stuck_in_stage")
    assert result.created == 2 and not result.failed
    items = {f["summary"].split(" (")[0]: f for f in findings(client, shop, "jobs.stuck_in_stage")}
    assert set(items) == {f"Job {slow['number']}", f"Job {parts['number']}"}
    assert items[f"Job {slow['number']}"]["summary"] == f"Job {slow['number']} (Slow repair) has been in progress for 24 days."
    assert items[f"Job {slow['number']}"]["severity"] == "medium" and Dec(items[f"Job {slow['number']}"]["value"]) == 24
    assert items[f"Job {parts['number']}"]["severity"] == "high"                                # 43 days >= 30
    assert items[f"Job {slow['number']}"]["branch_id"] == str(shop["branch_id"])
    # tuned: working jobs are fine for 30 days
    assert {c.entity_id for c in direct(shop, JobStuck(), open_days=30)} == {UUID(parts["id"])}
    # the job moves on: the finding closes by itself
    assert move(client, shop, slow, "ready").status_code == 200
    again = run_check(shop, "jobs.stuck_in_stage")
    assert again.resolved == 1


# --------------------------------------------------------------------------- estimates nobody answered
def test_an_estimate_with_no_answer_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    old = new_job(client, shop, title="Old estimate")
    fresh = new_job(client, shop, title="Fresh estimate")
    answered = new_job(client, shop, title="Answered estimate")
    ids = {}
    for name, job in (("old", old), ("fresh", fresh), ("answered", answered)):
        est = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={"lines": [
            {"kind": "labour", "description": "Work", "quantity": "2", "unit_price": "100.00"}]}).json()
        client.post(f"{JOBS}/estimates/{est['id']}/send", headers=shop["owner"], json={})
        ids[name] = est["id"]
    client.post(f"{JOBS}/estimates/{ids['answered']}/decision", headers=shop["owner"], json={"approved": True})
    for name, when in (("old", "2026-10-01 08:00+00"), ("fresh", "2026-10-12 08:00+00"), ("answered", "2026-10-01 08:00+00")):
        sql(shop, "update jobs.estimate set sent_at = cast(:d as timestamptz) where id = :i", d=when, i=ids[name])
    result = run_check(shop, "jobs.estimate_not_approved")
    assert result.created == 1
    only = findings(client, shop, "jobs.estimate_not_approved")[0]
    cur = sql(shop, "select base_currency from kernel.company")[0][0]
    assert only["summary"] == (f"The estimate for job {old['number']} ({cur} 200.00) has waited 13 days for the "
                               "customer's answer.")
    assert Dec(only["amount"]) == 200 and only["severity"] == "low"
    client.post(f"{JOBS}/estimates/{ids['old']}/decision", headers=shop["owner"], json={"approved": False})
    assert run_check(shop, "jobs.estimate_not_approved").resolved == 1


# --------------------------------------------------------------------------- done but never invoiced
def test_finished_work_without_an_invoice_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    def collected(title: str, day: str, invoice: bool = False, cancel: bool = False):  # type: ignore[no-untyped-def]
        job = new_job(client, shop, title=title)
        client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
            "description": "Filter", "quantity": "2", "unit_price": "50.00"})
        client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["owner"], json={"hours": "1", "rate": "80.00"})
        if invoice:
            assert client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["owner"]).status_code == 200
        if cancel:
            move(client, shop, job, "cancelled")
        else:
            for code in ("in_progress", "ready"):
                move(client, shop, job, code)
            client.post(f"{JOBS}/jobs/{job['id']}/collect", headers=shop["owner"], json={})
        sql(shop, "update jobs.job set collected_at = cast(:d as timestamptz), closed_at = cast(:d as timestamptz) "
                  "where id = :i", d=day, i=job["id"])
        return job

    gone = collected("Collected, not billed", "2026-10-05 10:00+00")
    collected("Billed", "2026-10-05 10:00+00", invoice=True)
    collected("Collected yesterday", "2026-10-13 10:00+00")                                    # inside the grace days
    collected("Cancelled with parts", "2026-10-05 10:00+00", cancel=True)
    empty = new_job(client, shop, title="No parts, no labour")
    for code in ("in_progress", "ready"):
        move(client, shop, empty, code)
    client.post(f"{JOBS}/jobs/{empty['id']}/collect", headers=shop["owner"], json={})
    sql(shop, "update jobs.job set collected_at = cast('2026-10-05 10:00+00' as timestamptz) where id = :i", i=empty["id"])
    result = run_check(shop, "jobs.parts_not_invoiced")
    assert result.created == 1
    only = findings(client, shop, "jobs.parts_not_invoiced")[0]
    cur = sql(shop, "select base_currency from kernel.company")[0][0]
    # 2 x 50.00 of parts and 1 h x 80.00 of labour
    assert only["summary"] == f"Job {gone['number']} is done and worth {cur} 180.00 but has no invoice."
    assert Dec(only["amount"]) == 180 and only["severity"] == "high"
    assert client.post(f"{JOBS}/jobs/{gone['id']}/invoice", headers=shop["owner"]).status_code == 200
    assert run_check(shop, "jobs.parts_not_invoiced").resolved == 1


# --------------------------------------------------------------------------- repeat returns
def test_repeat_returns_inside_the_warranty_point_at_one_persons_work(client, shop) -> None:  # type: ignore[no-untyped-def]
    tech = shop["users"]["tech"]

    def returns(title: str, count: int, inside: bool = True):  # type: ignore[no-untyped-def]
        original = new_job(client, shop, title=title, assignee_id=tech)
        for code in ("in_progress", "ready"):
            move(client, shop, original, code)
        client.post(f"{JOBS}/jobs/{original['id']}/collect", headers=shop["owner"], json={})
        for _ in range(count):
            visit = client.post(f"{JOBS}/jobs/{original['id']}/return-visit", headers=shop["owner"], json={})
            assert visit.status_code == 201
            sql(shop, "update jobs.job set received_at = cast('2026-10-10 10:00+00' as timestamptz), "
                      "rework_in_warranty = :w where id = :i", w=inside, i=visit.json()["id"])
        return original

    returns("Two comebacks", 2)
    assert run_check(shop, "jobs.repeat_returns").created == 0                                # two is below three
    returns("Third comeback", 1)
    assert run_check(shop, "jobs.repeat_returns").created == 1
    only = findings(client, shop, "jobs.repeat_returns")[0]
    assert only["summary"].endswith("had 3 customers come back inside the warranty in the last 90 days.")
    assert Dec(only["value"]) == 3 and only["entity_id"] == tech
    assert len(direct(shop, RepeatReturns(), min_returns=4)) == 0
    # comebacks after the warranty ended are not counted
    returns("Out of warranty", 3, inside=False)
    assert len(direct(shop, RepeatReturns(), min_returns=4)) == 0


# --------------------------------------------------------------------------- ready, not collected
def test_items_left_waiting_to_be_collected_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    long = job_at(client, shop, "Forgotten phone", "ready", "2026-10-01 09:00+00")
    sql(shop, "update jobs.job set ready_at = cast('2026-10-01 09:00+00' as timestamptz) where id = :i", i=long["id"])
    recent = job_at(client, shop, "Just finished", "ready", "2026-10-12 09:00+00")
    sql(shop, "update jobs.job set ready_at = cast('2026-10-12 09:00+00' as timestamptz) where id = :i", i=recent["id"])
    assert run_check(shop, "jobs.ready_not_collected").created == 1
    only = findings(client, shop, "jobs.ready_not_collected")[0]
    assert only["summary"] == f"Job {long['number']} (Forgotten phone) has been ready for 13 days and is not collected."
    assert only["severity"] == "low"
    assert direct(shop, ReadyNotCollected(), serious_days=10)[0].severity == "medium"
    client.post(f"{JOBS}/jobs/{long['id']}/collect", headers=shop["owner"], json={})
    assert run_check(shop, "jobs.ready_not_collected").resolved == 1


def test_a_late_part_and_an_overdue_courtesy_car_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Waiting on a part")
    late = client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "description": "Gearbox", "quantity": "1", "unit_price": "900", "order_for_job": True,
        "expected_on": "2026-10-10", "supplier_name": "Spares Ltd"}).json()
    client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "description": "Not late yet", "quantity": "1", "unit_price": "10", "order_for_job": True,
        "expected_on": "2026-10-20"})
    found = direct(shop, PartOverdue())
    assert len(found) == 1 and "Gearbox" in found[0].summary and "4 days late" in found[0].summary
    assert "Spares Ltd" in found[0].summary
    client.post(f"{JOBS}/jobs/{job['id']}/parts/{late['parts'][0]['id']}/arrived", headers=shop["owner"], json={})
    assert direct(shop, PartOverdue()) == []
    car = client.post(f"{JOBS}/assets", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "label": "Courtesy Note KCA 1", "kind": "courtesy-car"}).json()
    loan = client.post(f"{JOBS}/jobs/{job['id']}/loans", headers=shop["owner"], json={
        "asset_id": car["id"], "due_at": "2026-10-12"})
    assert loan.status_code == 201, loan.text
    cars = direct(shop, CourtesyCarOverdue())
    assert len(cars) == 1 and "2 days overdue" in cars[0].summary and cars[0].branch_id == shop["branch_id"]
    client.post(f"{JOBS}/loans/{loan.json()['loans'][0]['id']}/return", headers=shop["owner"], json={})
    assert direct(shop, CourtesyCarOverdue()) == []


def test_the_checks_say_what_they_are() -> None:
    codes = {c.code for c in (JobStuck, EstimateNotAnswered, PartsNotInvoiced, RepeatReturns, ReadyNotCollected,
                              PartOverdue, CourtesyCarOverdue)}
    assert codes == {"jobs.stuck_in_stage", "jobs.estimate_not_approved", "jobs.parts_not_invoiced",
                     "jobs.repeat_returns", "jobs.ready_not_collected", "jobs.part_overdue",
                     "jobs.courtesy_car_overdue"}


# --------------------------------------------------------------------------- figures
def test_figures_for_the_command_center(client, shop) -> None:  # type: ignore[no-untyped-def]
    sql(shop, "update jobs.job set received_at = '2026-10-01 08:00+00'")
    todays = [new_job(client, shop, title=f"Arrived {i}") for i in range(2)]
    for job in todays:
        sql(shop, "update jobs.job set received_at = '2026-10-14 08:00+00' where id = :i", i=job["id"])
    sql(shop, "update jobs.job set promised_at = '2026-10-10' where id = :i", i=todays[0]["id"])      # promised, late
    with system(shop) as s:
        assert pulse.refresh_company(s, shop["company_id"], TODAY) >= 5
    rows = sql(shop, "select metric, branch_id, value from command.pulse_figure where day = :d and metric like 'jobs.%'",
               d=TODAY)
    got = {r.metric: Dec(r.value) for r in rows if r.branch_id is None}
    assert got["jobs.received_today"] == 2 and got["jobs.late"] >= 1
    live = sql(shop, "select count(*) from jobs.job j join jobs.job_status s on s.id = j.status_id "
                     "where s.kind in ('open', 'waiting')")[0][0]
    assert got["jobs.open"] == live
    ready = sql(shop, "select count(*) from jobs.job j join jobs.job_status s on s.id = j.status_id "
                      "where s.role = 'ready'")[0][0]
    assert got["jobs.ready_for_collection"] == ready
    assert got["jobs.awaiting_approval"] == sql(shop, "select count(distinct job_id) from jobs.estimate "
                                                      "where status = 'sent'")[0][0]
    assert {r.branch_id for r in rows} >= {None, shop["branch_id"]}
