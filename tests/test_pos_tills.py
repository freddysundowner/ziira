"""Devices, till sessions, the X and Z reports, closing with a variance, and the books and daily close around them."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import PAY, one
from tests.pos_helpers import POS, line, make_pos_shop, open_till, sell
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_pos_shop(client, registry, "Pos Till Co", finance=True)


def new_cashier(client, shop, name: str):  # type: ignore[no-untyped-def]
    """A cashier with a device of their own (so tills can be opened and closed freely)."""
    who = shop["user"](name, "Cashier", shop["branch_id"])
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": name[:8].upper(), "name": name, "location_id": shop["main"]})
    assert dev.status_code == 201, dev.text
    shop[name] = who
    shop["devices"][name] = dev.json()["id"]
    return who


# --------------------------------------------------------------------------- devices
def test_registering_devices(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, branch = shop["owner"], str(shop["branch_id"])
    body = {"branch_id": branch, "code": "TAB1", "name": "Tablet", "location_id": shop["main"]}
    made = client.post(f"{POS}/devices", headers=owner, json=body)
    assert made.status_code == 201 and made.json()["key"].startswith("zdk_") and made.json()["status"] == "active"
    assert "key" not in client.get(f"{POS}/devices", headers=owner).json()[0]
    assert "device_key_hash" not in made.text
    assert client.post(f"{POS}/devices", headers=owner, json=body).status_code == 409                 # same code
    for bad in ({"code": "bad code!"}, {"code": ""}, {"code": "TOOLONGCODE"}, {"name": " "},
                {"branch_id": str(uuid4())}, {"location_id": shop["juja_store"]}, {"location_id": str(uuid4())}):
        assert client.post(f"{POS}/devices", headers=owner, json={**body, "code": "OK1", **bad}).status_code == 422, bad
    assert client.post(f"{POS}/devices", headers=shop["cashier"], json={**body, "code": "NO1"}).status_code == 403
    assert client.post(f"{POS}/devices", headers=shop["manager"], json={**body, "code": "MGR1"}).status_code == 201
    listed = client.get(f"{POS}/devices", headers=shop["cashier"]).json()                 # a cashier sees the devices
    assert {d["code"] for d in listed} >= {"D1", "TAB1"}
    juja = shop["user"]("jujacashier", "Cashier", shop["juja"])
    assert client.get(f"{POS}/devices", headers=juja).json() == []


def test_blocking_and_rotating_a_devices_key(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    dev = client.post(f"{POS}/devices", headers=owner, json={
        "branch_id": str(shop["branch_id"]), "code": "LOST", "name": "Lost phone"}).json()
    snap = lambda key: client.get(f"{POS}/sync/snapshot", headers={**shop["cashier"], "X-Device-Key": key})  # noqa: E731
    assert snap(dev["key"]).status_code == 200
    assert client.patch(f"{POS}/devices/{dev['id']}/status", headers=shop["cashier"],
                        json={"status": "blocked"}).status_code == 403
    assert client.patch(f"{POS}/devices/{dev['id']}/status", headers=owner, json={"status": "bad"}).status_code == 422
    assert client.patch(f"{POS}/devices/{dev['id']}/status", headers=owner, json={"status": "blocked"}).status_code == 200
    assert snap(dev["key"]).status_code == 403
    client.patch(f"{POS}/devices/{dev['id']}/status", headers=owner, json={"status": "active"})
    rotated = client.post(f"{POS}/devices/{dev['id']}/rotate-key", headers=owner).json()
    assert rotated["key"] != dev["key"] and snap(rotated["key"]).status_code == 200 and snap(dev["key"]).status_code == 403
    assert client.post(f"{POS}/devices/{uuid4()}/rotate-key", headers=owner).status_code == 404
    assert snap("").status_code == 403 and snap("not-a-key").status_code == 403


# --------------------------------------------------------------------------- opening
def test_opening_a_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    lena = new_cashier(client, shop, "lena")
    assert open_till(client, shop, "lena", float_="-1").status_code == 422
    assert open_till(client, shop, "lena", float_="10.005").status_code == 422
    assert open_till(client, shop, "lena", float_="2000000").status_code == 422
    assert client.post(f"{POS}/tills", headers=lena, json={"device_id": str(uuid4()), "opening_float": "0"}
                       ).status_code == 404
    local = str(uuid4())
    first = open_till(client, shop, "lena", float_="500.00", local_id=local)
    assert first.status_code == 201 and Dec(first.json()["opening_float"]) == 500 and first.json()["status"] == "open"
    again = open_till(client, shop, "lena", float_="500.00", local_id=local)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]            # a retry
    resumed = open_till(client, shop, "lena")                                                # a fresh browser: carry on
    assert resumed.status_code == 200 and resumed.json()["id"] == first.json()["id"]
    other_device = open_till(client, shop, "lena", device=shop["device"])                    # one open till each
    assert other_device.status_code == 409 and "already have an open till on" in other_device.text
    mara = new_cashier(client, shop, "mara")
    taken = open_till(client, shop, "mara", device=shop["devices"]["lena"])                  # one per device
    assert taken.status_code == 409 and "opened by lena" in taken.text                       # and who has it is said
    assert open_till(client, shop, "mara").status_code == 201 and mara
    assert open_till(client, shop, "storekeeper", device=shop["device"]).status_code == 403
    one_open = one(shop, "select count(*) from pos.till_session where status = 'open' and cashier_id = "
                         "(select cashier_id from pos.till_session where id = :i)", i=first.json()["id"])
    assert one_open == 1


def test_simultaneous_openings_leave_one_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "nora")
    results = together([lambda: open_till(client, shop, "nora") for _ in range(6)])
    assert sorted(r.status_code for r in results) == [200] * 5 + [201]            # one till; the rest carry on with it
    assert len({r.json()["id"] for r in results}) == 1


def test_who_sees_which_tills(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "otto")
    mine = open_till(client, shop, "otto").json()
    ids = lambda who: {t["id"] for t in client.get(f"{POS}/tills", headers=shop[who]).json()}  # noqa: E731
    assert mine["id"] in ids("otto") and mine["id"] in ids("manager") and mine["id"] in ids("owner")
    assert mine["id"] not in ids("cashier")                                    # another cashier's till is not theirs
    assert client.get(f"{POS}/tills/{mine['id']}", headers=shop["cashier"]).status_code == 404
    assert client.get(f"{POS}/tills/{mine['id']}", headers=shop["manager"]).status_code == 200
    assert client.get(f"{POS}/tills", headers=shop["storekeeper"]).status_code == 403
    assert client.get(f"{POS}/tills", headers=shop["owner"], params={"status": "open", "limit": 0}).status_code == 422


# --------------------------------------------------------------------------- reports and closing
def test_the_x_and_z_reports(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "piet")
    till = open_till(client, shop, "piet", float_="1000.00").json()["id"]
    sell(client, shop, who="piet", till=till, lines=[line(shop, "cement", "2")],
         payments=[{"method": "cash", "amount": "300.00"}])                                    # 232 cash
    sell(client, shop, who="piet", till=till, payments=[{"method": "mobile_money", "amount": "116", "external_ref": "XRPT1"}])
    voided = sell(client, shop, who="piet", till=till).json()
    assert client.post(f"{POS}/sales/{voided['id']}/void", headers=shop["manager"],
                       json={"reason_code_id": shop["reasons"]["void"]}).status_code == 200
    x = client.get(f"{POS}/tills/{till}/report", headers=shop["piet"]).json()
    assert x["status"] == "open" and x["sales_count"] == 2 and Dec(x["sales_total"]) == 348
    assert x["voided_count"] == 1 and Dec(x["voided_total"]) == 116 and Dec(x["tax_total"]) == 48
    assert {k: Dec(v) for k, v in x["takings_by_method"].items()} == {"cash": Dec(232), "mobile_money": Dec(116)}
    assert Dec(x["expected_cash"]) == 1232 and x["counted_cash"] is None
    # the drawer holds exactly the expected cash: no variance, no reason needed
    z = client.post(f"{POS}/tills/{till}/close", headers=shop["piet"], json={"counted_cash": "1232.00"})
    assert z.status_code == 200, z.text
    assert z.json()["status"] == "closed" and Dec(z.json()["variance"]) == 0
    assert client.post(f"{POS}/tills/{till}/close", headers=shop["piet"], json={"counted_cash": "1.00"}).status_code == 409
    stored = one(shop, "select report->>'sales_count' from pos.till_session where id = :i", i=till)
    assert stored == "2"                                                       # the Z report is kept as it was
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'till.closed' and "
                     "aggregate_id = :i", i=till) == 1


def test_a_short_till_needs_a_reason_is_flagged_and_posts_to_the_books(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "quin")
    till = open_till(client, shop, "quin", float_="1000.00").json()["id"]
    sell(client, shop, who="quin", till=till)                                              # expected cash 1116
    before = balance(shop, "6500")
    path = f"{POS}/tills/{till}/close"
    assert client.post(path, headers=shop["quin"], json={"counted_cash": "1096.00"}).status_code == 422   # no reason
    wrong = client.post(path, headers=shop["quin"], json={"counted_cash": "1096.00",
                                                           "reason_code_id": shop["reasons"]["void"]})
    assert wrong.status_code == 422                                                         # reason from the wrong list
    for bad in ("-1", "10.005", "100000001"):
        assert client.post(path, headers=shop["quin"], json={"counted_cash": bad}).status_code == 422
    assert client.post(path, headers=shop["cashier"], json={"counted_cash": "1096"}).status_code in (403, 404)
    r = client.post(path, headers=shop["quin"], json={
        "counted_cash": "1096.00", "reason_code_id": shop["reasons"]["till_variance"], "note": "Gave wrong change"})
    assert r.status_code == 200 and Dec(r.json()["variance"]) == -20
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "till_variance"}).json()
    assert any(i["ref_id"] == till for i in items)
    assert balance(shop, "6500") == before + 20                                             # the loss is in the books


def test_an_overage_and_a_managers_close(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "rosa")
    till = open_till(client, shop, "rosa", float_="500.00").json()["id"]
    before = balance(shop, "6500")
    r = client.post(f"{POS}/tills/{till}/close", headers=shop["manager"], json={
        "counted_cash": "530.00", "reason_code_id": shop["reasons"]["till_variance"]})
    assert r.status_code == 200 and Dec(r.json()["variance"]) == 30                          # a reviewer may close it
    assert balance(shop, "6500") == before - 30


# --------------------------------------------------------------------------- the books and the daily close
def test_sales_reach_the_books_and_a_void_reverses_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "sven")
    till = open_till(client, shop, "sven").json()["id"]
    codes = ("1010", "1030", "4000", "4100", "2200", "5000", "1200")
    before = {c: balance(shop, c) for c in codes}
    sale = sell(client, shop, who="sven", till=till, lines=[line(shop, "cement", "2")],
                payments=[{"method": "cash", "amount": "100"}, {"method": "mobile_money", "amount": "132", "external_ref": "BKS1"}]
                ).json()
    after = {c: balance(shop, c) for c in codes}
    assert after["1010"] - before["1010"] == 100 and after["1030"] - before["1030"] == 132
    assert after["4000"] - before["4000"] == -200 and after["2200"] - before["2200"] == -32
    assert after["5000"] - before["5000"] == 100 and after["1200"] - before["1200"] == -100        # 2 x cost 50
    voided = client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"],
                         json={"reason_code_id": shop["reasons"]["void"]})
    assert voided.status_code == 200, voided.text
    back = {c: balance(shop, c) for c in codes}
    assert back["1010"] == before["1010"] and back["1030"] == before["1030"] and back["1200"] == before["1200"]
    assert back["5000"] == before["5000"] and back["2200"] == before["2200"]
    assert back["4000"] + back["4100"] == before["4000"] + before["4100"]                    # revenue nets to nothing
    client.post(f"{POS}/tills/{till}/close", headers=shop["sven"], json={"counted_cash": "1000"})


def test_a_day_cannot_close_while_a_till_is_open_and_then_locks_the_sales(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_cashier(client, shop, "tess")
    till = open_till(client, shop, "tess").json()
    day = till["business_date"]
    blocked = client.post(f"{PAY}/closes", headers=shop["manager"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": day,
        "cash_banked": "0", "explanation": "x"})
    assert blocked.status_code == 422 and "till session" in blocked.json()["message"]
    sale = sell(client, shop, who="tess", till=till["id"]).json()
    client.post(f"{POS}/tills/{till['id']}/close", headers=shop["tess"], json={"counted_cash": "1116.00"})
    # other tills opened in the test module are still open: close them so the day can close
    for open_one in client.get(f"{POS}/tills", headers=shop["owner"], params={"status": "open"}).json():
        client.post(f"{POS}/tills/{open_one['id']}/close", headers=shop["owner"], json={
            "counted_cash": open_one["opening_float"], "reason_code_id": shop["reasons"]["till_variance"]})
    preview = client.get(f"{PAY}/closes/preview", headers=shop["manager"], params={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": day}).json()
    assert not any("till session" in p for p in preview["problems"]), preview
    done = client.post(f"{PAY}/closes", headers=shop["manager"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": day,
        "cash_banked": "0", "explanation": "Counted in the safe"})
    assert done.status_code == 200, done.text
    assert done.json()["close"]["status"] == "locked"
    again = open_till(client, shop, "tess")                                                  # today is closed now
    assert again.status_code == 422 and "closed" in again.json()["message"]
    reason = {"reason_code_id": shop["reasons"]["void"]}
    late = client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"], json=reason)
    assert late.status_code == 422                                                           # its till is closed anyway
