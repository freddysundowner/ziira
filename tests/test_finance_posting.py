"""The posting engine: stock, sales and returns become balanced entries, atomically with the operation behind them."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import FIN, balance, entries, make_books_shop, opening, publish_sale
from tests.stock_helpers import INV, system
from ziira.sdk import Conflict, Event, ValidationFailed


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_books_shop(client, registry, "Books Co")


def shape(entry):  # type: ignore[no-untyped-def]
    """[(account code, debit, credit)] of an entry from tests.finance_helpers.entries."""
    return [(code, debit, credit) for code, debit, credit, _ in entry[2]]


def last(shop, **where):  # type: ignore[no-untyped-def]
    return entries(shop, **where)[-1]


def trial_balanced(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        d, c = s.execute(text("select coalesce(sum(debit), 0), coalesce(sum(credit), 0) "
                              "from finance.journal_line")).one()
    assert d == c


# --------------------------------------------------------------------------- the books set themselves up
def test_the_books_appear_with_the_first_posting_and_only_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.finance.domain import chart

    with system(shop) as s:
        assert s.execute(text("select count(*) from finance.account")).scalar_one() == 0      # nothing yet
    opening(client, shop)
    with system(shop) as s:
        counts = [s.execute(text(f"select count(*) from finance.{t}")).scalar_one()
                  for t in ("account", "journal", "posting_rule")]
    assert counts == [len(chart.CHART), len(chart.JOURNALS), len(chart.DEFAULT_RULES)]
    r = client.post(f"{FIN}/companies/{shop['company_id']}/books", headers=shop["owner"])
    assert r.status_code == 200 and len(r.json()) == len(chart.CHART)                          # idempotent
    with system(shop) as s:
        assert s.execute(text("select count(*) from finance.account")).scalar_one() == len(chart.CHART)


def test_opening_stock_posts_inventory_against_opening_equity(shop) -> None:  # type: ignore[no-untyped-def]
    entry = entries(shop)[0]
    assert entry[0] == "STK-000001" and entry[1] == "stock_movement"
    assert sorted(shape(entry)) == sorted([("1200", Dec("1000.00"), Dec("0.00")),
                                           ("3100", Dec("0.00"), Dec("1000.00"))])
    assert {b for _, _, _, b in entry[2]} == {shop["branch_id"]}                              # branch dimension


# --------------------------------------------------------------------------- sales
def test_a_cash_sale_with_its_cost_of_goods(shop) -> None:  # type: ignore[no-untyped-def]
    sale = uuid4()
    publish_sale(shop, sale_id=sale, lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "4"}])
    revenue = entries(shop, source_type="sale", source_id=sale)[0]
    assert revenue[0].startswith("SAL-") and revenue[4] == "Sale POS-1"
    assert sorted(shape(revenue)) == sorted([("1010", Dec("116.00"), Dec("0.00")), ("4000", Dec("0.00"), Dec("100.00")),
                                              ("2200", Dec("0.00"), Dec("16.00"))])
    cogs = last(shop, source_type="stock_movement")
    assert sorted(shape(cogs)) == sorted([("5000", Dec("40.00"), Dec("0.00")), ("1200", Dec("0.00"), Dec("40.00"))])
    assert balance(shop, "1200") == Dec("960.00") and balance(shop, "5000") == Dec("40.00")
    trial_balanced(shop)


def test_a_sale_paid_several_ways_with_credit_to_a_customer(shop) -> None:  # type: ignore[no-untyped-def]
    customer, sale = uuid4(), uuid4()
    publish_sale(shop, sale_id=sale, net="200", tax="32", customer=customer, payments=[
        {"method": "cash", "amount": "100"}, {"method": "mobile_money", "amount": "82"}, {"method": "card", "amount": "20"},
        {"method": "credit", "amount": "30"}])
    entry = entries(shop, source_type="sale", source_id=sale)[0]
    assert {c for c, _, _ in shape(entry)} == {"1010", "1030", "1040", "1100", "4000", "2200"}
    with system(shop) as s:
        parties = s.execute(text("select a.code, l.party_type, l.party_id from finance.journal_line l join "
                                 "finance.account a on a.id = l.account_id join finance.journal_entry e on e.id = "
                                 "l.entry_id where e.source_id = :s and l.party_id is not null"),
                           {"s": str(sale)}).all()
    assert [(c, t, str(p)) for c, t, p in parties] == [("1100", "customer", str(customer))]
    trial_balanced(shop)


def test_a_sale_must_be_paid_for_exactly_and_failure_rolls_everything_back(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        stock_before = s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance")).scalar_one()
        entries_before = s.execute(text("select count(*) from finance.journal_entry")).scalar_one()
    stock_line = [{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "5"}]
    for kwargs, message in (({"payments": [{"method": "cash", "amount": "100"}]}, "add up to 100"),
                            ({"payments": [{"method": "cash", "amount": "-116"}, {"method": "mobile_money", "amount": "232"}]},
                             "positive"),
                            ({"payments": "cash"}, "payments are required"),
                            ({"net": "NaN"}, "not a number"),
                            ({"business_date": "last tuesday"}, "not a date")):
        with pytest.raises(ValidationFailed, match=message):
            publish_sale(shop, lines=stock_line, **kwargs)
    with system(shop) as s:
        assert s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance")).scalar_one() \
            == stock_before                                            # the stock movement of the sale did not survive
        assert s.execute(text("select count(*) from finance.journal_entry")).scalar_one() == entries_before


def test_the_same_sale_cannot_be_posted_twice(shop) -> None:  # type: ignore[no-untyped-def]
    sale = publish_sale(shop)
    with pytest.raises(Conflict, match="already been posted"):
        publish_sale(shop, sale_id=sale)


def test_a_return_reverses_the_sale_and_its_stock_comes_back_at_cost(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import publish

    line, sale = uuid4(), uuid4()
    publish_sale(shop, sale_id=sale, net="50", tax="8", lines=[{"line_id": line, "product_id": shop["cement"],
                                                                "quantity": "2"}])
    cash_before, returns_before = balance(shop, "1010"), balance(shop, "4100")
    back = uuid4()
    with system(shop) as s:
        publish(s, Event("sale.returned", "pos.sale_return", back, {
            "company_id": shop["company_id"], "branch_id": shop["branch_id"], "location_id": shop["main"],
            "sale_id": sale, "net": "50", "tax": "8", "number": "RET-1",
            "payments": [{"method": "cash", "amount": "58"}],
            "lines": [{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "2", "sale_line_id": line}]}))
    entry = entries(shop, source_type="sale_return", source_id=back)[0]
    assert sorted(shape(entry)) == sorted([("1010", Dec("0.00"), Dec("58.00")), ("4100", Dec("50.00"), Dec("0.00")),
                                            ("2200", Dec("8.00"), Dec("0.00"))])
    assert balance(shop, "1010") == cash_before - 58 and balance(shop, "4100") == returns_before + 50
    stock_entry = last(shop, source_type="stock_movement")
    assert sorted(shape(stock_entry)) == sorted([("1200", Dec("20.00"), Dec("0.00")),
                                                 ("5000", Dec("0.00"), Dec("20.00"))])
    trial_balanced(shop)


# --------------------------------------------------------------------------- every kind of stock movement
def adjustment(client, shop, qty: str, category: str = "stock_adjustment", code: str | None = None):  # type: ignore[no-untyped-def]
    reasons = client.get("/api/v1/settings/reason-codes", headers=shop["owner"]).json()
    reason = next(x["id"] for x in reasons if x["category"] == category and (code is None or x["code"] == code))
    a = client.post(f"{INV}/adjustments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "reason_code_id": reason,
        "lines": [{"product_id": shop["cement"], "qty_change": qty}]}).json()
    assert client.post(f"{INV}/adjustments/{a['id']}/submit", headers=shop["owner"]).json()["status"] == "posted"
    return a


def test_losses_and_gains_go_to_shrinkage(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = balance(shop, "5100")
    adjustment(client, shop, "-3")                                          # 3 x 10 lost
    assert balance(shop, "5100") == before + 30
    assert sorted(shape(last(shop, source_type="stock_movement"))) == sorted(
        [("5100", Dec("30.00"), Dec("0.00")), ("1200", Dec("0.00"), Dec("30.00"))])
    adjustment(client, shop, "2", code="FOUND")                             # 2 found at the average cost
    assert balance(shop, "5100") == before + 30 - 20
    trial_balanced(shop)


def test_a_transfer_moves_value_through_in_transit_and_nets_to_zero(client, shop) -> None:  # type: ignore[no-untyped-def]
    inventory_before, transit_before = balance(shop, "1200"), balance(shop, "1210")
    clearing_before = balance(shop, "2900")
    t = client.post(f"{INV}/transfers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": shop["cement"], "quantity": "10"}]}).json()
    client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=shop["owner"])
    assert balance(shop, "1210") == transit_before + 100                    # on the road: 10 x 10
    assert balance(shop, "1200") == inventory_before - 100
    client.post(f"{INV}/transfers/{t['id']}/receive", headers=shop["owner"])
    assert balance(shop, "1210") == transit_before                          # arrived: nothing left in transit
    assert balance(shop, "1200") == inventory_before                        # at the other branch now
    assert balance(shop, "2900") == clearing_before                         # the clearing account nets to zero
    with system(shop) as s:                                                 # and each branch holds its own share
        by_branch = dict(s.execute(text(
            "select l.branch_id, sum(l.debit - l.credit) from finance.journal_line l join finance.account a on "
            "a.id = l.account_id where a.code = '1200' group by l.branch_id")).all())
    assert by_branch[shop["juja"]] == Dec("100.00")


def test_a_short_delivery_posts_the_loss(client, shop) -> None:  # type: ignore[no-untyped-def]
    reasons = client.get("/api/v1/settings/reason-codes", headers=shop["owner"]).json()
    short = next(x["id"] for x in reasons if x["category"] == "transfer_variance")
    t = client.post(f"{INV}/transfers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": shop["cement"], "quantity": "10"}]}).json()
    client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=shop["owner"])
    shrinkage = balance(shop, "5100")
    r = client.post(f"{INV}/transfers/{t['id']}/receive", headers=shop["owner"], json={"lines": [
        {"line_id": t["lines"][0]["id"], "qty_received": "8", "reason_code_id": short}]})
    assert r.status_code == 200, r.text
    assert balance(shop, "5100") == shrinkage + 20 and balance(shop, "1210") == 0
    trial_balanced(shop)


def test_receipts_and_purchase_returns_use_goods_received_not_invoiced(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import publish

    grni_before = balance(shop, "2100")
    receipt = uuid4()
    with system(shop) as s:
        publish(s, Event("goods.received", "purchasing.receipt", receipt, {
            "company_id": shop["company_id"], "location_id": shop["main"], "landed_cost": "50",
            "lines": [{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "10", "unit_cost": "20"}]}))
    assert balance(shop, "2100") == grni_before - 250                       # credit: owed to the supplier, 200 + 50
    assert sorted(shape(last(shop, source_type="stock_movement"))) == sorted(
        [("1200", Dec("250.00"), Dec("0.00")), ("2100", Dec("0.00"), Dec("250.00"))])
    trial_balanced(shop)


def test_the_inventory_accounts_always_equal_the_stock_ledger(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.public import stock_value

    with system(shop) as s:
        assert stock_value(s, shop["company_id"]) == balance(shop, "1200") + balance(shop, "1210")


# --------------------------------------------------------------------------- entries are immutable and balanced
def test_entries_cannot_be_changed_or_unbalanced(shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    for sql in ("update finance.journal_entry set description = 'x'", "delete from finance.journal_entry",
                "update finance.journal_line set debit = debit + 1", "delete from finance.journal_line"):
        with pytest.raises(DBAPIError, match="immutable"), system(shop) as s:
            s.execute(text(sql))
    with system(shop) as s:                                      # a line added to an entry unbalances it: refused
        entry_id = s.execute(text("select id from finance.journal_entry limit 1")).scalar_one()
        account = s.execute(text("select id from finance.account limit 1")).scalar_one()
    with pytest.raises(DBAPIError, match="not balanced"), system(shop) as s:
        s.execute(text("insert into finance.journal_line (tenant_id, entry_id, company_id, account_id, debit) "
                       "values (kernel.current_tenant(), :e, :c, :a, 5)"),
                  {"e": str(entry_id), "c": str(shop["company_id"]), "a": str(account)})


def test_postings_are_numbered_without_gaps_and_dated_as_the_business_day(shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, business_date="2026-10-05")
    entry = last(shop, source_type="sale")
    assert str(entry[3]) == "2026-10-05"
    numbers = [int(n.rsplit("-", 1)[1]) for n, *_ in entries(shop) if n.startswith("STK-")]
    assert numbers == list(range(1, len(numbers) + 1))
