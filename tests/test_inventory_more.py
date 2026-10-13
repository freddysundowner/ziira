"""Inventory services called directly: the guards that the API layer normally keeps from being reached."""

from datetime import date
from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system
from ziira.sdk import Conflict, Event, NotFound, ValidationFailed


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "More Co")
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "10"},
                  {"product_id": s["paint"], "quantity": "5", "unit_cost": "4", "batch_no": "B1",
                   "expiry_date": "2027-01-01"}]})
    assert r.status_code == 201, r.text
    return s


def request(shop, **kw):  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import MovementRequest

    base = {"company_id": shop["company_id"], "location_id": UUID(shop["main"]), "product_id": UUID(shop["cement"]),
            "quantity": Dec("-1"), "movement_type": "sale", "source_type": "t", "source_id": uuid4()}
    return MovementRequest(**{**base, **kw})


# --------------------------------------------------------------------------- the ledger's guards
def test_post_movement_refuses_what_the_domain_refuses(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import post_movement

    cases = [({"quantity": Dec("0")}, "zero"), ({"quantity": Dec("1")}, "must be negative"),
             ({"movement_type": "teleport"}, "must be one of"), ({"movement_type": "write_off"}, "reason is required"),
             ({"quantity": Dec("1"), "movement_type": "receipt"}, "unit cost is required"),
             ({"location_id": uuid4()}, "Location not found"), ({"product_id": uuid4()}, "Product not found"),
             ({"company_id": uuid4()}, "Location not found"),
             ({"product_id": UUID(shop["delivery"])}, "Only stock products"),
             ({"product_id": UUID(shop["paint"])}, "batch-tracked"),
             ({"batch_id": uuid4()}, "not batch-tracked")]
    for change, message in cases:
        with pytest.raises(ValidationFailed, match=message), system(shop) as s:
            post_movement(s, request(shop, **change))


def test_stock_going_out_must_be_negative_and_batches_must_exist(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import post_stock_out

    with pytest.raises(ValidationFailed, match="negative quantity"), system(shop) as s:
        post_stock_out(s, request(shop, quantity=Dec("1"), movement_type="adjustment", reason_code_id=uuid4()))
    with pytest.raises(ValidationFailed, match="no batch has any"), system(shop) as s:
        # a batch-tracked product with no batch rows at all: nothing to take from even if negative is allowed
        post_stock_out(s, request(shop, product_id=UUID(shop["paint"]), location_id=UUID(shop["juja_store"]),
                                  quantity=Dec("-1"), allow_negative=True))


def test_a_shortage_of_a_batch_tracked_product_lands_on_the_earliest_batch_when_allowed(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import post_stock_out

    with system(shop) as s:
        moved = post_stock_out(s, request(shop, product_id=UUID(shop["paint"]), quantity=Dec("-8"),
                                          allow_negative=True))
    assert [m.quantity for m in moved] == [Dec("-8")]                   # one batch, 5 on hand: -3 left
    with system(shop) as s:
        assert s.execute(text("select quantity from inventory.stock_balance where product_id = :p"),
                         {"p": shop["paint"]}).scalar_one() == Dec("-3")


def test_batches_keep_their_expiry_date(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import get_or_create_batch
    from ziira.modules.products.public import find_product

    with system(shop) as s:
        product = find_product(s, UUID(shop["paint"]))
        assert product is not None
        existing = get_or_create_batch(s, product, " B1 ", None)             # no expiry given: keeps its own
        assert existing.expiry_date == date(2027, 1, 1)
        assert get_or_create_batch(s, product, "B1", date(2027, 1, 1)).id == existing.id
        with pytest.raises(ValidationFailed, match="different expiry"):
            get_or_create_batch(s, product, "B1", date(2030, 1, 1))
        with pytest.raises(ValidationFailed, match="required"):
            get_or_create_batch(s, product, "  ", None)


def test_a_balance_that_would_overflow_is_refused(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.domain.movements import MAX_QUANTITY
    from ziira.modules.inventory.services.ledger import post_movement

    with pytest.raises(ValidationFailed, match="too large"), system(shop) as s:
        post_movement(s, request(shop, quantity=MAX_QUANTITY, movement_type="adjustment", reason_code_id=_reason(shop)))


def _reason(shop) -> UUID:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select id from kernel.reason_code where category = 'stock_adjustment' limit 1")
                         ).scalar_one()


# --------------------------------------------------------------------------- services called without the HTTP layer
def test_documents_that_do_not_exist_or_are_hidden_are_not_found(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services import adjustments, counts, transfers

    with system(shop) as s:
        for finder in (adjustments.get_adjustment, transfers.get_transfer, counts.get_count):
            with pytest.raises(NotFound):
                finder(s, uuid4())


def test_services_refuse_empty_input(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services import adjustments, counts, opening_stock

    with pytest.raises(ValidationFailed, match="at least one line"), system(shop) as s:
        opening_stock.post_opening_stock(s, company_id=shop["company_id"], location_id=UUID(shop["main"]), lines=[])
    with pytest.raises(ValidationFailed, match="at least one line"), system(shop) as s:
        adjustments.create_adjustment(s, company_id=shop["company_id"], location_id=UUID(shop["main"]),
                                      reason_code_id=_reason(shop), note=None, lines=[])
    with system(shop) as s:
        count = counts.start_count(s, company_id=shop["company_id"], location_id=UUID(shop["juja_store"]))
        with pytest.raises(ValidationFailed, match="at least one counted"):
            counts.record_counts(s, count.count.id, [])


def test_opening_stock_for_a_plain_product_cannot_name_a_batch(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.opening_stock import OpeningLine, post_opening_stock

    product = UUID(shop["delivery"])                                   # not stock: refused earlier
    with pytest.raises(ValidationFailed), system(shop) as s:
        post_opening_stock(s, company_id=shop["company_id"], location_id=UUID(shop["juja_store"]),
                           lines=[OpeningLine(product, Dec("1"), Dec("1"), batch_no="B")])
    plain = UUID(shop["cement"])
    with pytest.raises(ValidationFailed, match="not batch-tracked"), system(shop) as s:
        post_opening_stock(s, company_id=shop["company_id"], location_id=UUID(shop["juja_store"]),
                           lines=[OpeningLine(plain, Dec("1"), Dec("1"), batch_no="B")])


# --------------------------------------------------------------------------- event payloads from other units
def publish_raw(shop, event_type: str, aggregate: str, payload: dict):  # type: ignore[no-untyped-def]
    from ziira.sdk import publish

    with system(shop) as s:
        publish(s, Event(event_type, aggregate, uuid4(), {"company_id": shop["company_id"], **payload}))


def line(shop, product="cement", quantity="1", **extra):  # type: ignore[no-untyped-def]
    return {"line_id": uuid4(), "product_id": shop[product], "quantity": quantity, **extra}


def test_event_payload_guards(shop) -> None:  # type: ignore[no-untyped-def]
    where = {"location_id": shop["main"]}
    cases = [
        ("sale.posted", {**where, "lines": [line(shop)], "business_date": "yesterday"}, "not a date"),
        ("sale.posted", {**where, "lines": [line(shop, quantity="NaN")]}, "not a number"),
        ("sale.posted", {**where, "lines": [line(shop, quantity="Infinity")]}, "not a number"),
        ("sale.posted", {"location_id": str(uuid4()), "lines": [line(shop)]}, "location not found"),
        ("sale.posted", {"lines": [line(shop)]}, "location_id is required"),
        ("sale.posted", {**where, "lines": "not a list"}, "no lines"),
        ("sale.posted", {**where, "lines": [{"product_id": shop["cement"], "quantity": "1"}]}, "not a valid id"),
        ("goods.received", {**where, "landed_cost": "-5", "lines": [line(shop, unit_cost="1")]}, "landed cost"),
        ("goods.received", {**where, "lines": [line(shop, unit_cost="NaN")]}, "not a number"),
        ("goods.received", {**where, "lines": [line(shop, unit_cost="1E+30")]}, "too large"),
    ]
    for event_type, payload, message in cases:
        with pytest.raises(ValidationFailed, match=message):
            publish_raw(shop, event_type, "x", payload)


def test_a_return_of_an_unknown_sale_line_uses_the_current_average(shop) -> None:  # type: ignore[no-untyped-def]
    returned = uuid4()
    from ziira.sdk import publish

    with system(shop) as s:
        publish(s, Event("sale.returned", "pos.sale_return", returned, {
            "company_id": shop["company_id"], "location_id": shop["main"], "sale_id": uuid4(),
            "lines": [line(shop, quantity="2", sale_line_id=uuid4())]}))
    with system(shop) as s:
        row = s.execute(text("select unit_cost, quantity from inventory.stock_movement where source_id = :i"),
                        {"i": str(returned)}).one()
    assert row.quantity == 2 and row.unit_cost == Dec("10")


# --------------------------------------------------------------------------- the public interface
def test_public_reads(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.public import average_cost, posted_cost, stock_on_hand

    cement = UUID(shop["cement"])
    with system(shop) as s:
        held = stock_on_hand(s, cement)                              # 100 opening + what the tests above added
        assert held >= 100
        assert stock_on_hand(s, cement, location_id=UUID(shop["main"])) == held
        assert stock_on_hand(s, cement, location_id=UUID(shop["juja_store"])) == 0
        assert stock_on_hand(s, cement, company_id=shop["company_id"]) == held
        assert stock_on_hand(s, cement, company_id=uuid4()) == 0
        assert stock_on_hand(s, uuid4()) == 0
        assert average_cost(s, shop["company_id"], cement) == 10
        assert average_cost(s, uuid4(), cement) == 0
        assert posted_cost(s, "no-such-source", uuid4()) == {}


def test_locations_can_be_filtered(client, shop) -> None:  # type: ignore[no-untyped-def]
    by_branch = client.get(f"{INV}/locations", headers=shop["owner"], params={"branch_id": str(shop["juja"])}).json()
    assert [x["code"] for x in by_branch] == ["JUJA-STORE"]
    by_kind = client.get(f"{INV}/locations", headers=shop["owner"], params={"kind": "warehouse"}).json()
    assert by_kind == []
    by_company = client.get(f"{INV}/locations", headers=shop["owner"],
                            params={"company_id": str(shop["company_id"]), "kind": "store"}).json()
    assert {x["code"] for x in by_company} == {"MAIN", "JUJA-STORE"}


def test_unknown_conflict_import() -> None:
    assert issubclass(Conflict, Exception)                       # keeps the import honest for future tests
