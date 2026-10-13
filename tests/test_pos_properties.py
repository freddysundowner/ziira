"""POS under pressure: simultaneous sales never oversell or repeat a number, a sale racing a void, a return or a till
close ends in one consistent state, and the money always agrees across sales, payments, stock and the books."""

import random
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import FIN, balance
from tests.payments_helpers import one
from tests.pos_helpers import POS, ensure_till, line, make_pos_shop, open_till, sell, stock
from tests.stock_helpers import INV, P
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_pos_shop(client, registry, "Pos Props Co", finance=True, stock="1000")
    owner, co = s["owner"], str(s["company_id"])
    scarce = client.post(f"{P}/products", headers=owner, json={
        "company_id": co, "sku": "SCARCE", "name": "Scarce", "base_uom_id": s["uom"], "tax_code_id": s["tax"]}).json()
    client.put(f"{P}/price-lists/{s['price_list']}/prices", headers=owner, json={
        "product_id": scarce["id"], "price": "10.00", "valid_from": "2026-01-01"})
    client.post(f"{INV}/opening-stock", headers=owner, json={
        "company_id": co, "location_id": s["main"], "lines": [{"product_id": scarce["id"], "quantity": "5",
                                                              "unit_cost": "4"}]})
    s["scarce"] = scarce["id"]
    return s


def cashiers(client, shop, n: int, prefix: str):  # type: ignore[no-untyped-def]
    """n cashiers, each with a device and an open till."""
    out = []
    for i in range(n):
        name = f"{prefix}{i}"
        who = shop["user"](name, "Cashier", shop["branch_id"])
        dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
            "branch_id": str(shop["branch_id"]), "code": f"{prefix[:3].upper()}{i}", "name": name,
            "location_id": shop["main"]}).json()
        shop[name], shop["devices"][name] = who, dev["id"]
        till = open_till(client, shop, name).json()["id"]
        out.append((name, till))
    return out


def test_simultaneous_sales_never_oversell(client, shop) -> None:  # type: ignore[no-untyped-def]
    staff = cashiers(client, shop, 4, "race")
    body = lambda till: {"till_session_id": till, "lines": [{"product_id": shop["scarce"], "quantity": "1"}],  # noqa: E731
                         "payments": [{"method": "cash", "amount": "10.00"}]}
    calls = [lambda who=who, till=till: client.post(f"{POS}/sales", headers=shop[who], json=body(till))
             for _ in range(3) for who, till in staff]                                   # 12 attempts, 5 in stock
    results = together(calls)
    ok = [r for r in results if r.status_code == 201]
    assert len(ok) == 5 and sorted({r.status_code for r in results}) == [201, 422], [r.text for r in results][:3]
    on_hand = one(shop, "select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p",
                  p=shop["scarce"])
    assert on_hand == 0
    assert one(shop, "select count(*) from pos.sale_line where product_id = :p", p=shop["scarce"]) == 5
    cash = one(shop, "select coalesce(sum(p.amount), 0) from payments.payment p join pos.sale_payment sp on "
                     "sp.payment_id = p.id join pos.sale_line l on l.sale_id = sp.sale_id where l.product_id = :p",
               p=shop["scarce"])
    assert cash == 50                                                       # only the five that sold took money
    for who, till in staff:
        takings = 10 * sum(1 for r in ok if r.json()["till_session_id"] == till)
        closed = client.post(f"{POS}/tills/{till}/close", headers=shop[who], json={"counted_cash": str(1000 + takings)})
        assert closed.status_code == 200 and Dec(closed.json()["variance"]) == 0, closed.text


def test_numbers_on_one_device_are_unique_and_gap_free_under_load(client, shop) -> None:  # type: ignore[no-untyped-def]
    ((name, till),) = cashiers(client, shop, 1, "seq")
    ok = lambda: client.post(f"{POS}/sales", headers=shop[name], json={  # noqa: E731
        "till_session_id": till, "lines": [line(shop, "delivery", "1")], "payments": [{"method": "cash", "amount": "58"}]})
    bad = lambda: client.post(f"{POS}/sales", headers=shop[name], json={  # noqa: E731
        "till_session_id": till, "lines": [line(shop, "cement", "1")], "payments": [{"method": "cash", "amount": "1"}]})
    results = together([ok, bad] * 10)
    numbers = sorted(r.json()["number"] for r in results if r.status_code == 201)
    assert len(numbers) == 10 and len(set(numbers)) == 10
    sequence = [int(n.rsplit("-", 1)[1]) for n in numbers]
    assert sequence == list(range(sequence[0], sequence[0] + 10))           # refused sales left no holes
    client.post(f"{POS}/tills/{till}/close", headers=shop[name], json={"counted_cash": "1580.00"})


