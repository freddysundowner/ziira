"""The business date follows the company's own time zone (setting `timezone`), never a country's.

The same instant is a different calendar day in different places: 22:00 UTC on 14 October is already the 15th in Nairobi
and Auckland and still the 14th in UTC and Los Angeles. Every record that takes its date from the clock (a stock
movement, a till, a journal entry, a supplier receipt, a price) must show the day where the company is. The zones used
here are fixtures: nothing in the platform treats any of them specially.
"""

from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import entries, publish_sale
from tests.pos_helpers import POS, make_pos_shop, open_till
from tests.purchasing_helpers import approved_order, make_purchasing_shop, receive
from tests.stock_helpers import INV, P, system
from ziira.kernel import clock

LATE_14TH = "2026-10-14T22:00:00+00:00"          # 15 Oct in Nairobi (+3) and Auckland (+13), 14 Oct in UTC and Los Angeles (-7)
NOON_14TH = "2026-10-14T12:00:00+00:00"          # 01:00 on the 15th in Auckland, still the 14th everywhere else here
EARLY_15TH = "2026-10-15T05:00:00+00:00"         # 22:00 on the 14th in Los Angeles, the 15th everywhere else here
UTC_Z, NAIROBI, AUCKLAND, LOS_ANGELES = "UTC", "Africa/Nairobi", "Pacific/Auckland", "America/Los_Angeles"

# (zone, the instant, the company's calendar date at that instant)
CASES = [
    (UTC_Z, LATE_14TH, date(2026, 10, 14)),
    (NAIROBI, LATE_14TH, date(2026, 10, 15)),
    (AUCKLAND, LATE_14TH, date(2026, 10, 15)),
    (AUCKLAND, NOON_14TH, date(2026, 10, 15)),
    (LOS_ANGELES, LATE_14TH, date(2026, 10, 14)),
    (LOS_ANGELES, EARLY_15TH, date(2026, 10, 14)),
    (UTC_Z, EARLY_15TH, date(2026, 10, 15)),
]
IDS = [f"{zone}@{instant[5:13]}" for zone, instant, _ in CASES]


@pytest.fixture
def at(monkeypatch):  # type: ignore[no-untyped-def]
    """Freeze the clock the business date is read from at an instant."""
    def freeze(instant: str) -> None:
        fixed = datetime.fromisoformat(instant)

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[no-untyped-def]
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        monkeypatch.setattr(clock, "datetime", Frozen)

    return freeze


def set_zone(client, shop, zone: str) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"], json={"timezone": zone})
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_pos_shop(client, registry, "Zone Shop", finance=True, stock="0")


@pytest.fixture(scope="module")
def buyer(client, registry):  # type: ignore[no-untyped-def]
    return make_purchasing_shop(client, registry, "Zone Buyer")


def test_the_helpers_read_the_company_zone(client, shop, at) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import company_date_of, company_today

    for zone, instant, expected in CASES:
        set_zone(client, shop, zone)
        at(instant)
        with system(shop) as s:
            assert company_today(s, shop["company_id"]) == expected, (zone, instant)
            assert company_date_of(s, shop["company_id"], datetime.fromisoformat(instant)) == expected
    set_zone(client, shop, NAIROBI)
    with system(shop) as s:                                  # a naive moment is read as UTC
        assert company_date_of(s, shop["company_id"], datetime(2026, 10, 14, 22, 0)) == date(2026, 10, 15)


def test_a_company_in_utc_differs_from_nairobi_at_22_utc(client, shop, at) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import company_today

    at(LATE_14TH)
    days = {}
    for zone in (UTC_Z, NAIROBI):
        set_zone(client, shop, zone)
        with system(shop) as s:
            days[zone] = company_today(s, shop["company_id"])
    assert days == {UTC_Z: date(2026, 10, 14), NAIROBI: date(2026, 10, 15)}


