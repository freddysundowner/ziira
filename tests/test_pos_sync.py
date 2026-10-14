"""Working offline: a device sells without a connection and uploads what happened. Every operation lands exactly once,
however often or however many times at once it is sent, and what cannot be accepted is kept, never lost."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from itertools import count
from uuid import uuid4

import pytest

from tests.payments_helpers import PAY, one
from tests.pos_helpers import POS, line, make_pos_shop, stock
from tests.test_lifecycle_more import together

NUMBERS = count(1)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_pos_shop(client, registry, "Pos Sync Co", stock="500")
    s["offline_cashier"] = s["user"]("offline", "Cashier", s["branch_id"])
    dev = client.post(f"{POS}/devices", headers=s["owner"], json={
        "branch_id": str(s["branch_id"]), "code": "OFF1", "name": "Offline tablet", "location_id": s["main"]}).json()
    s["off_key"], s["off_device"] = dev["key"], dev["id"]
    return s


@pytest.fixture(autouse=True)
def no_stray_tills(shop):  # type: ignore[no-untyped-def]
    """Each test starts with the offline device's till closed (a failed test must not break the ones after it)."""
    from sqlalchemy import text

    from tests.stock_helpers import system

    with system(shop) as s:
        s.execute(text("update pos.till_session set status = 'closed', closed_at = now() where device_id = :d "
                       "and status = 'open'"), {"d": shop["off_device"]})
    yield


def hours_ago(h: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=h)).isoformat()


def op_open(local=None, at=None, float_="1000.00"):  # type: ignore[no-untyped-def]
    return {"type": "till_open", "local_id": local or str(uuid4()), "at": at or hours_ago(5), "opening_float": float_}


def op_sale(till_local, lines=None, payments=None, at=None, number=None, local=None, **kw):  # type: ignore[no-untyped-def]
    return {"type": "sale", "local_id": local or str(uuid4()), "till_local_id": till_local, "at": at or hours_ago(4),
            "number": number or f"POS-HQ-OFF1-L{next(NUMBERS):06d}", "lines": lines,
            "payments": payments or [{"method": "cash", "amount": "116.00"}], **kw}


def op_close(till_local, counted, at=None, local=None, **kw):  # type: ignore[no-untyped-def]
    return {"type": "till_close", "local_id": local or str(uuid4()), "till_local_id": till_local, "at": at or hours_ago(1),
            "counted_cash": counted, **kw}


def upload(client, shop, ops, who="offline_cashier", key=None):  # type: ignore[no-untyped-def]
    return client.post(f"{POS}/sync/upload", headers={**shop[who], "X-Device-Key": shop["off_key"] if key is None else key},
                       json={"ops": ops})


def statuses(response) -> list[str]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return [r["status"] for r in response.json()["results"]]


def fix_lines(shop, ops):  # type: ignore[no-untyped-def]
    for op in ops:
        if op["type"] == "sale" and op["lines"] is None:
            op["lines"] = [line(shop, "cement", "1", unit_price="116.00")]
    return ops


def totals(shop):  # type: ignore[no-untyped-def]
    return {
        "sales": one(shop, "select count(*) from pos.sale"), "lines": one(shop, "select count(*) from pos.sale_line"),
        "payments": one(shop, "select count(*) from payments.payment"),
        "movements": one(shop, "select count(*) from inventory.stock_movement"),
        "tills": one(shop, "select count(*) from pos.till_session"), "stock": stock(shop),
        "outbox": one(shop, "select count(*) from kernel.event_outbox where event_type = 'sale.posted'"),
    }


# --------------------------------------------------------------------------- the snapshot
def test_the_snapshot_gives_a_device_what_it_needs_to_sell_offline(client, shop) -> None:  # type: ignore[no-untyped-def]
    headers = {**shop["offline_cashier"], "X-Device-Key": shop["off_key"]}
    snap = client.get(f"{POS}/sync/snapshot", headers=headers).json()
    assert snap["branch_id"] == str(shop["branch_id"]) and snap["location_id"] == shop["main"]
    items = {i["sku"]: i for i in snap["items"]}
    assert Dec(items["CEM"]["price"]) == 116 and Dec(items["CEM"]["stock"]) == 500 and Dec(items["CEM"]["vat_rate"]) == 16
    assert items["DELIVERY"]["stock"] is None and items["PAINT"]["is_batch_tracked"] is True
    assert snap["has_more"] is False and snap["server_time"]
    page = client.get(f"{POS}/sync/snapshot", headers=headers, params={"limit": 1}).json()
    assert len(page["items"]) == 1 and page["has_more"] is True
    second = client.get(f"{POS}/sync/snapshot", headers=headers, params={"limit": 1, "offset": 1}).json()
    assert second["items"][0]["product_id"] != page["items"][0]["product_id"]
    assert client.get(f"{POS}/sync/snapshot", headers=shop["offline_cashier"]).status_code == 403     # no device key
    assert client.get(f"{POS}/sync/snapshot", headers=headers, params={"limit": 0}).status_code == 422


