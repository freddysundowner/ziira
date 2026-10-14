"""POS's Intelligence checks and Command Center figures, run through the real engine on a real shop.

History (weeks of sales, old invoices) is written straight into POS's tables, because it must be dated in the past;
the day-to-day flow (a till opened, sold from and closed with a difference) goes through the API.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.pos_helpers import POS, credit_customer, line, make_pos_shop, make_sales_shop, open_till, sell
from tests.stock_helpers import system
from ziira.modules.command.services import pulse
from ziira.modules.intel.services import baselines, engine

INTEL = "/api/v1/intel"
TODAY = date(2026, 10, 14)
YESTERDAY = TODAY - timedelta(days=1)
OPEN_STATUSES = ["new", "sent", "acknowledged", "explained"]


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401 - define the sockets
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.pos.hooks  # noqa: F401

    s = make_sales_shop(client, registry, "Pos Intel Co")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    for key, code, location in (("juja_device", "J1", s["juja_store"]),):
        r = client.post(f"{POS}/devices", headers=s["owner"], json={
            "branch_id": str(s["juja"]), "code": code, "name": "Juja counter", "location_id": location})
        assert r.status_code == 201, r.text
        s[key] = r.json()["id"]
    return s


# --------------------------------------------------------------------------- helpers
def uid(shop, name: str) -> UUID:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return UUID(str(s.execute(text("select id from kernel.app_user where full_name = :n"), {"n": name}).scalar_one()))


def cashier(shop, name: str) -> UUID:  # type: ignore[no-untyped-def]
    shop["user"](name, "Cashier", shop["branch_id"])
    return uid(shop, name)


def new_branch(shop, code: str) -> UUID:  # type: ignore[no-untyped-def]
    branch = uuid4()
    with system(shop) as s:
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) values (:i, :t, :c, :k, :n)"),
                  {"i": str(branch), "t": str(shop["tenant_id"]), "c": str(shop["company_id"]), "k": code,
                   "n": f"Branch {code}"})
    return branch


def bulk_sales(shop, who: UUID, prefix: str, start: date, days: int, per_day: int, *, voided: int = 0,  # type: ignore[no-untyped-def]
               total: str = "116.00", branch: Any = None, list_price: str | None = None, unit_price: str = "116.00",
               discount: str = "0") -> None:
    """`per_day` sales a day for `days` days from `start` (the first `voided` of each day voided), each with one line."""
    with system(shop) as s:
        s.execute(text("""
            insert into pos.sale (tenant_id, company_id, branch_id, number, local_id, cashier_id, business_date, sold_at,
                subtotal, discount_total, tax_total, total, paid_total, status, voided_by, voided_at,
                void_reason_code_id, created_at)
            select kernel.current_tenant(), cast(:co as uuid), cast(:br as uuid), :p || '-' || d || '-' || n,
                gen_random_uuid(), cast(:who as uuid), cast(:start as date) + d,
                (cast(:start as timestamp) + d * interval '1 day' + interval '10 hours') at time zone 'UTC',
                :t, 0, 0, :t, :t, case when n <= :v then 'voided' else 'posted' end,
                case when n <= :v then cast(:who as uuid) end,
                case when n <= :v then (cast(:start as timestamp) + d * interval '1 day' + interval '10 hours 5 minutes')
                     at time zone 'UTC' end,
                case when n <= :v then cast(:reason as uuid) end,
                (cast(:start as timestamp) + d * interval '1 day' + interval '12 hours') at time zone 'UTC'
            from generate_series(0, :days - 1) d, generate_series(1, :per) n"""),
            {"co": str(shop["company_id"]), "br": str(branch or shop["branch_id"]), "p": prefix, "who": str(who),
             "start": start, "t": total, "v": voided, "days": days, "per": per_day,
             "reason": shop["reasons"]["void"]})
        s.execute(text("""
            insert into pos.sale_line (tenant_id, sale_id, line_no, product_id, uom_id, quantity, list_price, unit_price,
                discount_amount, tax_code_id, tax_amount, line_total)
            select kernel.current_tenant(), id, 1, cast(:prod as uuid), cast(:uom as uuid), 1, cast(:lp as numeric),
                cast(:up as numeric), cast(:disc as numeric), cast(:tax as uuid), 0, cast(:up as numeric) - cast(:disc as numeric)
            from pos.sale where number like :p || '-%'"""),
            {"prod": shop["cement"], "uom": shop["uom"], "tax": shop["tax"], "lp": list_price or unit_price,
             "up": unit_price, "disc": discount, "p": prefix})


def raw_sale(shop, number: str, who: UUID, day: date, sold_at: str, total: str, *, branch: Any = None,  # type: ignore[no-untyped-def]
             status: str = "posted", created_at: str | None = None, offline: bool = False, voided_at: str | None = None,
             lines: tuple[str, str, str] | None = None) -> UUID:
    """One sale. `lines` is (list price, unit price, discount) of its single line."""
    sale = uuid4()
    with system(shop) as s:
        s.execute(text("""
            insert into pos.sale (id, tenant_id, company_id, branch_id, number, local_id, cashier_id, business_date, sold_at,
                subtotal, discount_total, tax_total, total, paid_total, status, voided_by, voided_at, void_reason_code_id,
                synced_offline, created_at)
            values (:id, kernel.current_tenant(), :co, :br, :n, gen_random_uuid(), :who, :day, cast(:at as timestamptz),
                :t, 0, 0, :t, :t, :st, case when :st = 'voided' then cast(:who as uuid) end,
                case when :st = 'voided' then cast(:vat as timestamptz) end,
                case when :st = 'voided' then cast(:reason as uuid) end, :off, cast(:cr as timestamptz))"""),
                  {"id": str(sale), "co": str(shop["company_id"]), "br": str(branch or shop["branch_id"]), "n": number,
                   "who": str(who), "day": day, "at": sold_at, "t": total, "st": status, "off": offline,
                   "vat": voided_at or sold_at, "reason": shop["reasons"]["void"], "cr": created_at or sold_at})
        if lines:
            s.execute(text("""
                insert into pos.sale_line (tenant_id, sale_id, line_no, product_id, uom_id, quantity, list_price, unit_price,
                    discount_amount, tax_code_id, tax_amount, line_total)
                values (kernel.current_tenant(), :s, 1, :p, :u, 1, :lp, :up, :d, :tax, 0, :lt)"""),
                      {"s": str(sale), "p": shop["cement"], "u": shop["uom"], "tax": shop["tax"], "lp": lines[0],
                       "up": lines[1], "d": lines[2], "lt": Dec(lines[1]) - Dec(lines[2])})
    return sale


def raw_return(shop, number: str, sale: UUID, day: date, total: str, who: UUID, status: str = "posted") -> UUID:  # type: ignore[no-untyped-def]
    ret = uuid4()
    with system(shop) as s:
        s.execute(text("""
            insert into pos.sales_return (id, tenant_id, company_id, branch_id, number, original_sale_id, reason_code_id,
                refund_method, total, status, business_date, net, tax, created_by)
            values (:id, kernel.current_tenant(), :co, :br, :n, :sale, :reason, 'cash', :t, :st, :day, :t, 0, :who)"""),
                  {"id": str(ret), "co": str(shop["company_id"]), "br": str(shop["branch_id"]), "n": number,
                   "sale": str(sale), "reason": shop["reasons"]["sale_return"], "t": total, "st": status, "day": day,
                   "who": str(who)})
    return ret


def raw_till(shop, who: UUID, day: date, *, status: str = "closed", variance: str | None = None, branch: Any = None,  # type: ignore[no-untyped-def]
             device: str | None = None, expected: str = "1000.00") -> UUID:
    till = uuid4()
    counted = None if variance is None else str(Dec(expected) + Dec(variance))
    with system(shop) as s:
        s.execute(text("""
            insert into pos.till_session (id, tenant_id, branch_id, device_id, cash_account_id, cashier_id, business_date,
                opened_at, opening_float, closed_at, expected_cash, counted_cash, variance, status)
            values (:id, kernel.current_tenant(), :br, :dev, :cash, :who, :day, cast(:day as timestamptz), 0,
                case when :st = 'closed' then cast(:day as timestamptz) end, :ex, :ct, :var, :st)"""),
                  {"id": str(till), "br": str(branch or shop["branch_id"]), "dev": device or shop["device"],
                   "cash": shop["cash"], "who": str(who), "day": day, "st": status,
                   "ex": expected if status == "closed" else None, "ct": counted, "var": variance})
    return till


def raw_invoice(shop, number: str, customer: Any, issue: date, due: date, total: str, *, paid: str = "0",  # type: ignore[no-untyped-def]
                status: str = "issued", branch: Any = "HQ", created_at: str | None = None) -> UUID:
    invoice = uuid4()
    with system(shop) as s:
        s.execute(text("""
            insert into pos.sales_invoice (id, tenant_id, company_id, branch_id, number, customer_id, issue_date, due_date,
                subtotal, tax_total, total, amount_paid, status, created_at)
            values (:id, kernel.current_tenant(), :co, :br, :n, :cu, :iss, :due, :t, 0, :t, :paid, :st,
                cast(coalesce(:cr, cast(:iss as text)) as timestamptz))"""),
                  {"id": str(invoice), "co": str(shop["company_id"]),
                   "br": str(shop["branch_id"]) if branch == "HQ" else (str(branch) if branch else None),
                   "n": number, "cu": str(customer), "iss": issue, "due": due, "t": total, "paid": paid, "st": status,
                   "cr": created_at})
    return invoice


def raw_receipt(shop, number: str, customer: Any, invoice: UUID | None, received: date, amount: str,  # type: ignore[no-untyped-def]
                unallocated: str = "0") -> None:
    receipt = uuid4()
    with system(shop) as s:
        s.execute(text("""
            insert into pos.customer_receipt (id, tenant_id, company_id, number, customer_id, method, amount, received_on,
                unallocated)
            values (:id, kernel.current_tenant(), :co, :n, :cu, 'cash', :a, :d, :un)"""),
                  {"id": str(receipt), "co": str(shop["company_id"]), "n": number, "cu": str(customer), "a": amount,
                   "d": received, "un": unallocated})
        if invoice is not None:
            s.execute(text("""
                insert into pos.customer_receipt_allocation (tenant_id, receipt_id, invoice_id, amount)
                values (kernel.current_tenant(), :r, :i, :a)"""), {"r": str(receipt), "i": str(invoice), "a": amount})


def run(shop, *codes: str, today: date = TODAY):  # type: ignore[no-untyped-def]
    """Learn the baselines, then run the named checks for the company."""
    with system(shop) as s:
        baselines.refresh_company(s, shop["company_id"], today)
        return engine.run_company(s, shop["company_id"], today=today, only=set(codes))


def found(client, shop, code: str, *, resolved: bool = False) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params={
        "check_code": code, "status": ["resolved"] if resolved else OPEN_STATUSES, "limit": 50})
    assert r.status_code == 200, r.text
    return list(r.json())


def detail(client, shop, finding: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings/{finding['id']}", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return dict(r.json())


def tune(client, shop, code: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


@contextmanager
def tuned(client, shop, code: str, **params: Any) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Change a check's limits for the length of the block, then put the defaults back."""
    defaults = next(c for c in client.get(f"{INTEL}/checks", headers=shop["owner"]).json() if c["code"] == code)
    tune(client, shop, code, **params)
    try:
        yield
    finally:
        tune(client, shop, code, **{k: v for k, v in _defaults(defaults).items() if k in params})


