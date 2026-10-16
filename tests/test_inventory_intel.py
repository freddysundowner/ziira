"""Inventory's contribution to Intelligence and the Command Center: the checks, the baseline and the pulse figures.

Every scenario is built through the unit's own API or ledger, then the real engine runs the check under test.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal as Dec
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, P, make_stock_shop, system
from ziira.kernel import extensions
from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.services import baselines, engine
from ziira.modules.inventory.intel_checks.controls import AdjustmentValueByUser
from ziira.modules.inventory.pulse import InventoryPulse
from ziira.modules.inventory.services.ledger import MovementRequest, post_movement, post_stock_out
from ziira.sdk import format_day

INTEL = "/api/v1/intel"
BASE = datetime.now(ZoneInfo("Africa/Nairobi")).date()          # the test tenants' zone (a fixture value)


def prepare(client, registry, name: str):  # type: ignore[no-untyped-def]
    """A stock shop with Intelligence and the Command Center switched on, and a few lookups."""
    shop = make_stock_shop(client, registry, name)
    registry.enable(shop["tenant_id"], "intel")
    registry.enable(shop["tenant_id"], "command")
    with system(shop) as s:
        shop["currency"] = s.execute(text("select base_currency from kernel.company")).scalar_one()
        shop["owner_id"] = s.execute(text("select id from kernel.app_user where email = :e"),
                                     {"e": f"owner@{shop['code']}.test"}).scalar_one()
        shop["reason"] = s.execute(text("select id from kernel.reason_code where category = 'stock_adjustment' "
                                        "and code = 'THEFT'")).scalar_one()
        shop["count_reason"] = s.execute(text("select id from kernel.reason_code where category = 'count_variance' "
                                              "and code = 'COUNT_ERROR'")).scalar_one()
    return shop


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return prepare(client, registry, "Inv Intel Co")


# --------------------------------------------------------------------------- helpers
def new_product(client, shop, sku: str, **extra) -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": sku, "name": f"Item {sku}", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"], **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def opening(client, shop, product: str, quantity: str, cost: str, place: str = "main", **line) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop[place],
        "lines": [{"product_id": product, "quantity": quantity, "unit_cost": cost, **line}]})
    assert r.status_code == 201, r.text


def move(shop, product: str, quantity: str, kind: str, place: str = "main", **extra: Any) -> None:  # type: ignore[no-untyped-def]
    """Post a movement straight into the ledger (a sale, a receipt...)."""
    with system(shop) as s:
        post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop[place]), product_id=UUID(product),
            quantity=Dec(quantity), movement_type=kind, source_type=extra.pop("source_type", "test_doc"),
            source_id=extra.pop("source_id", uuid4()), **extra))


def sell_fefo(shop, product: str, quantity: str) -> None:  # type: ignore[no-untyped-def]
    """Sell a batch-tracked product: the earliest expiry goes first."""
    with system(shop) as s:
        post_stock_out(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(product),
            quantity=-Dec(quantity), movement_type="sale", source_type="test_doc", source_id=uuid4()))


def adjust(client, shop, product: str, change: str, place: str = "main") -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/adjustments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop[place], "reason_code_id": str(shop["reason"]),
        "lines": [{"product_id": product, "qty_change": change}]})
    assert r.status_code == 201, r.text
    posted = client.post(f"{INV}/adjustments/{r.json()['id']}/submit", headers=shop["owner"])
    assert posted.status_code == 200 and posted.json()["status"] == "posted", posted.text
    return posted.json()


def run(shop, code: str, today: date = BASE) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=today, only={code})
    assert result.failed == [] and result.checks_run == 1


def found(shop, code: str, sku: str | None = None) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """The findings of a check (all statuses), optionally those whose summary names a product."""
    with system(shop) as s:
        rows = s.execute(text("select summary, severity, amount, branch_id, status, evidence, recommended_action, "
                              "value, expected_value from intel.finding where check_code = :c order by summary"),
                         {"c": code}).all()
    return [dict(r._mapping) for r in rows if sku is None or f"({sku})" in r.summary or sku in r.summary]


def open_ones(shop, code: str, sku: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return [f for f in found(shop, code, sku) if f["status"] not in ("resolved", "dismissed")]


def tune(client, shop, code: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


def records(finding: dict[str, Any]) -> list[tuple[str, str]]:
    return [(x["type"], x["id"]) for x in finding["evidence"]["records"]]


# --------------------------------------------------------------------------- stock levels
def test_out_of_stock_then_low_then_fine(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.out_of_stock"
    oos = new_product(client, shop, "OOS1", reorder_level="5")
    opening(client, shop, oos, "10", "20")
    run(shop, code)
    assert open_ones(shop, code, "OOS1") == []                        # 10 on hand: nothing to say

    move(shop, oos, "-10", "sale")
    run(shop, code)
    [f] = open_ones(shop, code, "OOS1")
    assert (f["severity"], f["branch_id"]) == ("medium", shop["branch_id"])
    assert "Item OOS1 (OOS1) is out of stock at" in f["summary"] and f["recommended_action"].startswith("Reorder")
    assert records(f) == [("products.product", oos)]
    assert not [x for x in found(shop, code) if str(shop["juja"]) == str(x["branch_id"])]   # Juja never had it

    adjust(client, shop, oos, "4")                                    # back, but under the reorder level of 5
    run(shop, code)
    assert open_ones(shop, code, "OOS1") == []                        # the state cleared: resolved by itself
    assert [x["status"] for x in found(shop, code, "OOS1")] == ["resolved"]
    low = "inventory.low_stock"
    run(shop, low)
    [f] = open_ones(shop, low, "OOS1")
    assert f["severity"] == "low" and Dec(f["value"]) == 4 and Dec(f["expected_value"]) == 5
    assert "down to 4" in f["summary"] and "reorder level is 5" in f["summary"]
    adjust(client, shop, oos, "1")                                    # exactly at the level still counts
    run(shop, low)
    assert len(open_ones(shop, low, "OOS1")) == 1
    adjust(client, shop, oos, "1")
    run(shop, low)
    assert open_ones(shop, low, "OOS1") == []
    run(shop, code)
    assert open_ones(shop, code, "OOS1") == []


def test_out_of_stock_ignores_products_that_never_moved_and_those_without_a_reason_to_stock(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.out_of_stock"
    never = new_product(client, shop, "NEVER1", reorder_level="5")       # no movement anywhere
    plain = new_product(client, shop, "PLAIN1")                          # no reorder level, never sold
    opening(client, shop, plain, "3", "10")
    move(shop, plain, "-3", "transfer_out")
    run(shop, code)
    assert open_ones(shop, code, "NEVER1") == [] and open_ones(shop, code, "PLAIN1") == []
    assert never != plain


def test_out_of_stock_only_looks_back_as_far_as_its_window(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.out_of_stock"
    old = new_product(client, shop, "OLD1", reorder_level="5")
    opening(client, shop, old, "5", "10")
    move(shop, old, "-5", "sale", business_date=BASE - timedelta(days=100))
    run(shop, code, today=BASE + timedelta(days=80))                    # the last movement was 180 days ago... and 100+
    assert open_ones(shop, code, "OLD1") == []
    run(shop, code, today=BASE)
    # opened today and sold on a past date: today's opening movement keeps it in the window
    assert len(open_ones(shop, code, "OLD1")) == 1
    run(shop, code, today=BASE + timedelta(days=80))                    # the product is out of the window now: resolved
    assert open_ones(shop, code, "OLD1") == []
    tune(client, shop, code, days=200)
    run(shop, code, today=BASE + timedelta(days=80))
    assert len(open_ones(shop, code, "OLD1")) == 1                      # a longer window brings it back (reopened)
    tune(client, shop, code, days=60)


def test_negative_stock_has_the_value_at_stake_and_clears_when_fixed(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.negative_stock"
    neg = new_product(client, shop, "NEG1")
    opening(client, shop, neg, "5", "10")
    move(shop, neg, "-8", "sale", allow_negative=True)
    run(shop, code)
    [f] = open_ones(shop, code, "NEG1")
    assert (f["severity"], f["branch_id"], Dec(f["amount"]), Dec(f["value"])) == (
        "medium", shop["branch_id"], Dec("30.00"), Dec("-3"))
    assert "shows -3" in f["summary"] and f"{shop['currency']} 30.00" in f["summary"]
    assert open_ones(shop, code, "CEM") == [] and not any("PLAIN1" in x["summary"] for x in found(shop, code))
    adjust(client, shop, neg, "3")
    run(shop, code)
    assert open_ones(shop, code, "NEG1") == []


def set_expiry(shop, batch_no: str, day: date) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("update inventory.batch set expiry_date = :d where batch_no = :b"), {"d": day, "b": batch_no})


def test_batches_expiring_and_expired_with_stock_on_hand(client, shop) -> None:  # type: ignore[no-untyped-def]
    paint = shop["paint"]
    batches = (("B-GONE", "1", 2), ("B-URGENT", "2", 5), ("B-SOON", "4", 10), ("B-FAR", "6", 90), ("B-OLD", "3", 40))
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": paint, "quantity": q, "unit_cost": "25", "batch_no": no,
                   "expiry_date": (BASE + timedelta(days=days)).isoformat()} for no, q, days in batches]})
    assert r.status_code == 201, r.text
    sell_fefo(shop, paint, "1")                                    # first-expiry-first-out takes B-GONE
    set_expiry(shop, "B-OLD", BASE - timedelta(days=3))
    soon, gone = "inventory.batch_expiring", "inventory.batch_expired"
    run(shop, soon)
    run(shop, gone)
    by_batch = {b: open_ones(shop, soon, b) for b in ("B-GONE", "B-URGENT", "B-SOON", "B-FAR", "B-OLD")}
    assert [len(v) for v in by_batch.values()] == [0, 1, 1, 0, 0]
    urgent, near = by_batch["B-URGENT"][0], by_batch["B-SOON"][0]
    assert (urgent["severity"], Dec(urgent["amount"]), urgent["branch_id"]) == ("high", Dec("50.00"), shop["branch_id"])
    assert (near["severity"], Dec(near["amount"])) == ("medium", Dec("100.00"))
    assert "expires on " + format_day(BASE + timedelta(days=10)) in near["summary"] and "4 is still at" in near["summary"]
    assert ("inventory.batch" in {t for t, _ in records(near)}) and ("products.product", paint) in records(near)
    [old] = open_ones(shop, gone, "B-OLD")
    assert (old["severity"], Dec(old["amount"])) == ("high", Dec("75.00"))
    assert open_ones(shop, gone, "B-GONE") == [] and open_ones(shop, gone, "B-URGENT") == []
    # tuned: look 120 days ahead and the far batch is flagged too; a longer urgent period turns B-SOON high
    tune(client, shop, soon, days_ahead=120, urgent_days=14)
    run(shop, soon)
    assert len(open_ones(shop, soon, "B-FAR")) == 1
    assert open_ones(shop, soon, "B-SOON")[0]["severity"] == "high"
    tune(client, shop, soon, days_ahead=30, urgent_days=7)
    run(shop, soon)
    assert open_ones(shop, soon, "B-FAR") == []                          # beyond the window again: resolved
    # the stock of a flagged batch leaves: the finding goes
    sell_fefo(shop, paint, "5")                                      # the expired B-OLD (3), then B-URGENT (2)
    run(shop, soon)
    run(shop, gone)
    assert open_ones(shop, soon, "B-URGENT") == [] and open_ones(shop, gone, "B-OLD") == []


def test_slow_stock_needs_old_stock_of_real_value_with_nothing_going_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.slow_stock"
    dead, live, cheap = (new_product(client, shop, s) for s in ("DEAD1", "LIVE1", "CHEAP1"))
    opening(client, shop, dead, "10", "200")
    opening(client, shop, live, "10", "200")
    opening(client, shop, cheap, "10", "1")
    move(shop, live, "-1", "sale", business_date=BASE + timedelta(days=60))
    run(shop, code, today=BASE + timedelta(days=80))
    assert open_ones(shop, code, "DEAD1") == []                          # only 80 days old: not yet
    later = BASE + timedelta(days=120)
    run(shop, code, today=later)
    [f] = open_ones(shop, code, "DEAD1")
    assert (f["severity"], Dec(f["amount"]), f["branch_id"]) == ("low", Dec("2000.00"), shop["branch_id"])
    assert f"{shop['currency']} 2,000.00" in f["summary"] and "none has gone out since it arrived" in f["summary"]
    assert open_ones(shop, code, "LIVE1") == [] and open_ones(shop, code, "CHEAP1") == []   # sold lately / not worth it
    tune(client, shop, code, min_value="5")
    run(shop, code, today=later)
    assert len(open_ones(shop, code, "CHEAP1")) == 1
    tune(client, shop, code, min_value="1000", days=30)
    run(shop, code, today=later)
    assert len(open_ones(shop, code, "LIVE1")) == 1                      # last sold 60 days before: slow for 30
    tune(client, shop, code, min_value="1000", days=90)
    move(shop, dead, "-1", "sale", business_date=BASE + timedelta(days=119))
    run(shop, code, today=later)
    assert open_ones(shop, code, "DEAD1") == [] and open_ones(shop, code, "LIVE1") == []


def test_transfers_not_received_are_flagged_at_the_receiving_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.transfer_not_received"
    item = new_product(client, shop, "XFER1")
    opening(client, shop, item, "20", "100")
    t = client.post(f"{INV}/transfers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": item, "quantity": "5"}]}).json()
    run(shop, code)
    assert found(shop, code) == []                                       # a draft is not on the road
    assert client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=shop["owner"]).status_code == 200
    with system(shop) as s:
        sent = s.execute(text("select (dispatched_at at time zone 'UTC')::date from inventory.transfer where id = :i"),
                         {"i": t["id"]}).scalar_one()
    run(shop, code, today=sent + timedelta(days=2))
    assert found(shop, code) == []                                       # two days: within the three allowed
    run(shop, code, today=sent + timedelta(days=4))
    [f] = found(shop, code)
    assert (f["severity"], Dec(f["amount"]), f["branch_id"]) == ("medium", Dec("500.00"), shop["juja"])
    assert t["number"] in f["summary"] and "after 4 days" in f["summary"]
    assert records(f) == [("inventory.transfer", t["id"])]
    run(shop, code, today=sent + timedelta(days=10))
    assert found(shop, code)[0]["severity"] == "high"                    # waiting three times as long
    tune(client, shop, code, days=30)
    run(shop, code, today=sent + timedelta(days=10))
    assert found(shop, code)[0]["status"] == "resolved"                  # a longer allowance: no longer a problem
    tune(client, shop, code, days=3)
    run(shop, code, today=sent + timedelta(days=10))
    assert found(shop, code)[0]["status"] != "resolved"                  # and reopened when it returns
    assert client.post(f"{INV}/transfers/{t['id']}/receive", headers=shop["juja_keeper"]).status_code == 200
    run(shop, code, today=sent + timedelta(days=10))
    assert found(shop, code)[0]["status"] == "resolved"                  # received: closed


# --------------------------------------------------------------------------- controls
def test_large_write_downs_are_flagged_per_document(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.large_write_down"
    big, huge, small = (new_product(client, shop, s) for s in ("WD1", "WD2", "WD3"))
    for p in (big, huge, small):
        opening(client, shop, p, "100", "100")
    a_big, a_huge, a_small = adjust(client, shop, big, "-20"), adjust(client, shop, huge, "-50"), \
        adjust(client, shop, small, "-5")
    adjust(client, shop, big, "30")                                       # stock found is not a write-down
    run(shop, code)
    [f_big] = open_ones(shop, code, "Item WD1") or [None]
    mine = {x["summary"].split("(")[1].split(",")[0].strip(): x for x in found(shop, code) if "ADJ-" in x["summary"]}
    assert set(mine) >= {a_big["number"], a_huge["number"]} and a_small["number"] not in mine
    big_f, huge_f = mine[a_big["number"]], mine[a_huge["number"]]
    assert f_big is None
    assert (big_f["severity"], Dec(big_f["amount"]), big_f["branch_id"]) == ("medium", Dec("2000.00"), shop["branch_id"])
    assert (huge_f["severity"], Dec(huge_f["amount"])) == ("high", Dec("5000.00"))         # 5x the limit
    assert f"{shop['currency']} 2,000.00" in big_f["summary"] and "Theft or loss" in big_f["summary"]
    assert records(big_f) == [("inventory.stock_adjustment", a_big["id"])]
    # it is an event: it stays open long after, until a person deals with it
    run(shop, code, today=BASE + timedelta(days=60))
    assert {x["status"] for x in found(shop, code) if "ADJ-" in x["summary"]} <= {"new", "sent"}
    # a lower limit catches the small one
    tune(client, shop, code, value_limit="400", days=90)
    run(shop, code)
    assert any(a_small["number"] in x["summary"] for x in found(shop, code))
    tune(client, shop, code, value_limit="1000", days=14)


def test_shrinkage_compares_losses_with_what_moved(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.shrinkage_rate"
    sh = new_product(client, shop, "SH1")
    move(shop, sh, "100", "receipt", unit_cost=Dec("10"))
    move(shop, sh, "-50", "sale")                                          # 150 moved: 100 received + 50 sold
    adjust(client, shop, sh, "-10")                                        # 10 of 150 = 6.7%
    run(shop, code)
    assert open_ones(shop, code, "SH1") == []
    adjust(client, shop, sh, "-10")                                        # 20 of 150 = 13.3%
    run(shop, code)
    [f] = open_ones(shop, code, "SH1")
    assert (f["severity"], Dec(f["amount"]), Dec(f["value"]), Dec(f["expected_value"])) == (
        "medium", Dec("200.00"), Dec("13.3"), Dec("10.0"))
    assert f["branch_id"] == shop["branch_id"] and "13.3%" in f["summary"] and "of the 150 sold or received" in f["summary"]
    adjust(client, shop, sh, "-10")                                        # 30 of 150 = 20.0%: twice the limit
    run(shop, code)
    assert open_ones(shop, code, "SH1")[0]["severity"] == "high"
    assert len(found(shop, code, "SH1")) == 1                              # the same finding, made more serious
    tune(client, shop, code, percent="25.0")
    run(shop, code)
    assert open_ones(shop, code, "SH1") == []                              # within the business's own tolerance
    tune(client, shop, code, percent="10.0", min_loss_value="5000")
    run(shop, code)
    assert open_ones(shop, code, "SH1") == []                              # too little money to bother with
    tune(client, shop, code, min_loss_value="100")
    # a loss with nothing sold or received in the window is too little to judge
    lone = new_product(client, shop, "SH2")
    opening(client, shop, lone, "50", "100")
    adjust(client, shop, lone, "-10")
    run(shop, code)
    assert open_ones(shop, code, "SH2") == []


def count(client, shop, product: str, counted: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """A count of one product, finished and submitted with a reason."""
    h = shop["owner"]
    c = client.post(f"{INV}/counts", headers=h, json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "product_ids": [product]}).json()
    client.post(f"{INV}/counts/{c['id']}/entries", headers=h, json={"entries": [
        {"product_id": product, "counted_qty": counted}]})
    done = client.post(f"{INV}/counts/{c['id']}/finish", headers=h, json=None).json()
    reasons = [{"line_id": x["id"], "reason_code_id": str(shop["count_reason"])} for x in done["lines"]]
    r = client.post(f"{INV}/counts/{c['id']}/submit", headers=h, json={"reasons": reasons})
    assert r.status_code == 200 and r.json()["status"] == "posted", r.text
    return r.json()


def test_posted_counts_with_large_differences_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.count_variance"
    small, large = new_product(client, shop, "CV1"), new_product(client, shop, "CV2")
    opening(client, shop, small, "100", "10")
    opening(client, shop, large, "100", "100")
    c_small = count(client, shop, small, "80")                              # 20 short x 10 = 200
    c_large = count(client, shop, large, "50")                              # 50 short x 100 = 5000
    run(shop, code)
    hits = {x["summary"].split()[2]: x for x in found(shop, code)}
    assert c_small["number"] not in hits
    f = hits[c_large["number"]]
    assert (f["severity"], Dec(f["amount"]), f["branch_id"]) == ("high", Dec("5000.00"), shop["branch_id"])
    assert f"{shop['currency']} 5,000.00 short overall" in f["summary"] or "5,000.00" in f["summary"]
    assert "short overall" in f["summary"] and records(f) == [("inventory.stock_count", c_large["id"])]
    tune(client, shop, code, value_limit="100")
    run(shop, code)
    small_f = next(x for x in found(shop, code) if c_small["number"] in x["summary"])
    assert (small_f["severity"], Dec(small_f["amount"])) == ("medium", Dec("200.00"))
    tune(client, shop, code, value_limit="1000")
    # a count still being done, or cancelled, is not a posted difference
    pending = client.post(f"{INV}/counts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "product_ids": [small]}).json()
    run(shop, code)
    assert pending["number"] not in " ".join(x["summary"] for x in found(shop, code))
    client.post(f"{INV}/counts/{pending['id']}/cancel", headers=shop["owner"])


def test_stock_moves_at_odd_hours_or_back_dated(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "inventory.unusual_stock_moves"
    item = new_product(client, shop, "ODD1")
    opening(client, shop, item, "50", "100")
    doc = adjust(client, shop, item, "-2")                                  # worth 200, entered now, dated today
    nothing = {"hours_from": 0, "hours_to": 24, "backdate_days": 3, "min_value": "100"}
    tune(client, shop, code, **nothing)
    run(shop, code)
    assert [x for x in found(shop, code) if doc["number"] in x["summary"]] == []      # normal hours, dated today
    tune(client, shop, code, hours_from=0, hours_to=0)                      # every hour is "outside" the hours
    run(shop, code)
    [odd] = [x for x in found(shop, code) if doc["number"] in x["summary"]]
    assert (odd["severity"], Dec(odd["amount"]), odd["branch_id"]) == ("low", Dec("200.00"), shop["branch_id"])
    assert "outside the usual hours" in odd["summary"] and records(odd) == [("inventory.stock_adjustment", doc["id"])]
    tune(client, shop, code, **{**nothing, "min_value": "1000"})
    run(shop, code)
    # a movement entered now but dated ten days back, under the same adjustment
    move(shop, item, "1", "adjustment", source_type="stock_adjustment", source_id=UUID(doc["id"]),
         reason_code_id=shop["reason"], unit_cost=Dec("100"), business_date=BASE - timedelta(days=10))
    tune(client, shop, code, **nothing)
    run(shop, code)
    late = [x for x in found(shop, code) if doc["number"] in x["summary"] and "dated it" in x["summary"]]
    assert len(late) == 1 and late[0]["severity"] == "medium" and Dec(late[0]["amount"]) == 100
    assert "days earlier" in late[0]["summary"]
    tune(client, shop, code, **{**nothing, "backdate_days": 30})
    run(shop, code)                                                         # events stay once raised
    tune(client, shop, code, hours_from=6, hours_to=21, backdate_days=3, min_value="100")


@pytest.fixture(scope="module")
def spike_shop(client, registry):  # type: ignore[no-untyped-def]
    return prepare(client, registry, "Inv Spike Co")


def test_a_persons_unusual_removal_is_judged_against_their_own_history(client, spike_shop) -> None:  # type: ignore[no-untyped-def]
    shop = spike_shop
    code = "inventory.adjustment_spike"
    item = new_product(client, shop, "SPK1")
    opening(client, shop, item, "1000", "10")
    owner = shop["owner_id"]
    with system(shop) as s:
        for day in range(2, 22):                                            # 20 days of 100 or 120 taken out by hand
            value = 100 if day % 2 else 120
            s.execute(text(
                "insert into inventory.stock_movement (tenant_id, company_id, branch_id, location_id, product_id, "
                "quantity, unit_cost, value, movement_type, source_type, source_id, reason_code_id, business_date, "
                "created_by) values (:t, :c, :b, :l, :p, :q, 10, :v, 'write_off', 'test_seed', :s, :r, :d, :u)"),
                {"t": str(shop["tenant_id"]), "c": str(shop["company_id"]), "b": str(shop["branch_id"]),
                 "l": shop["main"], "p": item, "q": -value // 10, "v": -value, "s": str(uuid4()),
                 "r": str(shop["reason"]), "d": BASE - timedelta(days=day), "u": str(owner)})
    adjust(client, shop, item, "-200")                                      # 2000 today, against a norm of 110
    run(shop, code)
    assert found(shop, code) == []                                          # no baseline learned yet: say nothing
    with system(shop) as s:
        assert baselines.refresh_company(s, shop["company_id"], BASE, metrics=[AdjustmentValueByUser()]) >= 1
        learned = baselines.load(s, shop["company_id"]).get(AdjustmentValueByUser.code, str(owner))
    assert learned is not None and (learned.mean, learned.stddev, learned.p95, learned.sample_size) == (
        Dec(110), Dec(10), Dec(120), 20)
    run(shop, code)
    [f] = found(shop, code)
    assert (f["severity"], Dec(f["amount"]), f["branch_id"]) == ("medium", Dec("2000.00"), None)
    assert "usually about" in f["summary"] and f"{shop['currency']} 110.00" in f["summary"]
    assert records(f) == [("kernel.app_user", str(owner))]
    tune(client, shop, code, min_value="5000")
    other = found(shop, code)
    assert len(other) == 1                                                  # still there: a raised event stays
    tune(client, shop, code, min_value="500")


def test_a_quiet_day_is_normal_for_a_person_with_history(client, spike_shop) -> None:  # type: ignore[no-untyped-def]
    shop = spike_shop
    code = "inventory.adjustment_spike"
    before = len(found(shop, code))
    run(shop, code, today=BASE + timedelta(days=1))                         # tomorrow: nothing was taken out
    assert len(found(shop, code)) == before


# --------------------------------------------------------------------------- Command Center figures
def test_pulse_figures_company_wide_and_per_branch(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = prepare(client, registry, "Inv Pulse Co")
    a = new_product(client, shop, "PA", reorder_level="10")
    b = new_product(client, shop, "PB", reorder_level="5")
    c = new_product(client, shop, "PC")
    d = new_product(client, shop, "PD")
    opening(client, shop, a, "8", "100")                                    # HQ: 8 x 100, under its reorder level
    opening(client, shop, b, "4", "50")                                     # HQ: sold out below
    move(shop, b, "-4", "sale")
    opening(client, shop, c, "20", "30", place="juja_store")                # Juja: 20 x 30
    opening(client, shop, d, "3", "10", place="juja_store")
    move(shop, d, "-5", "sale", place="juja_store", allow_negative=True)    # Juja: -2 of D
    adjust(client, shop, a, "-2")                                           # 200 taken out at HQ today
    adjust(client, shop, c, "-1", place="juja_store")                       # 30 taken out at Juja today
    t = client.post(f"{INV}/transfers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": a, "quantity": "3"}]}).json()
    assert client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=shop["owner"]).status_code == 200

    with system(shop) as s:
        assert "inventory" in {u for u, _ in extensions._points[COMMAND_PULSE_SOURCE].implementations}
        figures = InventoryPulse().figures(s, shop["company_id"], BASE)
    assert len(figures) == 18                                                # 6 figures: company, HQ and Juja
    got = {(f.metric, f.branch_id): f.value for f in figures}
    kinds = {f.metric: f.kind for f in figures}
    hq, juja = shop["branch_id"], shop["juja"]
    expected = {
        # A: 6 left after the adjustment (value 600), 3 of them sent on; C: 19 x 30 = 570; D: -2 x 10 = -20
        "inventory.stock_value": {None: 1150, hq: 300, juja: 550},          # company includes the 300 in transit
        "inventory.below_reorder": {None: 1, hq: 1, juja: 0},               # A (3 on hand, level 10)
        "inventory.out_of_stock": {None: 1, hq: 1, juja: 0},                # B sold out at HQ
        "inventory.negative_stock": {None: 1, hq: 0, juja: 1},              # D at Juja
        "inventory.adjustments_value": {None: 230, hq: 200, juja: 30},
        "inventory.transfers_in_transit": {None: 1, hq: 0, juja: 1},
    }
    for metric, scopes in expected.items():
        for branch, value in scopes.items():
            assert got[(metric, branch)] == value, (metric, branch, got[(metric, branch)])
    assert kinds["inventory.stock_value"] == "money" and kinds["inventory.below_reorder"] == "count"
    # another day has no adjustments yet, but the same stock
    with system(shop) as s:
        tomorrow = {(f.metric, f.branch_id): f.value
                    for f in InventoryPulse().figures(s, shop["company_id"], BASE + timedelta(days=1))}
    assert tomorrow[("inventory.adjustments_value", None)] == 0 and tomorrow[("inventory.stock_value", hq)] == 300


def test_the_checks_are_registered_with_their_area_and_description(client, shop) -> None:  # type: ignore[no-untyped-def]
    listed = {c["code"]: c for c in client.get(f"{INTEL}/checks", headers=shop["owner"]).json()}
    mine = {c for c in listed if c.startswith("inventory.")}
    assert mine == {"inventory.out_of_stock", "inventory.low_stock", "inventory.negative_stock",
                    "inventory.batch_expiring", "inventory.batch_expired", "inventory.slow_stock",
                    "inventory.transfer_not_received", "inventory.large_write_down", "inventory.shrinkage_rate",
                    "inventory.count_variance", "inventory.unusual_stock_moves", "inventory.adjustment_spike"}
    assert {listed[c]["area"] for c in mine} == {"stock", "controls"}
    assert all(listed[c]["description"] for c in mine)
