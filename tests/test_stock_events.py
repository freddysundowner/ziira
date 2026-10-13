"""Stock changes from other units' events (a sale, a return, goods received), using fake events:
POS and Purchasing do not exist yet, so the tests publish what they will publish."""

from datetime import date
from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system
from ziira.sdk import Conflict, Event, ValidationFailed


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Event Co")
    co = str(s["company_id"])
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": co, "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"},
                  {"product_id": s["paint"], "quantity": "6", "unit_cost": "50", "batch_no": "LATE",
                   "expiry_date": "2027-09-01"},
                  {"product_id": s["paint"], "quantity": "4", "unit_cost": "50", "batch_no": "EARLY",
                   "expiry_date": "2027-03-01"}]})
    assert r.status_code == 201, r.text
    with system(s) as db:
        s["batches"] = {r.batch_no: str(r.id) for r in db.execute(text("select id, batch_no from inventory.batch"))}
    return s


def publish_event(shop, event_type: str, aggregate: str, **payload) -> UUID:  # type: ignore[no-untyped-def]
    """Publish an event in one transaction, as the publishing unit would."""
    from ziira.sdk import publish

    aggregate_id = uuid4()
    with system(shop) as s:
        publish(s, Event(event_type, aggregate, aggregate_id, {"company_id": shop["company_id"], **payload}))
    return aggregate_id


def sale(shop, lines, **extra) -> UUID:  # type: ignore[no-untyped-def]
    return publish_event(shop, "sale.posted", "pos.sale", location_id=shop["main"], business_date="2026-10-13",
                         lines=lines, **extra)


def sale_line(shop, product: str, quantity: str, **extra):  # type: ignore[no-untyped-def]
    return {"line_id": uuid4(), "product_id": shop[product], "quantity": quantity, **extra}


def stock(shop, product: str = "cement") -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p"),
                         {"p": shop[product]}).scalar_one()


def movements(shop, source_id):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select movement_type, quantity, unit_cost, value, business_date, batch_id "
                              "from inventory.stock_movement where source_id = :i order by seq"),
                         {"i": str(source_id)}).all()


# --------------------------------------------------------------------------- sales
def test_a_sale_takes_stock_out_and_ignores_services(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.public import posted_cost

    lines = [sale_line(shop, "cement", "5"), sale_line(shop, "delivery", "1")]
    sale_id = sale(shop, lines)
    assert stock(shop) == 95
    moved = movements(shop, sale_id)
    assert [(m.movement_type, m.quantity, m.unit_cost, m.value, m.business_date) for m in moved] == [
        ("sale", -5, 100, -500, date(2026, 10, 13))]
    with system(shop) as s:
        assert posted_cost(s, "sale", sale_id) == {lines[0]["line_id"]: Dec("500")}     # POS reads its cost of sales


def test_the_same_sale_cannot_post_twice(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import publish

    lines = [sale_line(shop, "cement", "1")]
    sale_id = sale(shop, lines)
    with pytest.raises(Conflict, match="already posted"), system(shop) as s:
        publish(s, Event("sale.posted", "pos.sale", sale_id, {
            "company_id": shop["company_id"], "location_id": shop["main"], "lines": lines}))
    assert stock(shop) == 94


def test_a_sale_without_enough_stock_fails_as_a_whole(shop) -> None:  # type: ignore[no-untyped-def]
    before = stock(shop)
    with pytest.raises(ValidationFailed, match="Not enough stock"):
        sale(shop, [sale_line(shop, "cement", "2"), sale_line(shop, "paint", "50")])
    assert stock(shop) == before                                   # the first line was rolled back too


def test_batch_tracked_sales_use_first_expiry_first_out_unless_a_batch_is_chosen(shop) -> None:  # type: ignore[no-untyped-def]
    sale_id = sale(shop, [sale_line(shop, "paint", "5")])
    assert sorted(m.quantity for m in movements(shop, sale_id)) == [-4, -1]               # EARLY (4) first, then LATE
    chosen = sale(shop, [sale_line(shop, "paint", "1", batch_id=shop["batches"]["LATE"])])
    assert [str(m.batch_id) for m in movements(shop, chosen)] == [shop["batches"]["LATE"]]


def test_offline_sales_are_always_accepted_and_raise_an_exception(shop) -> None:  # type: ignore[no-untyped-def]
    def count() -> int:
        with system(shop) as s:
            return s.execute(text("select count(*) from kernel.event_outbox where event_type = 'stock.negative'")
                             ).scalar_one()

    before = count()
    on_hand = stock(shop)
    sale(shop, [sale_line(shop, "cement", str(on_hand + 3))], offline=True)
    assert stock(shop) == -3 and count() == before + 1


def test_the_company_policy_can_allow_negative_stock_for_online_sales(client, shop) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed):
        sale(shop, [sale_line(shop, "cement", "1")])                # stock is at -3, policy says no
    client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                 json={"negative_stock_allowed": True})
    sale(shop, [sale_line(shop, "cement", "1")])
    assert stock(shop) == -4
    client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                 json={"negative_stock_allowed": False})
    # put the stock back for the tests below
    publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                  lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "104", "unit_cost": "100"}])
    assert stock(shop) == 100