def _defaults(check: dict[str, Any]) -> dict[str, Any]:
    return dict(check["defaults"])


def about(items: list[dict[str, Any]], entity: UUID | str) -> list[dict[str, Any]]:
    return [f for f in items if str(f["entity_id"]) == str(entity)]


# --------------------------------------------------------------------------- till differences
def test_a_till_closed_far_from_its_expected_cash_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.till_cash_variance"
    who = cashier(shop, "tilly")
    short = raw_till(shop, who, date(2026, 10, 10), variance="-600.00")
    way_short = raw_till(shop, who, date(2026, 10, 11), variance="-3000.00")
    small = raw_till(shop, who, date(2026, 10, 12), variance="100.00")
    old = raw_till(shop, who, date(2026, 8, 1), variance="-9999.00")
    still_open = raw_till(shop, who, date(2026, 10, 13), status="open", device=shop["devices"]["manager"])
    assert run(shop, code).created == 2
    items = found(client, shop, code)
    assert {f["entity_id"] for f in items} == {str(short), str(way_short)}      # not the small, old or open ones
    assert not about(items, small) and not about(items, old) and not about(items, still_open)
    f = about(items, short)[0]
    assert (f["severity"], Dec(f["amount"]), f["branch_id"], Dec(f["value"])) == ("medium", Dec("600.00"),
                                                                                  str(shop["branch_id"]), Dec("-600.00"))
    assert "tilly's till at Head office on 2026-10-10 closed KES 600.00 short" in f["summary"]
    assert "KES 400.00 counted against KES 1,000.00 expected" in f["summary"]
    assert about(items, way_short)[0]["severity"] == "high" and Dec(about(items, way_short)[0]["amount"]) == 3000
    assert detail(client, shop, f)["records"][0]["type"] == "pos.till_session"
    # an event stays until a person deals with it; the same till is never reported twice
    assert run(shop, code).created == 0 and len(found(client, shop, code)) == 2
    # the business can tighten the limit
    with tuned(client, shop, code, limit="50.00"):
        assert run(shop, code).created == 1
        assert about(found(client, shop, code), small)[0]["severity"] == "medium"
    # a limit only matters on a later run: this one finds nothing more
    assert run(shop, code).created == 0