def test_a_void_and_a_return_racing_on_one_sale_leave_one_winner(client, shop) -> None:  # type: ignore[no-untyped-def]
    manager_till = ensure_till(client, shop, "manager")
    sale = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "2")],
                payments=[{"method": "cash", "amount": "232"}]).json()
    before = stock(shop)
    void = lambda: client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"], json={  # noqa: E731
        "reason_code_id": shop["reasons"]["void"]})
    ret = lambda: client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json={  # noqa: E731
        "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "2"}],
        "reason_code_id": shop["reasons"]["sale_return"], "refund_method": "cash"})
    results = together([void, ret, void, ret])
    won = [r for r in results if r.status_code in (200, 201)]
    assert len(won) == 1, [(r.status_code, r.text) for r in results]
    assert stock(shop) == before + 2                                          # the goods came back exactly once
    assert one(shop, "select count(*) from inventory.stock_movement where source_type = 'sale_return' and "
                     "source_id in (select id from pos.sale where id = :s union select id from pos.sales_return "
                     "where original_sale_id = :s)", s=sale["id"]) == 1


def test_a_sale_racing_the_close_is_either_counted_or_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    ((name, till),) = cashiers(client, shop, 1, "clos")
    sale = lambda: client.post(f"{POS}/sales", headers=shop[name], json={  # noqa: E731
        "till_session_id": till, "lines": [line(shop, "delivery", "1")], "payments": [{"method": "cash", "amount": "58"}]})
    close = lambda: client.post(f"{POS}/tills/{till}/close", headers=shop["manager"], json={  # noqa: E731
        "counted_cash": "1000", "reason_code_id": shop["reasons"]["till_variance"]})
    results = together([sale, sale, close, sale, sale])
    sold = sum(1 for r in results[:2] + results[3:] if r.status_code == 201)
    closed = [r for r in results if r.status_code == 200 and "expected_cash" in r.json()]
    assert len(closed) == 1
    expected = Dec(closed[0].json()["expected_cash"])
    cash_taken = one(shop, "select coalesce(sum(p.amount), 0) from pos.sale s join pos.sale_payment p on p.sale_id = "
                           "s.id where s.till_session_id = :t and s.status = 'posted'", t=till)
    # the count was taken after every sale it includes and before any it refused
    assert expected == 1000 + cash_taken and sold >= cash_taken / 58 - 0 and cash_taken % 58 == 0
    late = one(shop, "select count(*) from pos.sale s join pos.till_session t on t.id = s.till_session_id where "
                     "t.id = :t and s.created_at > t.closed_at", t=till)
    assert late == 0


def test_random_trading_keeps_every_total_in_agreement(client, shop) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(4)
    ((name, till),) = cashiers(client, shop, 1, "rand")
    manager_till = ensure_till(client, shop, "manager")
    reason = shop["reasons"]["price_override"]
    sold, voided = [], 0
    for i in range(60):
        n_lines = rng.randint(1, 3)
        lines = []
        for _ in range(n_lines):
            product = rng.choice(["cement", "paint", "delivery"])
            item = line(shop, product, str(rng.choice([1, 2, 3, "0.5", "1.25"])))
            lines.append(item)
        manager = rng.random() < 0.3
        if manager:
            lines[0] = {**lines[0], "discount": str(rng.choice([0, 1, "2.50", 10])), "reason_code_id": reason}
            if lines[0]["discount"] == 0:
                lines[0].pop("reason_code_id")
        payer, mine = ("manager", manager_till) if manager else (name, till)
        r = sell(client, shop, who=payer, till=mine, lines=lines,
                 payments=[{"method": "cash", "amount": "5000.00"}], local_id=str(uuid4()))
        assert r.status_code == 201, (i, lines, r.text)
        sold.append(r.json())
        if rng.random() < 0.15:
            v = client.post(f"{POS}/sales/{r.json()['id']}/void", headers=shop["manager"], json={
                "reason_code_id": shop["reasons"]["void"]})
            assert v.status_code == 200, v.text
            voided += 1
    for s in sold:
        total = Dec(s["total"])
        assert total == sum(Dec(x["line_total"]) for x in s["lines"])
        assert total == sum(Dec(x["amount"]) for x in s["payments"])
        assert Dec(s["tax_total"]) == sum(Dec(x["tax_amount"]) for x in s["lines"])
        assert Dec(s["subtotal"]) - Dec(s["discount_total"]) == total
    # the same figures in four places
    posted = one(shop, "select coalesce(sum(total), 0) from pos.sale where status = 'posted'")
    taken = one(shop, "select coalesce(sum(p.amount), 0) from payments.payment p where p.direction = 'in' and "
                      "p.status = 'posted' and p.id in (select payment_id from pos.sale_payment)")
    assert posted == taken
    tb = client.get(f"{FIN}/reports/trial-balance", headers=shop["owner"],
                    params={"company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"] and tb["total_debit"] == tb["total_credit"]
    assert balance(shop, "1010") >= 0 and voided >= 1
    # stock in the ledger equals stock in the books
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
    client.post(f"{POS}/tills/{till}/close", headers=shop[name], json={
        "counted_cash": "0", "reason_code_id": shop["reasons"]["till_variance"]})
