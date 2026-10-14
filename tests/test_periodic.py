"""Recurring tasks: claimed once per interval, failures recorded, and old quotations expire without anyone looking."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Periodic Co", stock="100")
    s["rep"] = s["user"]("rep", "Sales Rep", s["branch_id"])
    return s


def test_old_quotations_expire_by_themselves_and_only_once_per_interval(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    cust = credit_customer(client, shop, name="Quote Expiry", limit="1000")
    ids = []
    for _ in range(3):
        q = client.post(f"{POS}/quotations", headers=shop["rep"], json={
            "customer_id": cust["id"], "location_id": shop["main"], "valid_until": str(date.today() + timedelta(days=1)),
            "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).json()
        ids.append(q["id"])
    with system(shop) as s:
        s.execute(text("update pos.sales_document set valid_until = current_date - 2 where id = any(cast(:i as uuid[]))"),
                  {"i": ids[:2]})
    assert jobs.run_periodic(shop["tenant_id"]) >= 1                       # the first pass runs the task
    statuses = [one(shop, "select status from pos.sales_document where id = :i", i=i) for i in ids]
    assert statuses == ["expired", "expired", "draft"]
    assert jobs.run_periodic(shop["tenant_id"]) == 0                       # not again within the interval
    with system(shop) as s:
        s.execute(text("update kernel.periodic_run set last_run_at = now() - interval '1 day' "
                       "where name = 'pos.expire_quotations'"))
    assert jobs.run_periodic(shop["tenant_id"]) == 1
    assert one(shop, "select count(*) from kernel.audit_log where action = 'expire' and entity_id = :i", i=ids[0]) == 1


def test_a_task_that_fails_is_recorded_and_tried_again_next_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    calls = []

    @jobs.periodic("pos.test_task", every_seconds=60)
    def flaky(session):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the gateway is down")

    flaky.__module__ = "ziira.modules.pos.jobs"                           # it belongs to POS for this test
    jobs._periodic["pos.test_task"] = ("pos", 60, flaky)
    try:
        assert jobs.run_periodic(shop["tenant_id"]) >= 1
        err = one(shop, "select last_error from kernel.periodic_run where name = 'pos.test_task'")
        assert "the gateway is down" in err
        items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "periodic_failed"}).json()
        assert any("pos.test_task" in i["message"] for i in items)
        with system(shop) as s:
            s.execute(text("update kernel.periodic_run set last_run_at = now() - interval '5 minutes' "
                           "where name = 'pos.test_task'"))
        jobs.run_periodic(shop["tenant_id"])
        assert len(calls) == 2
        assert one(shop, "select last_error from kernel.periodic_run where name = 'pos.test_task'") is None
    finally:
        jobs._periodic.pop("pos.test_task", None)


def test_a_recurring_task_of_a_unit_that_is_off_does_not_run(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import make_stock_shop
    from ziira.kernel import jobs

    other = make_stock_shop(client, registry, "Periodic Off Co")
    assert jobs.run_periodic(other["tenant_id"]) == 1                    # only the kernel's own daily privacy task
    assert one(other, "select string_agg(name, ',') from kernel.periodic_run") == "privacy.apply_retention"
    assert uuid4()
    with pytest.raises(ValueError):
        jobs.periodic("too.fast", every_seconds=5)