def test_a_real_till_closed_short_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    """The whole way: open a till, sell, count the drawer wrongly, close it - and the check sees it."""
    who = shop["user"]("tess", "Cashier", shop["branch_id"])
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": "TESS", "name": "Tess", "location_id": shop["main"]}).json()
    shop["tess"] = who
    shop["devices"]["tess"] = dev["id"]
    till = open_till(client, shop, "tess", float_="1000.00").json()["id"]
    assert sell(client, shop, who="tess", till=till, lines=[line(shop, "cement", "1")],
                payments=[{"method": "cash", "amount": "116.00"}]).status_code == 201
    closed = client.post(f"{POS}/tills/{till}/close", headers=who, json={
        "counted_cash": "400.00", "reason_code_id": shop["reasons"]["till_variance"]})
    assert closed.status_code == 200, closed.text
    business_date = date.fromisoformat(client.get(f"{POS}/tills/{till}", headers=shop["owner"]).json()["business_date"])
    run(shop, "pos.till_cash_variance", today=business_date + timedelta(days=1))
    [f] = about(found(client, shop, "pos.till_cash_variance"), till)
    assert Dec(f["amount"]) == Dec("716.00") and f["severity"] == "medium"          # 400 counted against 1,116 expected
    assert "KES 716.00 short" in f["summary"]


