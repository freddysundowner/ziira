"""Platform pieces for phase 4: idempotency keys, the job queue and worker, and the exceptions inbox."""

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from tests.stock_helpers import make_stock_shop, system
from ziira.sdk import ValidationFailed


@pytest.fixture(scope="module")
def t(client, registry):  # type: ignore[no-untyped-def]
    return make_tenant("Platform Co")


# --------------------------------------------------------------------------- idempotency keys
def test_a_retried_request_is_done_once_and_gets_the_same_answer(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import idempotent

    runs: list[int] = []

    def operation() -> dict[str, object]:
        runs.append(1)
        return {"id": str(uuid4()), "amount": "10.00"}

    with system(t) as s:
        first, replayed = idempotent(s, "key-1", {"amount": 10}, operation)
    with system(t) as s:
        second, again = idempotent(s, "key-1", {"amount": 10}, operation)
    assert not replayed and again and first == second and len(runs) == 1


def test_the_same_key_for_a_different_request_is_refused(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import idempotent

    with system(t) as s:
        idempotent(s, "key-2", {"amount": 10}, lambda: {"ok": True})
    with pytest.raises(ValidationFailed, match="different request"), system(t) as s:
        idempotent(s, "key-2", {"amount": 11}, lambda: {"ok": True})


def test_without_a_key_it_just_runs_and_bad_keys_are_refused(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import idempotent

    runs: list[int] = []
    with system(t) as s:
        idempotent(s, None, {}, lambda: runs.append(1))
        idempotent(s, None, {}, lambda: runs.append(1))
    assert len(runs) == 2
    for bad in ("", "x" * 201, "bad\nkey", "tab\tkey"):
        with pytest.raises(ValidationFailed), system(t) as s:
            idempotent(s, bad, {}, lambda: {})


def test_a_failed_operation_stores_nothing_so_a_retry_runs_it(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import idempotent

    def boom() -> dict[str, object]:
        raise RuntimeError("the connection dropped")

    with pytest.raises(RuntimeError), system(t) as s:
        idempotent(s, "key-3", {"a": 1}, boom)
    with system(t) as s:
        assert idempotent(s, "key-3", {"a": 1}, lambda: {"done": True}) == ({"done": True}, False)


def test_two_copies_arriving_together_run_once(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.sdk import idempotent

    runs: list[int] = []
    barrier = threading.Barrier(6)

    def attempt() -> bool:
        system_context(t["tenant_id"])
        barrier.wait()
        with tenant_session(t["tenant_id"]) as s:
            _, replayed = idempotent(s, "key-race", {"x": 1}, lambda: (runs.append(1), {"ok": 1})[1])
        return replayed

    with ThreadPoolExecutor(6) as pool:
        replays = list(pool.map(lambda _: attempt(), range(6)))
    assert len(runs) == 1 and replays.count(False) == 1


def test_old_keys_are_forgotten(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session
    from ziira.kernel.idempotency import purge_old_keys

    with tenant_session(t["tenant_id"], admin=True) as s:
        s.execute(text("update kernel.idempotency_key set created_at = now() - interval '8 days' "
                       "where key = 'key-1'"))
    with system(t) as s:
        assert purge_old_keys(s) == 1
        assert s.execute(text("select count(*) from kernel.idempotency_key where key = 'key-2'")).scalar_one() == 1


# --------------------------------------------------------------------------- the job queue
@pytest.fixture
def handlers():  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    added: list[str] = []

    def register(job_type: str, fn, unit: str = "kernel"):  # type: ignore[no-untyped-def]
        jobs._handlers[job_type].append((unit, fn))
        added.append(job_type)

    yield register
    for job_type in added:
        jobs._handlers.pop(job_type, None)


def state(t, key: str):  # type: ignore[no-untyped-def]
    with system(t) as s:
        return s.execute(text("select status, attempts, last_error, run_at > now() as waiting from kernel.job "
                              "where dedupe_key = :k"), {"k": key}).one()


def test_jobs_run_once_when_due(t, handlers) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs
    from ziira.sdk import enqueue

    seen: list[dict] = []  # type: ignore[type-arg]
    handlers("test.ok", lambda s, payload: seen.append(payload))
    with system(t) as s:
        enqueue(s, "test.ok", {"n": 1}, dedupe_key="ok-1")
        enqueue(s, "test.ok", {"n": 1}, dedupe_key="ok-1")                    # the same job twice is one job
        enqueue(s, "test.ok", {"n": 2}, delay_seconds=3600, dedupe_key="ok-later")
    assert jobs.run_due(t["tenant_id"]) == 1
    assert seen == [{"n": 1}] and state(t, "ok-1").status == "done"
    assert state(t, "ok-later").status == "queued"                              # not due yet
    assert jobs.run_due(t["tenant_id"]) == 0 and len(seen) == 1                 # and done jobs do not run again


def test_failing_jobs_are_retried_with_growing_delays_then_flagged(t, handlers) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs
    from ziira.kernel.db import tenant_session
    from ziira.sdk import enqueue

    handlers("test.bad", lambda s, payload: (_ for _ in ()).throw(RuntimeError("service down")))
    with system(t) as s:
        enqueue(s, "test.bad", {}, dedupe_key="bad-1", max_attempts=3)
    for attempt in (1, 2, 3):
        jobs.run_due(t["tenant_id"])
        row = state(t, "bad-1")
        assert row.attempts == attempt and "service down" in row.last_error
        if attempt < 3:
            assert row.status == "queued" and row.waiting                      # try again later
            with tenant_session(t["tenant_id"], admin=True) as s:              # (skip the wait)
                s.execute(text("update kernel.job set run_at = now() where dedupe_key = 'bad-1'"))
    assert state(t, "bad-1").status == "failed"
    with system(t) as s:
        flagged = s.execute(text("select kind, severity, status from kernel.exception_item "
                                 "where kind = 'job_failed'")).all()
    assert [tuple(r) for r in flagged] == [("job_failed", "high", "open")]


def test_backoff_grows_and_stops_at_an_hour() -> None:
    from ziira.kernel.jobs import backoff_seconds

    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]
    assert backoff_seconds(30) == 3600


def test_jobs_of_a_disabled_unit_wait_and_unknown_types_fail(t, handlers) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs
    from ziira.sdk import enqueue

    handlers("test.off", lambda s, payload: None, unit="inventory")       # inventory is not enabled for this tenant
    with system(t) as s:
        enqueue(s, "test.off", {}, dedupe_key="off-1")
        enqueue(s, "test.nobody", {}, dedupe_key="nobody-1")
    jobs.run_due(t["tenant_id"])
    assert state(t, "off-1").status == "queued" and state(t, "off-1").attempts == 0
    assert state(t, "nobody-1").attempts == 1 and "No handler" in state(t, "nobody-1").last_error


def test_the_worker_command_runs_events_and_jobs(t, handlers, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli
    from ziira.sdk import enqueue

    seen: list[int] = []
    handlers("test.cli", lambda s, payload: seen.append(1))
    with system(t) as s:
        enqueue(s, "test.cli", {}, dedupe_key="cli-1")
    assert cli.main(["worker", "--once"]) == 0
    assert "ran" in capsys.readouterr().out and seen == [1]


# --------------------------------------------------------------------------- the exceptions inbox
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Inbox Co")


def raise_item(shop, **kw):  # type: ignore[no-untyped-def]
    from ziira.sdk import flag_for_review

    with system(shop) as s:
        return flag_for_review(s, unit="test", kind=kw.pop("kind", "thing"), message=kw.pop("message", "Look at this"),
                               company_id=shop["company_id"], **kw)


def test_items_are_raised_once_per_dedupe_key_and_announced(shop) -> None:  # type: ignore[no-untyped-def]
    first = raise_item(shop, dedupe_key="same-problem", branch_id=shop["branch_id"], amount=Dec("12.5"))
    assert first is not None and raise_item(shop, dedupe_key="same-problem") is None
    assert raise_item(shop) is not None and raise_item(shop) is not None          # without a key every call is an item
    with system(shop) as s:
        announced = s.execute(text("select count(*) from kernel.event_outbox where event_type = 'exception.raised' "
                                   "and aggregate_id = :i"), {"i": str(first)}).scalar_one()
    assert announced == 1
    with pytest.raises(ValidationFailed, match="Severity"):
        raise_item(shop, severity="apocalyptic")


def test_negative_stock_lands_in_the_inbox(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                 json={"negative_stock_allowed": True})
    from ziira.sdk import Event, publish

    with system(shop) as s:
        publish(s, Event("sale.posted", "pos.sale", uuid4(), {
            "company_id": shop["company_id"], "location_id": shop["main"],
            "lines": [{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "3"}]}))
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "negative_stock"}).json()
    assert len(items) == 1 and items[0]["unit_name"] == "inventory" and "CEM" in items[0]["message"]
    assert items[0]["branch_id"] == str(shop["branch_id"]) and items[0]["status"] == "open"


def test_working_an_item_assign_explain_resolve(client, shop) -> None:  # type: ignore[no-untyped-def]
    item = raise_item(shop, kind="flow", branch_id=shop["branch_id"])
    manager = shop["manager"]
    url = f"/api/v1/exceptions/{item}"
    assert client.get(url, headers=manager).json()["status"] == "open"
    me = client.get("/api/v1/auth/me", headers=manager).json()["user_id"]
    assert client.post(f"{url}/assign", headers=manager, json={"user_id": me}).json()["assigned_to"] == me
    assert client.post(f"{url}/assign", headers=manager, json={"user_id": str(uuid4())}).status_code == 422
    assert client.post(f"{url}/status", headers=manager, json={"status": "resolved", "note": " "}).status_code == 422
    r = client.post(f"{url}/status", headers=manager, json={"status": "explained", "note": "Checking with the shop"})
    assert r.json()["status"] == "explained" and r.json()["resolved_by"] is None
    r = client.post(f"{url}/status", headers=manager, json={"status": "resolved", "note": "It was a miscount"})
    assert r.json()["status"] == "resolved" and r.json()["resolved_by"] == me and r.json()["resolved_at"]
    assert client.post(f"{url}/status", headers=manager, json={"status": "dismissed", "note": "x"}).status_code == 422
    assert client.post(f"{url}/status", headers=manager, json={"status": "bogus", "note": "x"}).status_code == 422
    assert client.get(f"/api/v1/exceptions/{uuid4()}", headers=manager).status_code == 404


def test_the_inbox_is_limited_to_the_users_branches_and_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    hq = raise_item(shop, kind="scoped", branch_id=shop["branch_id"])
    juja = raise_item(shop, kind="scoped", branch_id=shop["juja"])
    company_wide = raise_item(shop, kind="scoped")
    def ids(headers):  # type: ignore[no-untyped-def]
        items = client.get("/api/v1/exceptions", headers=headers, params={"kind": "scoped"}).json()
        return {i["id"] for i in items}

    assert ids(shop["owner"]) == {str(hq), str(juja), str(company_wide)}
    assert ids(shop["boss"]) == {str(hq), str(juja), str(company_wide)}              # company-wide: all of them
    assert ids(shop["manager"]) == {str(hq)}                                         # one branch: only its own items
    assert client.get(f"/api/v1/exceptions/{juja}", headers=shop["manager"]).status_code == 404
    assert client.get(f"/api/v1/exceptions/{company_wide}", headers=shop["manager"]).status_code == 404
    for who in ("cashier", "storekeeper"):
        assert client.get("/api/v1/exceptions", headers=shop[who]).status_code == 403
    assert client.get("/api/v1/exceptions", params={"limit": 0}, headers=shop["owner"]).status_code == 422