def test_catalog_for_a_signed_in_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{POS}/catalog", headers=shop["cashier"], params={
        "branch_id": str(shop["branch_id"]), "location_id": shop["main"], "search": "cem"}).json()
    assert [i["sku"] for i in r] == ["CEM"] and Dec(r[0]["price"]) == 116
    assert client.get(f"{POS}/catalog", headers=shop["cashier"], params={"branch_id": str(shop["juja"])}).status_code == 404


# --------------------------------------------------------------------------- the day offline, then back online
def day_offline(shop):  # type: ignore[no-untyped-def]
    till = str(uuid4())
    ops = fix_lines(shop, [
        op_open(till),
        op_sale(till, at=hours_ago(4.5)),
        op_sale(till, lines=[line(shop, "cement", "2", unit_price="116.00"), line(shop, "delivery", "1")],
                payments=[{"method": "mobile_money", "amount": "290.00", "external_ref": f"OFF{uuid4().hex[:7].upper()}"}],
                at=hours_ago(4)),
        op_sale(till, payments=[{"method": "cash", "amount": "200.00"}], at=hours_ago(3)),
        op_close(till, "1232.00"),                                         # 1000 float + 116 + 116 cash
    ])
    return till, ops


def test_a_day_offline_syncs_once_and_every_effect_lands(client, shop) -> None:  # type: ignore[no-untyped-def]
    till, ops = day_offline(shop)
    before = totals(shop)
    assert statuses(upload(client, shop, ops)) == ["ok"] * 5
    after = totals(shop)
    assert after["sales"] == before["sales"] + 3 and after["tills"] == before["tills"] + 1
    assert after["stock"] == before["stock"] - 4 and after["movements"] == before["movements"] + 3
    assert after["payments"] == before["payments"] + 3
    sales = client.get(f"{POS}/sales", headers=shop["manager"], params={"limit": 10}).json()
    mine = [s for s in sales if s["synced_offline"]]
    assert len(mine) == 3 and all(s["number"].startswith("POS-HQ-OFF1-L") for s in mine)
    first = min(mine, key=lambda s: s["sold_at"])
    assert abs(datetime.fromisoformat(first["sold_at"]) - datetime.fromisoformat(ops[1]["at"])) < timedelta(seconds=1)
    server_till = client.get(f"{POS}/tills", headers=shop["manager"], params={"status": "closed"}).json()
    assert any(Dec(t["counted_cash"]) == Dec("1232.00") and Dec(t["variance"]) == 0 for t in server_till)
    # every sale's lines, payments and stock agree
    assert one(shop, "select count(*) from pos.sale s where s.total <> (select sum(amount) from pos.sale_payment p "
                     "where p.sale_id = s.id)") == 0
    assert one(shop, "select count(*) from pos.sale s where s.total <> (select sum(line_total) from pos.sale_line l "
                     "where l.sale_id = s.id)") == 0


def test_sending_the_same_day_again_changes_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    till, ops = day_offline(shop)
    assert statuses(upload(client, shop, ops)) == ["ok"] * 5
    settled = totals(shop)
    for _ in range(3):
        assert statuses(upload(client, shop, ops)) == ["duplicate"] * 5
    assert totals(shop) == settled
    results = upload(client, shop, ops).json()["results"]
    assert [r["id"] for r in results if r["type"] == "sale"] == [
        r["id"] for r in upload(client, shop, ops).json()["results"] if r["type"] == "sale"]      # same sales answered


def test_a_connection_that_drops_midway_resumes_without_doubling(client, shop) -> None:  # type: ignore[no-untyped-def]
    till, ops = day_offline(shop)
    assert statuses(upload(client, shop, ops[:3])) == ["ok"] * 3            # the first part got through
    settled = totals(shop)
    again = upload(client, shop, ops)                                        # the device resends everything
    assert statuses(again) == ["duplicate"] * 3 + ["ok"] * 2
    after = totals(shop)
    assert after["sales"] == settled["sales"] + 1 and after["tills"] == settled["tills"]