# --------------------------------------------------------------------------- cashier habits
def test_cashier_void_refund_and_discount_rates_against_their_own_normal(client, shop) -> None:  # type: ignore[no-untyped-def]
    vera, wim, xena, yuri = (cashier(shop, n) for n in ("vera", "wim", "xena", "yuri"))
    history = date(2026, 9, 20)                                    # twenty days, up to 9 October
    for n, who in (("v", vera), ("w", wim), ("x", xena)):
        bulk_sales(shop, who, f"{n}h", history, 20, 6, voided=1 if n == "w" else 0)
    # vera: yesterday 6 sales, 3 voided (6 x 116 ...), 3 posted with 40 off each, and a 300 return
    bulk_sales(shop, vera, "vy", YESTERDAY, 1, 6, voided=3, list_price="116.00", unit_price="116.00", discount="40.00")
    refunded_sale = raw_sale(shop, "VRET-1", vera, YESTERDAY, "2026-10-13T11:00:00Z", "116.00")
    raw_return(shop, "RET-V1", refunded_sale, YESTERDAY, "300.00", vera)
    bulk_sales(shop, wim, "wy", YESTERDAY, 1, 6, voided=1)         # wim: one void in six, as always
    bulk_sales(shop, xena, "xy", YESTERDAY, 1, 2, voided=2)        # xena: two sales, both voided - too few to judge
    bulk_sales(shop, yuri, "yy", YESTERDAY, 1, 6, voided=6)        # yuri: all voided, but no history at all
    codes = ("pos.cashier_void_rate", "pos.cashier_refund_rate", "pos.cashier_discount_rate")
    run(shop, *codes)

    [void] = found(client, shop, codes[0])
    assert void["entity_id"] == str(vera) and void["severity"] == "medium" and void["branch_id"] == str(shop["branch_id"])
    assert round(Dec(void["value"]), 4) == round(Dec(3) / Dec(7), 4)                          # 3 voided of 7 sales
    assert Dec(void["amount"]) == Dec("348.00")                                                # 3 voided x 116
    assert f"On {YESTERDAY} vera's void rate was 43% over 7 sales (KES 348.00)" in void["summary"]
    assert detail(client, shop, void)["records"][0]["label"] == "vera"
    # vera's posted value: 3 sales + the one sold to return = 4 x 116 = 464, and she returned 300
    [refund] = found(client, shop, codes[1])
    assert refund["entity_id"] == str(vera) and Dec(refund["amount"]) == Dec("300.00")
    assert round(Dec(refund["value"]), 4) == round(Dec(300) / Dec(464), 4)                     # 65%
    [discount] = found(client, shop, codes[2])
    assert discount["entity_id"] == str(vera) and Dec(discount["amount"]) == Dec("120.00")     # 3 posted lines x 40
    assert round(Dec(discount["value"]), 4) == round(Dec(120) / Dec(3 * 116), 4)               # of 3 lines at 116
    # nobody else: wim is as usual, xena had too few sales, yuri has no history
    assert {f["entity_id"] for c in codes for f in found(client, shop, c)} == {str(vera)}
    # the events stay and are not duplicated
    assert run(shop, *codes).created == 0
    # tuned: judging a day with only two sales flags xena, who always sells six
    with tuned(client, shop, codes[0], min_sales=2):
        run(shop, codes[0])
        assert [f["entity_id"] for f in found(client, shop, codes[0])].count(str(xena)) == 1


