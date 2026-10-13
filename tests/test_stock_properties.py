"""Properties of the stock ledger in the database: random histories keep every figure consistent, and
simultaneous sales cannot sell the last unit twice."""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from itertools import count
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from tests.stock_helpers import INV, P, make_stock_shop, system
from ziira.sdk import ValidationFailed

quantities = st.integers(1, 40).map(Decimal)
costs = st.integers(1, 500).map(Decimal)
OPS = ("receipt", "sale", "adjust_up", "adjust_down", "write_off", "transfer")
histories = st.lists(st.tuples(st.sampled_from(OPS), st.integers(0, 1), quantities, costs), min_size=1, max_size=12)

_names = count(1)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Property Co")
    s["reason"] = UUID(next(x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
                            if x["category"] == "stock_adjustment" and x["code"] == "FOUND"))
    s["write_off_reason"] = UUID(next(
        x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
        if x["category"] == "write_off"))
    s["second"] = client.post(f"{INV}/locations", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "branch_id": str(s["branch_id"]), "code": "SECOND", "name": "Second"}
    ).json()["id"]
    return s


def new_product(client, shop) -> UUID:  # type: ignore[no-untyped-def]
    r = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": f"PROP-{next(_names)}", "name": f"Property {uuid4()}",
        "base_uom_id": shop["uom"], "tax_code_id": shop["tax"]})
    assert r.status_code == 201, r.text
    return UUID(r.json()["id"])


def apply(shop, product: UUID, op: str, place: int, quantity: Decimal, cost: Decimal) -> None:  # type: ignore[no-untyped-def]
    """One real operation in its own transaction; operations the stock cannot support are refused, as in use."""
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    places = [UUID(shop["main"]), UUID(shop["second"])]
    here, there = places[place], places[1 - place]

    def request(location: UUID, signed: Decimal, kind: str, **extra) -> MovementRequest:  # type: ignore[no-untyped-def]
        return MovementRequest(company_id=shop["company_id"], location_id=location, product_id=product,
                               quantity=signed, movement_type=kind, source_type="property", source_id=uuid4(), **extra)

    try:
        with system(shop) as s:
            if op == "receipt":
                post_movement(s, request(here, quantity, "receipt", unit_cost=cost))
            elif op == "sale":
                post_movement(s, request(here, -quantity, "sale"))
            elif op == "adjust_up":
                post_movement(s, request(here, quantity, "adjustment", reason_code_id=shop["reason"]))
            elif op == "adjust_down":
                post_movement(s, request(here, -quantity, "adjustment", reason_code_id=shop["reason"]))
            elif op == "write_off":
                post_movement(s, request(here, -quantity, "write_off", reason_code_id=shop["write_off_reason"]))
            else:                                                       # transfer: both legs in one transaction
                out = post_movement(s, request(here, -quantity, "transfer_out"))
                post_movement(s, request(there, quantity, "transfer_in", unit_cost=out.unit_cost))
    except ValidationFailed:
        pass                                                            # e.g. not enough stock: nothing happened


@given(histories)
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_any_history_leaves_the_ledger_consistent(client, shop, history) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.verify import verify_stock

    product = new_product(client, shop)
    for op, place, quantity, cost in history:
        apply(shop, product, op, place, quantity, cost)
    with system(shop) as s:
        assert verify_stock(s) == []                      # balances and costs equal what the movements add up to
        row = s.execute(text(
            "select c.quantity, c.value, (select coalesce(sum(quantity), 0) from inventory.stock_movement "
            "where product_id = c.product_id) as moved_q, (select coalesce(sum(value), 0) from "
            "inventory.stock_movement where product_id = c.product_id) as moved_v, "
            "(select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = c.product_id) as held "
            "from inventory.product_cost c where c.product_id = :p"), {"p": str(product)}).first()
        negative = s.execute(text("select count(*) from inventory.stock_balance where product_id = :p "
                                  "and quantity < 0"), {"p": str(product)}).scalar_one()
    if row is not None:
        assert row.quantity == row.moved_q == row.held     # the company figure, the ledger and the shelves agree
        assert row.value == row.moved_v
        assert row.quantity >= 0 and row.value >= 0
    assert negative == 0                                   # nothing but sales may go negative, and they were blocked


def slow_down_after_reading_the_balance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Make every posting linger between reading the balance and writing it, so that without row locks all of
    them would read the same figure (a race that is otherwise rare and flaky to reproduce)."""
    from ziira.modules.inventory.repository import inventory_repo

    real = inventory_repo.lock_balance

    def slow(*args, **kwargs):  # type: ignore[no-untyped-def]
        balance = real(*args, **kwargs)
        time.sleep(0.05)
        return balance

    monkeypatch.setattr(inventory_repo, "lock_balance", slow)


def test_two_sales_cannot_take_the_last_unit(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    slow_down_after_reading_the_balance(monkeypatch)
    product = new_product(client, shop)
    apply(shop, product, "receipt", 0, Decimal(1), Decimal(10))
    barrier = threading.Barrier(8)

    def sell_one() -> str:
        system_context(shop["tenant_id"])                  # each thread acts as the system, like an event handler
        barrier.wait()
        try:
            with tenant_session(shop["tenant_id"]) as s:
                post_movement(s, MovementRequest(
                    company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=product,
                    quantity=Decimal(-1), movement_type="sale", source_type="race", source_id=uuid4()))
            return "sold"
        except ValidationFailed:
            return "refused"

    with ThreadPoolExecutor(8) as pool:
        outcome = Counter(pool.map(lambda _: sell_one(), range(8)))
    assert outcome == {"sold": 1, "refused": 7}
    with system(shop) as s:
        held = s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p"),
                         {"p": str(product)}).scalar_one()
    assert held == 0


def test_postings_in_opposite_orders_do_not_deadlock(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Two documents touching the same two products in opposite order both finish: every posting takes the
    product's lock first and documents post their lines in a fixed order."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    first, second = new_product(client, shop), new_product(client, shop)
    for product in (first, second):
        apply(shop, product, "receipt", 0, Decimal(100), Decimal(10))
    barrier = threading.Barrier(2)

    def sale_of(products: list[UUID]) -> str:
        system_context(shop["tenant_id"])
        barrier.wait()
        with tenant_session(shop["tenant_id"]) as s:
            for product in sorted(products, key=str):      # the rule documents follow: a fixed order
                post_movement(s, MovementRequest(
                    company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=product,
                    quantity=Decimal(-1), movement_type="sale", source_type="race", source_id=uuid4()))
        return "done"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(sale_of, [[first, second], [second, first]]))
    assert results == ["done", "done"]
