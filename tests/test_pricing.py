"""Price lists: dated prices that keep their history, branch lists that beat the company's, and who may change them."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import UUID, uuid4

import pytest

from tests.payments_helpers import one
from tests.stock_helpers import P, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Pricing Co")


def make_list(client, shop, name="Retail", **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{P}/price-lists", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": name, **kw})


def set_price(client, shop, lst, price, product=None, valid_from=None, who="owner"):  # type: ignore[no-untyped-def]
    return client.put(f"{P}/price-lists/{lst}/prices", headers=shop[who], json={
        "product_id": product or shop["cement"], "price": price, **({"valid_from": valid_from} if valid_from else {})})


def prices_on(shop, branch, day: date, *products):  # type: ignore[no-untyped-def]
    from ziira.modules.products.public import selling_prices

    with system(shop) as s:
        return selling_prices(s, shop["company_id"], branch, {UUID(str(p)) for p in products}, day)


def test_lists_are_created_validated_and_unique_by_default(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert make_list(client, shop, is_default=True).status_code == 201
    assert make_list(client, shop, "Another default", is_default=True).status_code == 409
    assert make_list(client, shop, "Wholesale").status_code == 201                       # non-default lists are free
    assert make_list(client, shop, " ").status_code == 422
    assert make_list(client, shop, branch_id=str(uuid4())).status_code == 422
    juja = make_list(client, shop, "Juja prices", branch_id=str(shop["juja"]), is_default=True)
    assert juja.status_code == 201                                                       # one default per branch too
    assert make_list(client, shop, "Juja again", branch_id=str(shop["juja"]), is_default=True).status_code == 409
    assert {x["name"] for x in client.get(f"{P}/price-lists", headers=shop["owner"]).json()} >= {"Retail", "Juja prices"}


def test_a_new_price_ends_the_one_before_and_history_answers_any_day(client, shop) -> None:  # type: ignore[no-untyped-def]
    lst = next(x["id"] for x in client.get(f"{P}/price-lists", headers=shop["owner"]).json() if x["name"] == "Retail")
    assert set_price(client, shop, lst, "100.00", valid_from="2026-01-01").status_code == 200
    assert set_price(client, shop, lst, "120.00", valid_from="2026-06-01").status_code == 200
    assert set_price(client, shop, lst, "140.00", valid_from="2026-09-01").status_code == 200
    day = lambda d: prices_on(shop, shop["branch_id"], date.fromisoformat(d), shop["cement"]).get(  # noqa: E731
        UUID(shop["cement"]))
    assert day("2025-12-31") is None and day("2026-01-01") == 100 and day("2026-05-31") == 100
    assert day("2026-06-01") == 120 and day("2026-08-31") == 120 and day("2026-09-01") == 140
    history = client.get(f"{P}/price-lists/{lst}/prices", headers=shop["owner"], params={"product_id": shop["cement"]}).json()
    assert [(h["valid_from"], h["valid_to"]) for h in history] == [
        ("2026-09-01", None), ("2026-06-01", "2026-08-31"), ("2026-01-01", "2026-05-31")]
    assert set_price(client, shop, lst, "150.00", valid_from="2026-09-01").status_code == 409     # not before the latest
    assert set_price(client, shop, lst, "150.00", valid_from="2026-03-01").status_code == 409
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'price.changed'") >= 3


def test_prices_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    lst = next(x["id"] for x in client.get(f"{P}/price-lists", headers=shop["owner"]).json() if x["name"] == "Wholesale")
    for bad in ("-1", "10.005", "100000001", "abc"):
        assert set_price(client, shop, lst, bad).status_code == 422, bad
    assert set_price(client, shop, lst, "0.00").status_code == 200                     # a free item is allowed
    assert set_price(client, shop, lst, "5.00", product=str(uuid4()), valid_from="2026-02-01").status_code == 422
    assert set_price(client, shop, str(uuid4()), "5.00").status_code == 404
    assert client.get(f"{P}/price-lists/{uuid4()}/prices", headers=shop["owner"]).status_code == 404


def test_a_branch_list_beats_the_company_list_for_that_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    lists = {x["name"]: x["id"] for x in client.get(f"{P}/price-lists", headers=shop["owner"]).json()}
    set_price(client, shop, lists["Juja prices"], "130.00", valid_from="2026-01-01")
    at = date(2026, 7, 1)
    cement = UUID(shop["cement"])
    paint = UUID(shop["paint"])
    set_price(client, shop, lists["Retail"], "300.00", product=shop["paint"], valid_from="2026-01-01")
    juja = prices_on(shop, shop["juja"], at, cement, paint)
    hq = prices_on(shop, shop["branch_id"], at, cement, paint)
    assert juja[cement] == Dec("130.00") and juja[paint] == Dec("300.00")             # falls back for what it lacks
    assert hq[cement] == Dec("120.00") and hq[paint] == Dec("300.00")


def test_who_may_change_prices(client, shop) -> None:  # type: ignore[no-untyped-def]
    lst = next(x["id"] for x in client.get(f"{P}/price-lists", headers=shop["owner"]).json() if x["name"] == "Retail")
    for who in ("cashier", "storekeeper", "manager"):
        assert make_list(client, {**shop, "owner": shop[who]}, f"By {who}").status_code == 403
        assert set_price(client, shop, lst, "1.00", who=who).status_code == 403
    assert client.get(f"{P}/price-lists", headers=shop["cashier"]).status_code == 200      # everyone selling can read
    fm = shop["user"]("fmprice", "Finance Manager", None)
    assert make_list(client, {**shop, "owner": fm}, "Finance list").status_code == 201
    juja_fm = shop["user"]("jujafm", "Finance Manager", shop["juja"])
    assert make_list(client, {**shop, "owner": juja_fm}, "Not mine").status_code == 403    # another branch's scope only