def test_a_new_company_with_no_zone_is_in_utc(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import company_settings

    other = uuid4()
    with system(shop) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name, base_currency) values (:i, :t, 'Bare', 'USD')"),
                  {"i": str(other), "t": str(shop["tenant_id"])})
        assert company_settings.get_setting(s, other, "timezone") == "UTC"


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_a_stock_movement_belongs_to_the_company_day(client, shop, at, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, shop, zone)
    at(instant)
    product = client.post(f"{P}/products", headers=shop["owner"], json={      # opening stock is once per product
        "company_id": str(shop["company_id"]), "sku": f"Z{uuid4().hex[:8]}", "name": "Zone product",
        "base_uom_id": shop["uom"], "tax_code_id": shop["tax"]})
    assert product.status_code == 201, product.text
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": product.json()["id"], "quantity": "1", "unit_cost": "10"}]})
    assert r.status_code == 201, r.text
    with system(shop) as s:
        day = s.execute(text("select business_date from inventory.stock_movement where id = :i"),
                        {"i": r.json()[0]["id"]}).scalar_one()
    assert day == expected


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_a_journal_entry_is_dated_in_the_company_zone(client, shop, at, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, shop, zone)
    at(instant)
    sale_id = publish_sale(shop)                          # a sale event that names no date
    found = entries(shop, source_id=sale_id)
    assert found and all(e[3] == expected for e in found)


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_a_price_starts_on_the_company_day(client, shop, at, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, shop, zone)
    at(instant)
    lst = client.post(f"{P}/price-lists", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": f"List {uuid4().hex[:6]}"})
    assert lst.status_code == 201, lst.text
    r = client.put(f"{P}/price-lists/{lst.json()['id']}/prices", headers=shop["owner"], json={
        "product_id": shop["cement"], "price": "120.00"})
    assert r.status_code == 200, r.text
    assert date.fromisoformat(r.json()["valid_from"]) == expected


@pytest.mark.parametrize(("zone", "instant", "expected"), [c for c in CASES if c[0] != NAIROBI][::2],
                         ids=lambda v: str(v)[:16])
def test_a_till_opens_on_the_company_day(client, shop, at, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, shop, zone)
    at(instant)
    who = ("manager", "boss", "cashier", "manager")[[c for c in CASES if c[0] != NAIROBI][::2].index((zone, instant, expected))]
    till = open_till(client, shop, who=who)
    assert till.status_code == 201, till.text
    assert date.fromisoformat(till.json()["business_date"]) == expected
    closed = client.post(f"{POS}/tills/{till.json()['id']}/close", headers=shop[who], json={"counted_cash": "1000.00"})
    assert closed.status_code == 200, closed.text


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_an_offline_sale_moment_is_read_in_the_company_zone(client, shop, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.pos.services import tills

    set_zone(client, shop, zone)
    with system(shop) as s:
        assert tills.business_day(s, shop["company_id"], datetime.fromisoformat(instant)) == expected


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_a_supplier_receipt_is_dated_in_the_company_zone(client, buyer, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, buyer, zone)
    order = approved_order(client, buyer, qty="1")
    r = receive(client, buyer, order, received_at=instant)
    assert r.status_code == 201, r.text
    with system(buyer) as s:
        days = {row.business_date for row in s.execute(text(
            "select business_date from inventory.stock_movement where source_id = :i"), {"i": r.json()["id"]})}
    assert days == {expected}


@pytest.mark.parametrize(("zone", "instant", "expected"), CASES, ids=IDS)
def test_a_return_to_the_supplier_is_dated_in_the_company_zone(client, buyer, zone, instant, expected) -> None:  # type: ignore[no-untyped-def]
    set_zone(client, buyer, zone)
    order = approved_order(client, buyer, qty="2")
    receipt = receive(client, buyer, order, received_at="2026-10-01T09:00:00+00:00")
    assert receipt.status_code == 201, receipt.text
    r = client.post(f"/api/v1/purchasing/receipts/{receipt.json()['id']}/returns", headers=buyer["owner"], json={
        "lines": [{"receipt_line_id": receipt.json()["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": buyer["reasons"]["purchase_return"], "returned_at": instant})
    assert r.status_code == 201, r.text
    with system(buyer) as s:
        days = {row.business_date for row in s.execute(text(
            "select business_date from inventory.stock_movement where source_id = :i"), {"i": r.json()["id"]})}
    assert days == {expected}
