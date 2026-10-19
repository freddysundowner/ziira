"""Checkout at the front desk: one bill from a visit to a paid invoice with services, retail, discount, tip, deposit, credit,
split payment and a co-pay; the Cashier can bill without Point of Sale's invoice right; all-or-nothing; idempotent."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.bookings_helpers import B, book, make_salon, reason
from tests.memberships_helpers import M
from tests.pos_helpers import credit_customer, stock
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Checkout Salon", units=("memberships",), stock="50")
    co = str(s["company_id"])
    s["loyal"] = reason(client, s, "checkout_discount", "LOYAL")
    s["cancel_client"] = reason(client, s, "appointment_cancel", "CLIENT")
    s["fee_waive"] = reason(client, s, "fee_waive", "GOOD_REASON")
    # Anna is a senior stylist, Brian a junior one; commission rules: 40 percent on services, 10 percent on products
    client.patch(f"{B}/resources/{s['anna']}", headers=s["owner"], json={"level": "Senior"})
    client.patch(f"{B}/resources/{s['brian']}", headers=s["owner"], json={"level": "Junior"})
    for applies, value in (("service", "40"), ("product", "10")):
        made = client.post(f"{B}/commission/rules", headers=s["owner"], json={
            "company_id": co, "applies_to": applies, "kind": "percent", "value": value})
        assert made.status_code == 201, made.text
    s["client2"] = credit_customer(client, s, "Njeri Client", limit="0", terms=0)
    return s


def sql(shop, stmt: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def walk_in(client, shop, who: str = "cashier", **extra):  # type: ignore[no-untyped-def]
    r = client.post(f"{B}/front-desk/walk-in", headers=shop[who], json={
        "offer_id": shop["cut"], "client_name": "Walk-in Wendy", **extra})
    assert r.status_code == 201, r.text
    return r.json()["appointment"]


def open_bill(client, shop, appt, who: str = "cashier"):  # type: ignore[no-untyped-def]
    r = client.post(f"{B}/checkouts", headers=shop[who], json={"appointment_ids": [appt["id"]]})
    assert r.status_code == 201, r.text
    return r.json()


def draft(client, shop, co, lines, who: str = "cashier", **extra):  # type: ignore[no-untyped-def]
    body = {"lines": lines, **extra}
    r = client.put(f"{B}/checkouts/{co['id']}", headers=shop[who], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def complete(client, shop, co, who: str = "cashier", **body):  # type: ignore[no-untyped-def]
    return client.post(f"{B}/checkouts/{co['id']}/complete", headers=shop[who], json=body)


def service_line(co, **extra):  # type: ignore[no-untyped-def]
    first = co["lines"][0]
    return {"kind": "service", "appointment_id": first["appointment_id"], "quantity": "1",
            "unit_price": first["unit_price"], "resource_id": first["resource_id"], **extra}


# --------------------------------------------------------------------------- the main flow
def test_a_walk_in_is_billed_with_a_product_a_tip_and_split_payments_by_the_cashier(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock(shop)
    appt = walk_in(client, shop)
    co = open_bill(client, shop, appt)
    assert co["status"] == "open" and co["lines"][0]["unit_price"] == "58.00"
    assert co["totals"]["total"] == "58.00"
    staff = co["lines"][0]["resource_id"]
    done = draft(client, shop, co, [
        service_line(co), {"kind": "product", "product_id": shop["cement"], "quantity": "2", "resource_id": staff}])
    assert done["totals"]["total"] == "290.00"                      # 58 + 2 x 116.00 (tax included)
    paid = complete(client, shop, co, payments=[{"method": "cash", "amount": "200.00"},
                                                {"method": "cash", "amount": "90.00"}],
                    tips=[{"resource_id": staff, "amount": "30.00", "method": "cash"}])
    assert paid.status_code == 200, paid.text
    out = paid.json()
    assert out["status"] == "done" and out["paid_total"] == "290.00" and out["tip_total"] == "30.00"
    assert out["invoice_number"]
    invoice = sql(shop, "select total, amount_paid, status from pos.sales_invoice where number = :n",
                  n=out["invoice_number"])[0]
    assert (str(invoice[0]), str(invoice[1]), invoice[2]) == ("290.00", "290.00", "paid")
    assert stock(shop) == before - Decimal(2)                       # the retail items left the shelf
    again = client.get(f"{B}/appointments/{appt['id']}", headers=shop["cashier"]).json()
    assert again["status"] == "completed" and again["invoice_number"] == out["invoice_number"]
    rules = sql(shop, "select applies_to, base, amount from bookings.commission_line where checkout_id = :c "
                      "order by applies_to", c=out["id"])
    assert [(r[0], str(r[2])) for r in rules][0][0] == "product"
    assert sum(r[2] for r in rules) > 0
    tips = sql(shop, "select held, amount from bookings.checkout_tip where checkout_id = :c", c=out["id"])
    assert tips == [(False, Decimal("30.00"))]                      # a cash tip goes straight to the person


def test_completing_twice_changes_nothing_and_a_wrong_payment_saves_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = walk_in(client, shop)
    co = open_bill(client, shop, appt)
    too_much = complete(client, shop, co, payments=[{"method": "cash", "amount": "999.00"}])
    assert too_much.status_code == 422 and "owes" in too_much.json()["message"]
    still = client.get(f"{B}/checkouts/{co['id']}", headers=shop["cashier"]).json()
    assert still["status"] == "open" and still["invoice_number"] is None          # nothing was kept
    first = complete(client, shop, co, payments=[{"method": "cash", "amount": "58.00"}])
    second = complete(client, shop, co, payments=[{"method": "cash", "amount": "58.00"}])
    assert first.status_code == second.status_code == 200
    assert first.json()["invoice_number"] == second.json()["invoice_number"]
    paid = sql(shop, "select count(*) from bookings.checkout_payment where checkout_id = :c and kind = 'payment'",
               c=co["id"])
    assert paid == [(1,)]


def test_a_discount_needs_a_reason_and_is_spread_over_the_bill(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = walk_in(client, shop)
    co = open_bill(client, shop, appt)
    staff = co["lines"][0]["resource_id"]
    lines = [service_line(co), {"kind": "product", "product_id": shop["cement"], "quantity": "1", "resource_id": staff}]
    priced = draft(client, shop, co, lines, discount_kind="percent", discount_value="10")
    assert priced["totals"]["total"] == "156.60"                    # 174.00 less 10 percent
    refused = complete(client, shop, co, payments=[{"method": "cash", "amount": "156.60"}])
    assert refused.status_code == 422 and "reason" in refused.json()["message"].lower()
    draft(client, shop, co, lines, discount_kind="percent", discount_value="10", discount_reason_id=shop["loyal"])
    ok = complete(client, shop, co, payments=[{"method": "cash", "amount": "156.60"}])
    assert ok.status_code == 200, ok.text
    assert ok.json()["totals"]["total"] == "156.60"
    line_totals = sql(shop, "select sum(line_total) from pos.sales_invoice_line l join pos.sales_invoice i on i.id = "
                            "l.invoice_id where i.number = :n", n=ok.json()["invoice_number"])
    assert line_totals == [(Decimal("156.60"),)]


def test_a_manager_limit_on_discounts_is_kept(client, shop) -> None:  # type: ignore[no-untyped-def]
    co_id = str(shop["company_id"])
    client.patch(f"{B}/settings", params={"company_id": co_id}, headers=shop["owner"],
                 json={"discount_limit_percent": "20"})
    try:
        appt = walk_in(client, shop)
        co = open_bill(client, shop, appt)
        lines = [service_line(co)]
        draft(client, shop, co, lines, discount_kind="percent", discount_value="50", discount_reason_id=shop["loyal"])
        cashier = complete(client, shop, co, payments=[{"method": "cash", "amount": "29.00"}])
        assert cashier.status_code == 403 and "manager" in cashier.json()["message"]
        manager = complete(client, shop, co, who="manager", payments=[{"method": "cash", "amount": "29.00"}])
        assert manager.status_code == 200, manager.text
    finally:
        client.patch(f"{B}/settings", params={"company_id": co_id}, headers=shop["owner"],
                     json={"discount_limit_percent": None})


def test_only_people_with_the_checkout_right_can_bill(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = walk_in(client, shop)
    rep = shop["user"]("viewer", "Accountant", shop["branch_id"])                # may view bookings, not check out
    assert client.post(f"{B}/checkouts", headers=rep, json={"appointment_ids": [appt["id"]]}).status_code == 403
    co = open_bill(client, shop, appt)
    assert client.get(f"{B}/checkouts/{co['id']}", headers=rep).status_code == 403
    assert client.post(f"{B}/checkouts/{co['id']}/discard", headers=shop["cashier"],
                       json={"reason": "client left"}).status_code == 200


def test_a_visit_not_yet_arrived_cannot_be_billed(client, shop) -> None:  # type: ignore[no-untyped-def]
    booked = book(client, shop, 12, 9, who="owner").json()
    refused = client.post(f"{B}/checkouts", headers=shop["cashier"], json={"appointment_ids": [booked["id"]]})
    assert refused.status_code == 422 and "check the client in" in refused.json()["message"]


# --------------------------------------------------------------------------- deposits, credit, payer, fees
def test_a_deposit_is_taken_at_booking_and_used_at_checkout(client, shop) -> None:  # type: ignore[no-untyped-def]
    offer = client.patch(f"{B}/offers/{shop['cut']}", headers=shop["owner"], json={"deposit_percent": "50"})
    assert offer.status_code == 200
    try:
        made = book(client, shop, 13, 9, who="cashier", customer_id=shop["customer"]["id"]).json()
        assert made["deposit_amount"] == "29.00" and made["deposit_paid"] == "0.00"
        assert any("Deposit" in w for w in client.get(f"{B}/appointments/{made['id']}", headers=shop["cashier"]).json()["warnings"])
        paid = client.post(f"{B}/appointments/{made['id']}/deposit", headers=shop["cashier"],
                           json={"amount": "29.00", "method": "cash"})
        assert paid.status_code == 200 and paid.json()["deposit_paid"] == "29.00"
        for step in ("check-in",):
            assert client.post(f"{B}/appointments/{made['id']}/{step}", headers=shop["cashier"]).status_code == 200
        co = open_bill(client, shop, made)
        assert co["deposit_held"] == "29.00"
        done = complete(client, shop, co, payments=[{"method": "cash", "amount": "29.00"}])
        assert done.status_code == 200, done.text
        assert done.json()["paid_total"] == "58.00"
        invoice = sql(shop, "select amount_paid, status from pos.sales_invoice where number = :n",
                      n=done.json()["invoice_number"])[0]
        assert (str(invoice[0]), invoice[1]) == ("58.00", "paid")
        left = sql(shop, "select coalesce(sum(unallocated), 0) from pos.customer_receipt where customer_id = :c",
                   c=shop["customer"]["id"])
        assert left == [(Decimal("0.00"),)]
    finally:
        client.patch(f"{B}/offers/{shop['cut']}", headers=shop["owner"], json={"deposit_percent": "0"})


def test_a_package_pays_for_the_service_and_the_rest_is_charged(client, shop) -> None:  # type: ignore[no-untyped-def]
    co_id = str(shop["company_id"])
    package = client.post(f"{M}/packages", headers=shop["owner"], json={
        "company_id": co_id, "code": "CUTS", "name": "Five cuts", "credits": "5", "price": "200.00",
        "covered_services": ["DELIVERY"], "product_id": shop["delivery"]})
    assert package.status_code == 201, package.text
    client_row = credit_customer(client, shop, "Package Pam", limit="100000", terms=14)
    sold = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": package.json()["id"], "customer_id": client_row["id"], "branch_id": str(shop["branch_id"])})
    assert sold.status_code == 201, sold.text
    appt = walk_in(client, shop, customer_id=client_row["id"])
    co = open_bill(client, shop, appt)
    assert co["lines"][0]["credit_quantity"] == "1.0000"            # the package is used by default
    assert co["totals"]["total"] == "0.00" and co["totals"]["credit_value"] == "58.00"
    done = complete(client, shop, co)
    assert done.status_code == 200, done.text
    assert done.json()["invoice_number"] is None and done.json()["credit_total"] == "58.00"
    import ziira.modules.memberships.public as memberships_public

    with system(shop) as s:
        assert memberships_public.member_credit_balance(s, UUID(client_row["id"])) == Decimal(4)    # one of five used


def test_a_payer_pays_all_but_the_patients_co_pay(client, shop) -> None:  # type: ignore[no-untyped-def]
    payer = credit_customer(client, shop, "Green Insurance", limit="100000", terms=30)
    patient = credit_customer(client, shop, "Patient Pete", limit="0", terms=0)
    made = book(client, shop, 14, 9, who="cashier", customer_id=patient["id"], payer_customer_id=payer["id"],
                copay_amount="8.00", preauth_ref="PA-123").json()
    assert made["preauth_ref"] == "PA-123" and made["copay_amount"] == "8.00"
    client.post(f"{B}/appointments/{made['id']}/check-in", headers=shop["cashier"])
    co = open_bill(client, shop, made)
    assert co["payer_customer_id"] == payer["id"] and co["copay_amount"] == "8.00"
    done = complete(client, shop, co, payments=[{"method": "cash", "amount": "8.00"}])
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["total"] == "8.00" and out["invoice_number"] and out["payer_invoice_number"]
    rows = sql(shop, "select i.total, i.customer_id from pos.sales_invoice i where i.number in (:a, :b) order by i.total",
               a=out["invoice_number"], b=out["payer_invoice_number"])
    assert [str(r[0]) for r in rows] == ["8.00", "50.00"]
    assert str(rows[1][1]) == payer["id"]


def test_a_late_cancellation_fee_appears_on_the_next_bill_and_can_be_waived(client, shop) -> None:  # type: ignore[no-untyped-def]
    co_id = str(shop["company_id"])
    fee_item = shop["delivery"]
    set_up = client.patch(f"{B}/settings", params={"company_id": co_id}, headers=shop["owner"], json={
        "late_cancel_fee_percent": "50", "no_show_fee_percent": "100", "fee_product_id": fee_item,
        "cancel_window_hours": 720})
    assert set_up.status_code == 200, set_up.text
    try:
        who = credit_customer(client, shop, "Late Lucy", limit="100000", terms=14)
        gone = book(client, shop, 2, 15, who="cashier", customer_id=who["id"]).json()
        cancelled = client.post(f"{B}/appointments/{gone['id']}/cancel", headers=shop["cashier"],
                                json={"reason_code_id": shop["cancel_client"]})
        assert cancelled.status_code == 200 and cancelled.json()["late_cancellation"] is True
        fees = client.get(f"{B}/fees", headers=shop["cashier"], params={"customer_id": who["id"]}).json()
        assert [(f["kind"], f["amount"]) for f in fees] == [("late_cancel", "29.00")]
        appt = walk_in(client, shop, customer_id=who["id"])
        co = open_bill(client, shop, appt)
        assert [line["kind"] for line in co["lines"]] == ["service", "fee"]
        assert co["totals"]["total"] == "87.00"
        done = complete(client, shop, co, payments=[{"method": "cash", "amount": "87.00"}])
        assert done.status_code == 200, done.text
        assert client.get(f"{B}/fees", headers=shop["cashier"], params={"customer_id": who["id"]}).json() == []
        # a second client: the fee is waived instead
        other = credit_customer(client, shop, "Missed Mia", limit="100000", terms=14)
        second = book(client, shop, 3, 15, who="cashier", customer_id=other["id"]).json()
        client.post(f"{B}/appointments/{second['id']}/cancel", headers=shop["cashier"],
                    json={"reason_code_id": shop["cancel_client"]})
        fee = client.get(f"{B}/fees", headers=shop["cashier"], params={"customer_id": other["id"]}).json()[0]
        waived = client.post(f"{B}/fees/{fee['id']}/waive", headers=shop["cashier"],
                             json={"reason_code_id": shop["fee_waive"], "note": "first time"})
        assert waived.status_code == 200 and waived.json()["status"] == "waived"
    finally:
        client.patch(f"{B}/settings", params={"company_id": co_id}, headers=shop["owner"], json={
            "late_cancel_fee_percent": "0", "no_show_fee_percent": "0", "fee_product_id": None,
            "cancel_window_hours": 24})


def test_a_client_over_their_limit_cannot_be_billed_on_credit_but_can_pay_now(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = walk_in(client, shop, customer_id=shop["client2"]["id"])           # credit limit 0
    co = open_bill(client, shop, appt)
    on_credit = complete(client, shop, co)
    assert on_credit.status_code == 422 and "credit" in on_credit.json()["message"].lower()
    paid = complete(client, shop, co, payments=[{"method": "cash", "amount": "58.00"}])
    assert paid.status_code == 200, paid.text


def test_a_tip_can_be_added_after_the_bill_and_paid_out_by_a_manager(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = walk_in(client, shop)
    co = open_bill(client, shop, appt)
    staff = co["lines"][0]["resource_id"]
    done = complete(client, shop, co, payments=[{"method": "cash", "amount": "58.00"}]).json()
    added = client.post(f"{B}/checkouts/{done['id']}/tips", headers=shop["cashier"],
                        json={"resource_id": staff, "amount": "12.00", "method": "card"})
    assert added.status_code == 200 and added.json()["tip_total"] == "12.00"
    cid = str(shop["company_id"])
    owed = client.get(f"{B}/tips/owed", headers=shop["boss"], params={"company_id": cid}).json()
    assert any(o["resource_id"] == staff and Decimal(o["owed"]) >= Decimal("12.00") for o in owed)
    assert client.get(f"{B}/tips/owed", headers=shop["cashier"], params={"company_id": cid}).status_code == 403
    paid = client.post(f"{B}/tips/pay-out", headers=shop["boss"], json={"company_id": cid, "resource_id": staff})
    assert paid.status_code == 200 and Decimal(paid.json()["amount"]) >= Decimal("12.00")
    assert client.post(f"{B}/tips/pay-out", headers=shop["boss"],
                       json={"company_id": cid, "resource_id": staff}).status_code == 422       # nothing left


def test_commission_is_reported_per_person_and_available_to_payroll(client, shop) -> None:  # type: ignore[no-untyped-def]
    from datetime import date, timedelta
    from uuid import UUID

    from ziira.modules.bookings import public as bookings_public

    cid = str(shop["company_id"])
    today = date.today()
    report = client.get(f"{B}/commission/report", headers=shop["boss"], params={
        "company_id": cid, "start": (today - timedelta(days=2)).isoformat(), "end": (today + timedelta(days=2)).isoformat()})
    assert report.status_code == 200, report.text
    anna = next(p for p in report.json() if p["resource_id"] == shop["anna"])
    brian = next(p for p in report.json() if p["resource_id"] == shop["brian"])
    assert Decimal(anna["commission"]) + Decimal(brian["commission"]) > 0
    assert client.get(f"{B}/commission/report", headers=shop["cashier"], params={
        "company_id": cid, "start": today.isoformat(), "end": today.isoformat()}).status_code == 403
    with system(shop) as s:
        figure = bookings_public.commission_figure(s, company_id=UUID(cid), start=today - timedelta(days=2),
                                                   end=today + timedelta(days=2))
    assert figure == Decimal(anna["commission"]) + Decimal(brian["commission"])
    # the lines cannot be edited, only reversed
    with pytest.raises(Exception, match="never changed"):
        sql(shop, "update bookings.commission_line set amount = 0")


def test_the_day_end_summary_adds_up(client, shop) -> None:  # type: ignore[no-untyped-def]
    summary = client.get(f"{B}/day-end", headers=shop["manager"], params={"branch_id": str(shop["branch_id"])})
    assert summary.status_code == 200, summary.text
    out = summary.json()
    assert out["visits"] >= 5 and Decimal(out["paid"]) > 0
    cash = sum(Decimal(m["amount"]) for m in out["payments_by_method"] if m["kind"] == "payment" and m["method"] == "cash")
    assert cash > 0
    assert client.get(f"{B}/day-end", headers=shop["cashier"], params={"branch_id": str(shop["branch_id"])}).status_code == 403