def test_the_location_can_be_the_branchs_only_store(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale_id = publish_event(shop, "sale.posted", "pos.sale", branch_id=shop["branch_id"],
                            lines=[sale_line(shop, "cement", "1")])
    with system(shop) as s:
        code = s.execute(text("select l.code from inventory.stock_movement m join inventory.location l "
                              "on l.id = m.location_id where m.source_id = :i"), {"i": str(sale_id)}).scalar_one()
    assert code == "MAIN"
    client.post(f"{INV}/locations", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "code": "BACK", "name": "Back"})
    with pytest.raises(ValidationFailed, match="no single store"):
        publish_event(shop, "sale.posted", "pos.sale", branch_id=shop["branch_id"],
                      lines=[sale_line(shop, "cement", "1")])


def test_bad_payloads_are_refused_clearly(shop) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed, match="no lines"):
        sale(shop, [])
    with pytest.raises(ValidationFailed, match="positive"):
        sale(shop, [sale_line(shop, "cement", "-1")])
    with pytest.raises(ValidationFailed, match="not a number"):
        sale(shop, [sale_line(shop, "cement", "lots")])
    with pytest.raises(ValidationFailed, match="not a valid id"):
        sale(shop, [{"line_id": uuid4(), "product_id": "nope", "quantity": "1"}])
    with pytest.raises(ValidationFailed, match="product not found"):
        sale(shop, [{"line_id": uuid4(), "product_id": uuid4(), "quantity": "1"}])
    with pytest.raises(ValidationFailed, match="location_id is required"):
        publish_event(shop, "sale.posted", "pos.sale", lines=[sale_line(shop, "cement", "1")])


# --------------------------------------------------------------------------- returns
def test_a_return_comes_back_at_the_cost_the_sale_took_it_out_at(shop) -> None:  # type: ignore[no-untyped-def]
    line = sale_line(shop, "cement", "10")
    sale_id = sale(shop, [line])                                                    # at the average cost: 100
    publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                  lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "90", "unit_cost": "200"}])
    returned = publish_event(shop, "sale.returned", "pos.sale_return", location_id=shop["main"], sale_id=sale_id,
                             lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "4",
                                     "sale_line_id": line["line_id"]}])
    assert [(m.movement_type, m.quantity, m.unit_cost, m.value) for m in movements(shop, returned)] == [
        ("sale_return", 4, 100, 400)]


def test_a_batch_tracked_return_goes_back_to_the_batch_it_came_from(shop) -> None:  # type: ignore[no-untyped-def]
    line = sale_line(shop, "paint", "1", batch_id=shop["batches"]["LATE"])
    sale_id = sale(shop, [line])
    returned = publish_event(shop, "sale.returned", "pos.sale_return", location_id=shop["main"], sale_id=sale_id,
                             lines=[{"line_id": uuid4(), "product_id": shop["paint"], "quantity": "1",
                                     "sale_line_id": line["line_id"]}])
    assert [str(m.batch_id) for m in movements(shop, returned)] == [shop["batches"]["LATE"]]


# --------------------------------------------------------------------------- goods received
def test_goods_received_average_into_the_cost(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        before = s.execute(text("select quantity, value from inventory.product_cost where product_id = :p"),
                           {"p": shop["cement"]}).one()
    receipt = publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                            lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "10",
                                    "unit_cost": "300"}])
    with system(shop) as s:
        after = s.execute(text("select quantity, value, average_cost from inventory.product_cost "
                               "where product_id = :p"), {"p": shop["cement"]}).one()
    assert after.quantity == before.quantity + 10 and after.value == before.value + 3000
    assert after.average_cost == (after.value / after.quantity).quantize(Dec("0.000001"))
    assert [m.movement_type for m in movements(shop, receipt)] == ["receipt"]


def test_landed_cost_is_spread_over_the_lines(shop) -> None:  # type: ignore[no-untyped-def]
    receipt = publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"], landed_cost="200",
                            lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "10",
                                    "unit_cost": "100"},
                                   {"line_id": uuid4(), "product_id": shop["paint"], "quantity": "5",
                                    "unit_cost": "200", "batch_no": "NEW", "expiry_date": "2028-01-01"}])
    by_cost = sorted((m.unit_cost, m.quantity) for m in movements(shop, receipt))
    assert by_cost == [(110, 10), (220, 5)]                       # 200 shared equally: each line is worth 1,000


def test_a_batch_tracked_receipt_creates_the_batch(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        batch = s.execute(text("select expiry_date from inventory.batch where batch_no = 'NEW'")).scalar_one()
    assert batch == date(2028, 1, 1)
    with pytest.raises(ValidationFailed, match="batch-tracked"):
        publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                      lines=[{"line_id": uuid4(), "product_id": shop["paint"], "quantity": "1", "unit_cost": "1"}])
    with pytest.raises(ValidationFailed, match="different expiry"):
        publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                      lines=[{"line_id": uuid4(), "product_id": shop["paint"], "quantity": "1", "unit_cost": "1",
                              "batch_no": "NEW", "expiry_date": "2029-01-01"}])


def test_receipts_need_costs(shop) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed, match="negative"):
        publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                      lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "1", "unit_cost": "-5"}])
    with pytest.raises(ValidationFailed, match="not a number"):
        publish_event(shop, "goods.received", "purchasing.receipt", location_id=shop["main"],
                      lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "1"}])


def test_stock_moved_events_reach_the_outbox_for_every_posting(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        moved = s.execute(text("select count(*) from inventory.stock_movement")).scalar_one()
        events = s.execute(text("select count(*) from kernel.event_outbox where event_type = 'stock.moved'")
                           ).scalar_one()
    assert moved == events