def test_the_same_batch_sent_by_several_connections_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    till, ops = day_offline(shop)
    before = totals(shop)
    results = together([lambda: upload(client, shop, ops) for _ in range(5)])
    assert all(r.status_code in (200, 409) for r in results), [r.text for r in results if r.status_code not in (200, 409)]
    ok = [r for r in results if r.status_code == 200]
    assert ok
    after = totals(shop)
    assert after["sales"] == before["sales"] + 3 and after["tills"] == before["tills"] + 1
    assert after["stock"] == before["stock"] - 4 and after["payments"] == before["payments"] + 3
    assert after["outbox"] == before["outbox"] + 3                           # and each sale announced once
    # whatever the interleaving, a final resend finds everything done
    assert statuses(upload(client, shop, ops)) == ["duplicate"] * 5


# --------------------------------------------------------------------------- what cannot be accepted is kept
def test_a_bad_operation_is_kept_whole_and_does_not_stop_the_others(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    bad_local, good_local = str(uuid4()), str(uuid4())
    ops = fix_lines(shop, [
        op_open(till),
        op_sale(till, lines=[{"product_id": str(uuid4()), "quantity": "1", "unit_price": "10"}], local=bad_local),
        op_sale(till, local=good_local),
    ])
    r = upload(client, shop, ops)
    assert statuses(r) == ["ok", "rejected", "ok"]
    rejected = r.json()["results"][1]
    assert rejected["local_id"] == bad_local and "not found" in rejected["error"]
    kept = client.get(f"{POS}/sync/rejections", headers=shop["manager"]).json()
    mine = next(k for k in kept if k["local_id"] == bad_local)
    assert mine["op_type"] == "sale" and Dec(mine["payload"]["lines"][0]["unit_price"]) == 10 and mine["attempts"] == 1
    assert client.get(f"{POS}/sync/rejections", headers=shop["cashier"]).status_code == 403
    flagged = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "sync_rejected"}).json()
    assert any(i["ref_id"] == mine["id"] for i in flagged)
    again = upload(client, shop, [ops[1]])                                   # sent again: still bad, counted once
    assert statuses(again) == ["rejected"]
    again_kept = next(k for k in client.get(f"{POS}/sync/rejections", headers=shop["manager"]).json()
                      if k["local_id"] == bad_local)
    assert again_kept["attempts"] == 2 and again_kept["id"] == mine["id"]
    assert one(shop, "select count(*) from pos.sale where local_id = :l", l=bad_local) == 0