# --------------------------------------------------------------------------- one big void, refund or override
def test_a_single_large_void_refund_or_override(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.large_exception"
    who = cashier(shop, "lars")
    day = date(2026, 10, 12)
    void_mid = raw_sale(shop, "LV-1", who, day, "2026-10-12T09:00:00Z", "2500.00", status="voided")
    void_big = raw_sale(shop, "LV-2", who, day, "2026-10-12T09:10:00Z", "7000.00", status="voided")
    void_small = raw_sale(shop, "LV-3", who, day, "2026-10-12T09:20:00Z", "500.00", status="voided")
    void_old = raw_sale(shop, "LV-4", who, date(2026, 9, 1), "2026-09-01T09:00:00Z", "9000.00", status="voided")
    base = raw_sale(shop, "LV-5", who, day, "2026-10-12T10:00:00Z", "100.00")
    ret = raw_return(shop, "RET-L1", base, day, "2500.00", who)
    raw_return(shop, "RET-L2", base, day, "300.00", who)                                  # small
    raw_return(shop, "RET-L3", base, day, "9000.00", who, status="draft")                # not posted
    over_mid = raw_sale(shop, "LV-6", who, day, "2026-10-12T11:00:00Z", "1000.00", lines=("2500.00", "1000.00", "0.00"))
    over_big = raw_sale(shop, "LV-7", who, day, "2026-10-12T11:10:00Z", "1000.00", lines=("5000.00", "5000.00", "4000.00"))
    raw_sale(shop, "LV-8", who, day, "2026-10-12T11:20:00Z", "900.00", lines=("1000.00", "1000.00", "100.00"))
    assert run(shop, code).created == 5
    items = found(client, shop, code)
    by_entity = {f["entity_id"]: f for f in items}
    assert set(by_entity) == {str(x) for x in (void_mid, void_big, ret, over_mid, over_big)}
    assert not {str(void_small), str(void_old)} & set(by_entity)
    assert (by_entity[str(void_mid)]["severity"], Dec(by_entity[str(void_mid)]["amount"])) == ("medium", Dec("2500.00"))
    assert by_entity[str(void_big)]["severity"] == "high"                                  # 7,000 >= 3 x 2,000
    assert "Sale LV-1 for KES 2,500.00 by lars was voided by lars on 2026-10-12" in by_entity[str(void_mid)]["summary"]
    assert by_entity[str(ret)]["severity"] == "medium" and "Return RET-L1 refunded KES 2,500.00" in by_entity[str(ret)]["summary"]
    assert Dec(by_entity[str(over_mid)]["amount"]) == Dec("1500.00")                      # list 2,500 sold at 1,000
    assert by_entity[str(over_mid)]["severity"] == "medium"
    assert Dec(by_entity[str(over_big)]["amount"]) == Dec("4000.00") and by_entity[str(over_big)]["severity"] == "high"
    assert all(f["branch_id"] == str(shop["branch_id"]) for f in items)
    assert detail(client, shop, by_entity[str(ret)])["records"][0]["type"] == "pos.sales_return"
    with tuned(client, shop, code, min_void="400.00"):
        assert run(shop, code).created == 1                                                 # the 500 void
    assert str(void_small) in {f["entity_id"] for f in found(client, shop, code)}


# --------------------------------------------------------------------------- outside trading hours
def test_sales_outside_trading_hours_are_judged_in_the_companys_time_zone(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.out_of_hours_sales"
    who = cashier(shop, "otto2")
    hq, juja = new_branch(shop, "OHA"), new_branch(shop, "OHB")
    company = shop["company_id"]
    assert client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"],
                        json={"timezone": "Asia/Tokyo"}).status_code == 200                  # UTC+9
    try:
        # HQ: 03:00 Tokyo on 14 Oct (= 18:00 UTC on the 13th) and 23:10 Tokyo (14:10 UTC); noon Tokyo is normal
        raw_sale(shop, "OH-1", who, YESTERDAY, "2026-10-13T18:00:00Z", "100.00", branch=hq)
        raw_sale(shop, "OH-2", who, TODAY, "2026-10-14T14:10:00Z", "132.00", branch=hq)
        raw_sale(shop, "OH-3", who, TODAY, "2026-10-14T03:00:00Z", "999.00",
                 branch=hq)                                                                      # noon in Tokyo
        raw_sale(shop, "OH-4", who, TODAY, "2026-10-14T15:00:00Z", "999.00", status="voided",
                 branch=hq)                                                                      # voided: not counted
        for n in range(5):                                                                     # Juja: 05:00 Tokyo x 5
            raw_sale(shop, f"OH-J{n}", who, TODAY, f"2026-10-13T20:0{n}:00Z", "50.00", branch=juja)
        run(shop, code)                       # (the real-time sale of another test may add a finding of its own)
        items = found(client, shop, code)
        first = next(f for f in items if f["branch_id"] == str(hq))
        jj = next(f for f in items if f["branch_id"] == str(juja))
        assert (first["severity"], Dec(first["amount"]), Dec(first["value"]), first["period_start"]) == (
            "low", Dec("232.00"), Dec(2), "2026-10-14")
        assert "Branch OHA made 2 sales worth KES 232.00 on 2026-10-14 outside 06:00-22:00, the first at 03:00" in first["summary"]
        assert (jj["severity"], Dec(jj["amount"])) == ("medium", Dec("250.00"))              # five sales
        assert [r["label"] for r in detail(client, shop, first)["records"]] == ["Sale OH-1", "Sale OH-2"]
        # an earlier opening hour makes the 03:00 sale normal; the day's finding is the same one, now smaller
        with tuned(client, shop, code, open_hour=3):
            run(shop, code)
            assert Dec(next(f for f in found(client, shop, code) if f["id"] == first["id"])["amount"]) == Dec("132.00")
    finally:
        client.patch(f"/api/v1/companies/{company}/settings", headers=shop["owner"], json={"timezone": "UTC"})


# --------------------------------------------------------------------------- recorded late
def test_sales_recorded_long_after_their_business_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.late_recorded_sales"
    who = cashier(shop, "lena")
    late_week = raw_sale(shop, "LR-1", who, date(2026, 10, 5), "2026-10-05T10:00:00Z", "300.00", offline=True,
                         created_at="2026-10-13T08:00:00Z")
    late_days = raw_sale(shop, "LR-2", who, date(2026, 10, 10), "2026-10-10T10:00:00Z", "200.00",
                         created_at="2026-10-13T08:00:00Z")
    raw_sale(shop, "LR-3", who, date(2026, 10, 12), "2026-10-12T22:00:00Z", "100.00", created_at="2026-10-13T08:00:00Z")
    raw_sale(shop, "LR-4", who, date(2026, 10, 13), "2026-10-13T10:00:00Z", "100.00")        # same day
    raw_sale(shop, "LR-5", who, date(2026, 9, 1), "2026-09-01T10:00:00Z", "100.00", created_at="2026-09-20T08:00:00Z")
    assert run(shop, code).created == 2
    items = found(client, shop, code)
    by_entity = {f["entity_id"]: f for f in items}
    assert set(by_entity) == {str(late_week), str(late_days)}
    week = by_entity[str(late_week)]
    assert (week["severity"], Dec(week["amount"]), Dec(week["value"])) == ("medium", Dec("300.00"), Dec(8))
    assert "Sale LR-1 by lena for KES 300.00 is dated 2026-10-05 but was synced from an offline till on 2026-10-13, 8 days later" \
        in week["summary"]
    assert by_entity[str(late_days)]["severity"] == "low" and "was entered on 2026-10-13, 3 days later" in \
        by_entity[str(late_days)]["summary"]
    with tuned(client, shop, code, min_days_late=1):
        assert run(shop, code).created == 1                                                  # LR-3, one day late


# --------------------------------------------------------------------------- a branch far below its normal
def test_a_branch_selling_far_less_than_it_usually_does_that_weekday(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.branch_sales_low"
    who = cashier(shop, "bella")
    assert YESTERDAY.weekday() == 1                                                        # a Tuesday
    tuesdays = [YESTERDAY - timedelta(days=7 * k) for k in range(1, 9)]                    # eight earlier ones
    hq, juja, newb, shut = (new_branch(shop, c) for c in ("BLHQ", "BLB", "NEWB", "SHUT"))
    values = ["1000", "1100", "900", "1000", "1050", "950", "1000", "1000"]
    n = 0

    def sale(branch, day: date, total: str) -> None:  # type: ignore[no-untyped-def]
        nonlocal n
        n += 1
        raw_sale(shop, f"BL-{n}", who, day, f"{day}T10:00:00Z", total, branch=branch)

    for day, v in zip(tuesdays, values, strict=True):
        sale(hq, day, v)
        sale(juja, day, "1000")
        sale(shut, day, "1000")
    for day in tuesdays[:3]:
        sale(newb, day, "1000")                                                             # too little history
    sale(hq, YESTERDAY, "300")                                                               # far below usual
    sale(juja, YESTERDAY, "800")                                                             # a bit below: normal
    assert run(shop, code).created == 2                                                      # HQ and the closed branch
    items = found(client, shop, code)
    low = next(f for f in items if f["branch_id"] == str(hq))
    assert (low["severity"], Dec(low["value"])) == ("medium", Dec(300))
    # the range the engine learned includes yesterday: (8,000 + 300) / 9
    assert abs(Dec(low["expected_value"]) - Dec("922.22")) < Dec("0.01")
    assert abs(Dec(low["amount"]) - Dec("622.22")) < Dec("0.01")
    assert "Branch BLHQ sold KES 300.00 on 2026-10-13 (Tuesday); it usually sells about KES 922.22 on that day" in low["summary"]
    zero = next(f for f in items if f["branch_id"] == str(shut))
    assert zero["severity"] == "high" and Dec(zero["value"]) == 0 and Dec(zero["amount"]) == Dec("1000.00")
    assert not [f for f in items if f["branch_id"] in (str(juja), str(newb))]
    with tuned(client, shop, code, min_history=3):
        assert run(shop, code).created == 1                                                  # the new branch now counts
    with tuned(client, shop, code, drop_percent=90):
        assert run(shop, code).created == 0


# --------------------------------------------------------------------------- what customers owe
def test_overdue_customers_one_finding_each_and_it_closes_when_they_pay(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.customer_overdue"
    alpha = credit_customer(client, shop, "Alpha Traders")["id"]
    beta = credit_customer(client, shop, "Beta Ltd")["id"]
    gamma = credit_customer(client, shop, "Gamma Stores")["id"]
    delta = credit_customer(client, shop, "Delta Mart")["id"]
    a1 = raw_invoice(shop, "OD-A1", alpha, date(2026, 7, 1), date(2026, 8, 1), "1000.00", paid="200.00", status="part_paid")
    a2 = raw_invoice(shop, "OD-A2", alpha, date(2026, 9, 1), date(2026, 9, 30), "500.00")
    raw_invoice(shop, "OD-B1", beta, date(2026, 5, 1), date(2026, 6, 1), "400.00")
    raw_invoice(shop, "OD-G1", gamma, date(2026, 9, 15), date(2026, 10, 1), "900.00")          # 13 days overdue
    raw_invoice(shop, "OD-D1", delta, date(2026, 5, 1), date(2026, 6, 1), "700.00", paid="700.00", status="paid")
    raw_invoice(shop, "OD-D2", delta, date(2026, 5, 1), date(2026, 6, 1), "700.00", status="cancelled")
    assert run(shop, code).created == 2
    items = found(client, shop, code)
    by_entity = {f["entity_id"]: f for f in items}
    assert set(by_entity) == {alpha, beta}
    a, b = by_entity[alpha], by_entity[beta]
    assert (a["severity"], Dec(a["amount"]), a["branch_id"]) == ("medium", Dec("1300.00"), str(shop["branch_id"]))   # 800 + 500
    assert "Alpha Traders owes KES 1,300.00 past due on 2 invoices; the oldest is 74 days overdue." in a["summary"]
    assert (b["severity"], Dec(b["amount"])) == ("high", Dec("400.00"))                        # 135 days
    assert [r["label"] for r in detail(client, shop, a)["records"]] == ["Invoice OD-A1", "Invoice OD-A2"]
    # paying clears it by itself, and the debt coming back reopens the same finding
    with system(shop) as s:
        s.execute(text("update pos.sales_invoice set amount_paid = total, status = 'paid' where id in (:a, :b)"),
                  {"a": str(a1), "b": str(a2)})
    assert run(shop, code).resolved == 1
    assert [f["entity_id"] for f in found(client, shop, code, resolved=True)] == [alpha]
    with system(shop) as s:
        s.execute(text("update pos.sales_invoice set amount_paid = 200, status = 'part_paid' where id = :a"),
                  {"a": str(a1)})                                                              # back to 800 owed
    assert run(shop, code).reopened == 1
    assert Dec(about(found(client, shop, code), alpha)[0]["amount"]) == Dec("800.00")
    with tuned(client, shop, code, min_days_overdue=10):
        assert run(shop, code).created == 1                                                    # Gamma, 13 days overdue


def test_overdue_without_crm_still_works_and_credit_limits_are_skipped(client, registry) -> None:  # type: ignore[no-untyped-def]
    plain = make_pos_shop(client, registry, "Pos Intel Plain")
    registry.enable(plain["tenant_id"], "intel")
    stranger = uuid4()
    raw_invoice(plain, "PL-1", stranger, date(2026, 6, 1), date(2026, 7, 1), "250.00")
    raw_invoice(plain, "PL-2", stranger, date(2026, 6, 1), date(2026, 7, 1), "999999.00")
    result = run(plain, "pos.customer_overdue", "pos.customer_over_credit_limit")
    assert result.failed == [] and result.created == 1
    [f] = found(client, plain, "pos.customer_overdue")
    assert f["summary"].startswith("A customer owes KES 1,000,249.00 past due on 2 invoices")


def test_customers_paying_slower_than_before(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.customer_paying_slower"
    names = ("Slow Sam", "Steady Tom", "Small Rise", "Few Invoices")
    sam, tom, rise, few = (credit_customer(client, shop, n)["id"] for n in names)
    n = 0

    def paid(customer: str, issue: date, days: int) -> None:
        nonlocal n
        n += 1
        invoice = raw_invoice(shop, f"SP-{n}", customer, issue, issue + timedelta(days=30), "100.00", paid="100.00",
                              status="paid")
        raw_receipt(shop, f"SPR-{n}", customer, invoice, issue + timedelta(days=days), "100.00")

    # the 90 days before 16 July: May. the last 90 days: August to early October
    for customer, before, after in ((sam, 10, 25), (tom, 10, 14), (rise, 3, 7), (few, 10, 30)):
        for issue in (date(2026, 5, 1), date(2026, 5, 10), date(2026, 5, 20)):
            paid(customer, issue, before)
        for issue in (date(2026, 8, 1), date(2026, 9, 1), date(2026, 9, 10)) if customer != few else (date(2026, 8, 1),):
            paid(customer, issue, after)
    raw_invoice(shop, "SP-OPEN", sam, date(2026, 10, 1), date(2026, 10, 31), "500.00")            # what Sam owes now
    assert run(shop, code).created == 1
    [f] = found(client, shop, code)
    assert f["entity_id"] == sam and f["severity"] == "medium"                                   # 25 days is over twice 10
    assert (Dec(f["value"]), Dec(f["expected_value"]), Dec(f["amount"])) == (Dec(25), Dec(10), Dec("500.00"))
    assert "Slow Sam now takes 25 days on average to pay, up from 10 days in the 90 days before; they currently owe KES 500.00" \
        in f["summary"]
    # Tom: +40% and 4 days. Small Rise: +133% but only 4 days. Few Invoices: only one invoice lately.
    with tuned(client, shop, code, increase_percent=30, min_increase_days=3):
        assert run(shop, code).created == 2                                                      # Tom and Small Rise
    assert {x["entity_id"] for x in found(client, shop, code)} == {sam, tom, rise}


def test_credit_given_to_a_customer_who_was_already_overdue(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.credit_to_overdue_customer"
    pat, quin, ron, sue, tia = (credit_customer(client, shop, n)["id"] for n in ("Pat", "Quin", "Ron", "Sue", "Tia"))
    raw_invoice(shop, "CO-P1", pat, date(2026, 8, 1), date(2026, 8, 31), "1000.00")             # overdue since 31 Aug
    new_pat = raw_invoice(shop, "CO-P2", pat, date(2026, 10, 12), date(2026, 11, 12), "600.00")
    raw_invoice(shop, "CO-Q1", quin, date(2026, 10, 1), date(2026, 10, 20), "1000.00")          # not yet due then
    raw_invoice(shop, "CO-Q2", quin, date(2026, 10, 12), date(2026, 11, 12), "600.00")
    raw_invoice(shop, "CO-R1", ron, date(2026, 8, 1), date(2026, 8, 31), "1000.00", paid="1000.00", status="paid")
    raw_invoice(shop, "CO-R2", ron, date(2026, 10, 12), date(2026, 11, 12), "600.00")            # Ron had settled up
    raw_invoice(shop, "CO-S1", sue, date(2026, 6, 1), date(2026, 6, 15), "1000.00")
    new_sue = raw_invoice(shop, "CO-S2", sue, date(2026, 10, 13), date(2026, 11, 13), "300.00")  # 120 days behind
    raw_invoice(shop, "CO-T1", tia, date(2026, 6, 1), date(2026, 6, 15), "1000.00")
    new_tia = raw_invoice(shop, "CO-T2", tia, date(2026, 9, 1), date(2026, 9, 30), "300.00")      # before the window
    assert run(shop, code).created == 2
    items = found(client, shop, code)
    by_entity = {f["entity_id"]: f for f in items}
    assert set(by_entity) == {str(new_pat), str(new_sue)}
    p = by_entity[str(new_pat)]
    assert (p["severity"], Dec(p["amount"]), p["branch_id"]) == ("medium", Dec("600.00"), str(shop["branch_id"]))
    assert "Invoice CO-P2 for KES 600.00 was issued on 2026-10-12 to pat" in p["summary"].replace("Pat", "pat")
    assert "still owes KES 1,000.00 on 1 older invoice that were already overdue (the oldest by 42 days)" in p["summary"]
    assert by_entity[str(new_sue)]["severity"] == "high"                                         # 120 days
    assert detail(client, shop, p)["figures"]["overdue_before"] == "1,000.00"
    with tuned(client, shop, code, days=60):
        run(shop, code)                  # (a wider window also catches Alpha's September invoice from another test)
        assert str(new_tia) in {f["entity_id"] for f in found(client, shop, code)}


def test_customers_over_their_credit_limit(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "pos.customer_over_credit_limit"
    over = credit_customer(client, shop, "Over Olga", limit="1000")["id"]
    way_over = credit_customer(client, shop, "Way Over", limit="1000")["id"]
    exact = credit_customer(client, shop, "Exact Eve", limit="1000")["id"]
    fine = credit_customer(client, shop, "Fine Finn", limit="5000")["id"]
    no_credit = credit_customer(client, shop, "No Credit", limit="0", terms=0)["id"]
    raw_invoice(shop, "CL-1", over, date(2026, 10, 1), date(2026, 11, 1), "1200.00")
    raw_receipt(shop, "CLR-1", over, None, date(2026, 10, 2), "100.00", unallocated="100.00")   # 100 held for her
    raw_invoice(shop, "CL-2", way_over, date(2026, 10, 1), date(2026, 11, 1), "1600.00")
    raw_invoice(shop, "CL-3", exact, date(2026, 10, 1), date(2026, 11, 1), "1000.00")
    raw_invoice(shop, "CL-4", fine, date(2026, 10, 1), date(2026, 11, 1), "1000.00")
    raw_invoice(shop, "CL-5", no_credit, date(2026, 10, 1), date(2026, 11, 1), "800.00")
    assert run(shop, code).created == 2
    by_entity = {f["entity_id"]: f for f in found(client, shop, code)}
    assert set(by_entity) == {over, way_over}
    o = by_entity[over]
    assert (o["severity"], Dec(o["amount"]), Dec(o["value"]), Dec(o["expected_value"])) == (
        "medium", Dec("100.00"), Dec("1100.00"), Dec("1000.00"))                                  # 1,200 less 100 held
    assert "Over Olga owes KES 1,100.00, which is KES 100.00 over their credit limit of KES 1,000.00" in o["summary"]
    assert by_entity[way_over]["severity"] == "high"                                             # 1,600 >= 150% of 1,000
    with tuned(client, shop, code, tolerance_percent=20):
        assert run(shop, code).resolved == 1                                                     # Olga is within 20%
    with system(shop) as s:
        s.execute(text("update pos.sales_invoice set amount_paid = 700 where number = 'CL-2'"))   # 900 owed: within
    assert run(shop, code).resolved == 1
    assert [f["entity_id"] for f in found(client, shop, code, resolved=True)].count(way_over) == 1


# --------------------------------------------------------------------------- Command Center figures
def test_pos_figures_company_wide_and_per_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = date(2026, 3, 3)
    who = cashier(shop, "paula")
    for number, branch, total, status in (("PF-1", shop["branch_id"], "100.00", "posted"),
                                          ("PF-2", shop["branch_id"], "200.00", "posted"),
                                          ("PF-3", shop["branch_id"], "300.00", "posted"),
                                          ("PF-4", shop["branch_id"], "50.00", "voided"),
                                          ("PF-5", shop["juja"], "400.00", "posted")):
        raw_sale(shop, number, who, day, "2026-03-03T10:00:00Z", total, branch=branch, status=status)
    base = raw_sale(shop, "PF-6", who, date(2026, 3, 2), "2026-03-02T10:00:00Z", "10.00")      # another day
    raw_return(shop, "PFR-1", base, day, "80.00", who)
    raw_return(shop, "PFR-2", base, day, "999.00", who, status="draft")                        # not posted
    raw_return(shop, "PFR-3", base, date(2026, 3, 4), "70.00", who)                            # another day
    raw_till(shop, who, day, variance="-20.00")
    raw_till(shop, who, day, variance="5.00")
    raw_till(shop, who, day, variance="-30.00", branch=shop["juja"], device=shop["juja_device"])
    raw_till(shop, who, day, status="open", device=shop["devices"]["boss"])
    raw_invoice(shop, "PFI-1", uuid4(), date(2026, 1, 1), date(2026, 2, 1), "1000.00", paid="300.00", status="part_paid")
    raw_invoice(shop, "PFI-2", uuid4(), date(2026, 1, 1), date(2026, 2, 1), "200.00", branch=shop["juja"])
    raw_invoice(shop, "PFI-3", uuid4(), date(2026, 1, 1), date(2026, 2, 1), "500.00", paid="500.00", status="paid")
    raw_invoice(shop, "PFI-4", uuid4(), date(2026, 2, 1), date(2026, 4, 1), "800.00")          # not due yet
    with system(shop) as s:
        pulse.refresh_company(s, shop["company_id"], day)
        rows = s.execute(text("select branch_id, metric, value, kind from command.pulse_figure where day = :d and "
                              "metric like 'pos.%'"), {"d": day}).all()
    figures = {(str(r.branch_id) if r.branch_id else None, r.metric): Dec(r.value) for r in rows}
    assert len(figures) == 24 == len(rows)                                       # 8 figures x (company, HQ, Juja)
    hq, juja = str(shop["branch_id"]), str(shop["juja"])

    def values(branch: str | None) -> list[Dec]:
        return [figures[(branch, m)] for m in (
            "pos.sales_total", "pos.sales_count", "pos.average_sale", "pos.voids_count", "pos.refunds_amount",
            "pos.till_variance", "pos.overdue_receivables", "pos.open_tills")]

    D = Dec  # noqa: N806
    assert values(hq) == [D(600), D(3), D(200), D(1), D(80), D(-15), D(700), D(1)]
    assert values(juja) == [D(400), D(1), D(400), D(0), D(0), D(-30), D(200), D(0)]
    assert values(None) == [D(1000), D(4), D(250), D(1), D(80), D(-45), D(900), D(1)]
    assert {r.kind for r in rows} == {"money", "count"}
