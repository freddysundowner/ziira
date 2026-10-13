"""Properties of the books: whatever happens to stock and sales, the books balance, equal the stock ledger, and every
operation that fails leaves no trace; simultaneous postings keep numbers unique."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from itertools import count
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from tests.finance_helpers import make_books_shop
from tests.stock_helpers import INV, P, system
from ziira.sdk import Conflict, Event, ValidationFailed, publish

OPS = ("receipt", "sale", "sale_card_credit", "return", "adjust_up", "adjust_down", "write_off", "transfer",
       "opening")
histories = st.lists(st.tuples(st.sampled_from(OPS), st.integers(0, 1), st.integers(1, 30),
                               st.integers(1, 400)), min_size=1, max_size=12)
_names = count(1)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Prop Books")
    reasons = client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
    s["adjust_reason"] = UUID(next(x["id"] for x in reasons if x["category"] == "stock_adjustment"))
    s["write_off_reason"] = UUID(next(x["id"] for x in reasons if x["category"] == "write_off"))
    s["second"] = client.post(f"{INV}/locations", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "branch_id": str(s["branch_id"]), "code": "SECOND", "name": "Second"}
    ).json()["id"]
    return s


def new_product(client, shop) -> UUID:  # type: ignore[no-untyped-def]
    r = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": f"FP-{next(_names)}", "name": f"Prop {uuid4()}",
        "base_uom_id": shop["uom"], "tax_code_id": shop["tax"]})
    assert r.status_code == 201, r.text
    return UUID(r.json()["id"])


def apply(shop, product: UUID, op: str, place: int, quantity: int, cost: int) -> None:  # type: ignore[no-untyped-def]
    """One operation in its own transaction. Operations the system refuses (not enough stock, a bad payment split)
    leave nothing behind, which the checks afterwards prove."""
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    places = [UUID(shop["main"]), UUID(shop["second"])]
    here, there = places[place], places[1 - place]
    qty = Decimal(quantity)

    def movement(location, signed, kind, **extra):  # type: ignore[no-untyped-def]
        return MovementRequest(company_id=shop["company_id"], location_id=location, product_id=product,
                               quantity=signed, movement_type=kind, source_type="prop", source_id=uuid4(), **extra)

    def sale(payments, net_per_unit=Decimal("10")):  # type: ignore[no-untyped-def]
        net = qty * net_per_unit
        tax = (net * Decimal("0.16")).quantize(Decimal("0.01"))
        total = net + tax
        split = [{"method": m, "amount": str(a)} for m, a in payments(total)]
        return {"company_id": shop["company_id"], "branch_id": shop["branch_id"], "location_id": str(here),
                "business_date": "2026-10-13", "net": str(net), "tax": str(tax), "payments": split,
                "lines": [{"line_id": uuid4(), "product_id": product, "quantity": str(qty)}]}

    try:
        with system(shop) as s:
            if op == "receipt":
                post_movement(s, movement(here, qty, "receipt", unit_cost=Decimal(cost)))
            elif op == "opening":
                post_movement(s, movement(here, qty, "opening", unit_cost=Decimal(cost)))
            elif op == "adjust_up":
                post_movement(s, movement(here, qty, "adjustment", reason_code_id=shop["adjust_reason"]))
            elif op == "adjust_down":
                post_movement(s, movement(here, -qty, "adjustment", reason_code_id=shop["adjust_reason"]))
            elif op == "write_off":
                post_movement(s, movement(here, -qty, "write_off", reason_code_id=shop["write_off_reason"]))
            elif op == "transfer":
                out = post_movement(s, movement(here, -qty, "transfer_out"))
                post_movement(s, movement(there, qty, "transfer_in", unit_cost=out.unit_cost))
            elif op == "sale":
                publish(s, Event("sale.posted", "pos.sale", uuid4(), sale(lambda t: [("cash", t)])))
            elif op == "sale_card_credit":
                publish(s, Event("sale.posted", "pos.sale", uuid4(),
                                 sale(lambda t: [("card", (t / 2).quantize(Decimal("0.01"))),
                                                 ("credit", t - (t / 2).quantize(Decimal("0.01")))])))
            else:                                                       # a return of something never sold: at average
                publish(s, Event("sale.returned", "pos.sale_return", uuid4(), {
                    **sale(lambda t: [("mpesa", t)]),
                    "lines": [{"line_id": uuid4(), "product_id": product, "quantity": str(qty)}]}))
    except (ValidationFailed, Conflict):
        pass


@given(histories)
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_any_history_keeps_the_books_balanced_and_equal_to_the_stock(client, shop, history) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.finance.services.verify import verify_books
    from ziira.modules.inventory.public import stock_value

    product = new_product(client, shop)
    for op, place, quantity, cost in history:
        apply(shop, product, op, place, quantity, cost)
    with system(shop) as s:
        assert verify_books(s) == []              # balanced; inventory accounts = stock ledger; all posted
        d, c = s.execute(text("select coalesce(sum(debit), 0), coalesce(sum(credit), 0) "
                              "from finance.journal_line")).one()
        assert d == c
        inventory = s.execute(text(
            "select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l join finance.account a "
            "on a.id = l.account_id where a.subtype in ('inventory', 'inventory_in_transit')")).scalar_one()
        assert inventory == stock_value(s, shop["company_id"])
        stray = s.execute(text(                          # nothing is half-posted: each sale has its entry or neither
            "select count(*) from inventory.stock_movement m where m.value <> 0 and not exists (select 1 from "
            "finance.journal_entry e where e.source_type = 'stock_movement' and e.source_id = m.id)")).scalar_one()
        assert stray == 0
        # the transfer clearing account always nets to zero (every transfer here is complete)
        clearing = s.execute(text(
            "select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l join finance.account a "
            "on a.id = l.account_id where a.subtype = 'transfer_clearing'")).scalar_one()
        assert clearing == 0


def together(calls):  # type: ignore[no-untyped-def]
    barrier = threading.Barrier(len(calls))

    def run(call):  # type: ignore[no-untyped-def]
        barrier.wait()
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def test_first_postings_at_once_set_the_books_up_once(client, registry) -> None:  # type: ignore[no-untyped-def]
    """Six sales arrive together for a company whose books do not exist yet: one chart of accounts, six entries."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.modules.finance.domain import chart

    shop = make_books_shop(client, registry, "Race Books")

    def one_sale() -> str:
        system_context(shop["tenant_id"])
        with tenant_session(shop["tenant_id"]) as s:
            publish(s, Event("sale.posted", "pos.sale", uuid4(), {
                "company_id": shop["company_id"], "branch_id": shop["branch_id"], "net": "100", "tax": "16",
                "payments": [{"method": "cash", "amount": "116"}],
                "lines": [{"line_id": uuid4(), "product_id": shop["delivery"], "quantity": "1"}]}))
        return "ok"

    assert Counter(together([one_sale for _ in range(6)])) == {"ok": 6}
    with system(shop) as s:
        assert s.execute(text("select count(*) from finance.account")).scalar_one() == len(chart.CHART)
        numbers = sorted(s.execute(text("select number from finance.journal_entry")).scalars())
    assert numbers == [f"SAL-{n:06d}" for n in range(1, 7)]                 # unique and without gaps


def test_simultaneous_sales_keep_every_figure_in_step(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.modules.finance.services.verify import verify_books

    product = new_product(client, shop)
    apply(shop, product, "receipt", 0, 20, 10)

    def sell() -> str:
        system_context(shop["tenant_id"])
        try:
            with tenant_session(shop["tenant_id"]) as s:
                publish(s, Event("sale.posted", "pos.sale", uuid4(), {
                    "company_id": shop["company_id"], "branch_id": shop["branch_id"], "location_id": shop["main"],
                    "net": "50", "tax": "8", "payments": [{"method": "mpesa", "amount": "58"}],
                    "lines": [{"line_id": uuid4(), "product_id": product, "quantity": "5"}]}))
            return "sold"
        except ValidationFailed:
            return "refused"

    outcome = Counter(together([sell for _ in range(8)]))
    assert outcome == {"sold": 4, "refused": 4}                              # 20 units, 5 each
    with system(shop) as s:
        assert verify_books(s) == []
        sales = s.execute(text("select count(*) from finance.journal_entry where source_type = 'sale' "
                               "and description = 'Sale'")).scalar_one()
    assert sales >= 4