def test_a_sale_that_arrives_before_its_till_is_kept_and_accepted_when_resent(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    sale = fix_lines(shop, [op_sale(till)])[0]
    assert statuses(upload(client, shop, [sale])) == ["rejected"]
    rejection = next(k for k in client.get(f"{POS}/sync/rejections", headers=shop["manager"]).json()
                     if k["local_id"] == sale["local_id"])
    assert "till" in rejection["error"]
    assert statuses(upload(client, shop, [op_open(till), sale, op_close(till, "1116.00")])) == ["ok"] * 3
    assert sale["local_id"] not in {k["local_id"] for k in client.get(f"{POS}/sync/rejections", headers=shop["manager"]).json()}
    resolved = client.get(f"{POS}/sync/rejections", headers=shop["manager"], params={"include_resolved": True}).json()
    assert next(k for k in resolved if k["local_id"] == sale["local_id"])["resolved_at"]


def test_sale_numbers_are_validated_and_unique(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    upload(client, shop, [op_open(till)])
    good = fix_lines(shop, [op_sale(till, number="POS-HQ-OFF1-L900001")])[0]
    assert statuses(upload(client, shop, [good])) == ["ok"]
    clash = fix_lines(shop, [op_sale(till, number="POS-HQ-OFF1-L900001")])[0]                 # another sale, same number
    assert statuses(upload(client, shop, [clash])) == ["rejected"]
    for number in ("POS-HQ-OFF1-000123", "POS-HQ-D1-L000123", "x", "POS-HQ-OFF1-L12;--"):
        bad = fix_lines(shop, [op_sale(till, number=number)])[0]
        assert statuses(upload(client, shop, [bad])) == ["rejected"], number
    no_number = fix_lines(shop, [{**op_sale(till), "number": None}])[0]
    assert statuses(upload(client, shop, [no_number])) == ["ok"]
    assert one(shop, "select number from pos.sale where local_id = :l", l=no_number["local_id"]).startswith(
        "POS-HQ-OFF1-0")                                                      # the server numbered it


# --------------------------------------------------------------------------- accepted, but a manager is told
def kinds(client, shop) -> set[str]:  # type: ignore[no-untyped-def]
    return {i["kind"] for i in client.get("/api/v1/exceptions", headers=shop["owner"], params={"limit": 500}).json()}


def test_a_price_that_changed_while_offline_is_honoured_and_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    sale = op_sale(till, lines=[line(shop, "cement", "1", unit_price="100.00")],            # the old price
                   payments=[{"method": "cash", "amount": "100.00"}])
    assert statuses(upload(client, shop, [op_open(till), sale])) == ["ok", "ok"]
    row = client.get(f"{POS}/sales", headers=shop["manager"], params={"number": sale["number"]}).json()[0]
    detail = client.get(f"{POS}/sales/{row['id']}", headers=shop["manager"]).json()
    assert Dec(detail["total"]) == 100                                     # the customer paid the old price
    assert Dec(detail["lines"][0]["unit_price"]) == 100 and Dec(detail["lines"][0]["list_price"]) == 116
    assert "offline_price_changed" in kinds(client, shop)
    assert statuses(upload(client, shop, [sale])) == ["duplicate"]            # a resend answers, it does not redo
    upload(client, shop, [op_close(till, "1100.00")])


def test_stock_that_was_not_there_does_not_refuse_an_offline_sale(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    before = stock(shop)
    sale = op_sale(till, lines=[line(shop, "cement", "700", unit_price="116.00")],
                   payments=[{"method": "cash", "amount": "81200.00"}])
    assert statuses(upload(client, shop, [op_open(till), sale])) == ["ok", "ok"]
    assert stock(shop) == before - 700 and stock(shop) < 0
    assert any("negative" in k for k in kinds(client, shop))
    upload(client, shop, [op_close(till, "82200.00")])


def test_an_unauthorised_discount_offline_is_recorded_and_raised(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    sale = op_sale(till, lines=[line(shop, "cement", "1", unit_price="116.00", discount="16.00")],
                   payments=[{"method": "cash", "amount": "100.00"}])
    r = upload(client, shop, [op_open(till), sale])
    assert statuses(r) == ["ok", "ok"]
    assert any(w.startswith("unauthorised_override") for w in r.json()["results"][1]["warnings"])
    assert "offline_unauthorised_discount" in kinds(client, shop)
    upload(client, shop, [op_close(till, "1100.00")])


def test_an_mpesa_payment_without_a_code_is_accepted_and_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    sale = op_sale(till, payments=[{"method": "mobile_money", "amount": "116.00"}])
    sale["lines"] = [line(shop, "cement", "1", unit_price="116.00")]
    r = upload(client, shop, [op_open(till), sale])
    assert statuses(r) == ["ok", "ok"] and "mobile_money_without_code" in r.json()["results"][1]["warnings"]
    assert "offline_mobile_money_no_code" in kinds(client, shop)
    upload(client, shop, [op_close(till, "1000.00")])


def test_a_day_closed_while_the_device_was_offline_books_the_sale_today(client, shop) -> None:  # type: ignore[no-untyped-def]
    old = (datetime.now(UTC) - timedelta(days=3)).astimezone().date().isoformat()
    closed = client.post(f"{PAY}/closes", headers=shop["manager"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": old,
        "cash_banked": "0"})
    assert closed.status_code == 200, closed.text
    till = str(uuid4())
    sale = op_sale(till, at=(datetime.now(UTC) - timedelta(days=3)).isoformat())
    sale["lines"] = [line(shop, "cement", "1", unit_price="116.00")]
    r = upload(client, shop, [op_open(till, at=(datetime.now(UTC) - timedelta(days=3, hours=1)).isoformat()), sale])
    assert statuses(r) == ["ok", "ok"] and "closed_day" in r.json()["results"][1]["warnings"]
    booked = one(shop, "select business_date::text from pos.sale where local_id = :l", l=sale["local_id"])
    assert booked != old and "offline_closed_day" in kinds(client, shop)
    upload(client, shop, [op_close(till, "1116.00")])


def test_a_till_closed_by_a_manager_meanwhile_still_gets_the_sale(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    opened = upload(client, shop, [op_open(till)]).json()["results"][0]
    client.post(f"{POS}/tills/{opened['id']}/close", headers=shop["manager"], json={
        "counted_cash": "1000.00"})
    sale = op_sale(till)
    sale["lines"] = [line(shop, "cement", "1", unit_price="116.00")]
    r = upload(client, shop, [sale])
    assert statuses(r) == ["ok"] and "till_closed" in r.json()["results"][0]["warnings"]
    assert "offline_late_sale" in kinds(client, shop)


def test_closing_offline_with_a_variance_and_no_reason_is_accepted_and_raised(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    close = op_close(till, "990.00")
    r = upload(client, shop, [op_open(till), close])
    assert statuses(r) == ["ok", "ok"]
    server_till = next(t for t in client.get(f"{POS}/tills", headers=shop["manager"], params={"status": "closed"}).json()
                       if Dec(t["counted_cash"]) == Dec("990.00"))
    assert Dec(server_till["variance"]) == -10
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "till_variance"}).json()
    assert any("no reason" in i["message"] for i in items)
    assert statuses(upload(client, shop, [close])) == ["duplicate"]


def test_opening_a_second_till_for_a_device_is_kept_for_a_manager(client, shop) -> None:  # type: ignore[no-untyped-def]
    first, second = str(uuid4()), str(uuid4())
    assert statuses(upload(client, shop, [op_open(first)])) == ["ok"]
    r = upload(client, shop, [op_open(second)])
    assert statuses(r) == ["rejected"] and "already has an open till" in r.json()["results"][0]["error"]
    upload(client, shop, [op_close(first, "1000.00")])
    assert statuses(upload(client, shop, [op_open(second)])) == ["ok"]                       # fine once the first is closed
    upload(client, shop, [op_close(second, "1000.00")])


# --------------------------------------------------------------------------- who may sync
def test_the_device_and_the_person_must_both_be_allowed(client, shop) -> None:  # type: ignore[no-untyped-def]
    ops = fix_lines(shop, [op_open()])
    assert upload(client, shop, ops, key="").status_code == 403
    assert upload(client, shop, ops, key="zdk_wrong").status_code == 403
    juja = shop["user"]("jujacashier", "Cashier", shop["juja"])
    assert client.post(f"{POS}/sync/upload", headers={**juja, "X-Device-Key": shop["off_key"]},
                       json={"ops": ops}).status_code == 403                                 # not their branch's device
    assert client.post(f"{POS}/sync/upload", headers={**shop["storekeeper"], "X-Device-Key": shop["off_key"]},
                       json={"ops": ops}).status_code == 403                                 # not allowed to sell
    assert client.post(f"{POS}/sync/upload", headers={"X-Device-Key": shop["off_key"]}, json={"ops": ops}).status_code == 401
    client.patch(f"{POS}/devices/{shop['off_device']}/status", headers=shop["owner"], json={"status": "blocked"})
    assert upload(client, shop, ops).status_code == 403
    client.patch(f"{POS}/devices/{shop['off_device']}/status", headers=shop["owner"], json={"status": "active"})
    stolen = fix_lines(shop, [op_open(), op_sale(str(uuid4()))])
    other = upload(client, shop, stolen, who="cashier", key=shop["off_key"])
    assert other.status_code == 200                                                          # another cashier on this device
    assert statuses(other)[0] == "ok"                                                        # can open their own till there... 
    done = client.get(f"{POS}/tills", headers=shop["manager"], params={"status": "open"}).json()
    for t in done:
        if t["device_id"] == shop["off_device"]:
            client.post(f"{POS}/tills/{t['id']}/close", headers=shop["manager"], json={"counted_cash": t["opening_float"]})


def test_a_device_cannot_close_or_sell_on_someone_elses_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = str(uuid4())
    upload(client, shop, [op_open(till)])
    foreign = fix_lines(shop, [op_sale(till)])[0]
    r = upload(client, shop, [foreign], who="cashier")                                       # a different cashier
    assert statuses(r) == ["rejected"] and "another cashier" in r.json()["results"][0]["error"]
    upload(client, shop, [op_close(till, "1000.00")])


def test_batches_are_limited(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert upload(client, shop, [op_open() for _ in range(201)]).status_code == 422
    assert upload(client, shop, [{"type": "unknown", "local_id": str(uuid4()), "at": hours_ago(1)}]).status_code == 422
    assert upload(client, shop, [{"type": "sale", "local_id": "not-a-uuid", "at": hours_ago(1)}]).status_code == 422
    assert statuses(upload(client, shop, [])) == []
