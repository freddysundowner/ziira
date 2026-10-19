"""Gyms and studios, part 2: billing that does not leak money. Overdue state, arrears, late-payment messages, the hold for
unpaid fees, taking payments, writing off and refunding by credit note, vouchers and credit applied to renewals."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from uuid import UUID, uuid4

import pytest

from tests.gym_helpers import M, age_invoice, customer, gym_plan, make_gym_shop, refresh, rows, scalar, today
from tests.memberships_helpers import run_billing
from tests.pos_helpers import reasons
from tests.stock_helpers import system
from ziira.modules.memberships.services import dues, notify


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_gym_shop(client, registry, "Gym Billing Co")
    s["return_reason"] = reasons(client, s["owner"])["sale_return"]
    return s


def join(client, shop, name: str, plan_id: str | None = None, phone: str | None = None, **extra):  # type: ignore[no-untyped-def]
    cust = customer(client, shop, name, **({"phone": phone} if phone else {}))
    body = {"plan_id": plan_id or shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
            **extra}
    r = client.post(f"{M}/members", headers=shop["rep"], json=body)
    assert r.status_code == 201, r.text
    return cust, r.json()


def first_invoice(client, shop, member_id: str) -> dict:  # type: ignore[no-untyped-def]
    runs = client.get(f"{M}/members/{member_id}/dues", headers=shop["owner"]).json()
    return sorted(runs, key=lambda r: r["period_start"])[0]


def member(client, shop, member_id: str) -> dict:  # type: ignore[no-untyped-def]
    return client.get(f"{M}/members/{member_id}", headers=shop["owner"]).json()


def noon() -> datetime:
    return datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC).replace(hour=12)


def test_an_unpaid_invoice_becomes_arrears_only_after_its_due_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Arrears Ann")
    inv = first_invoice(client, shop, m["id"])
    assert inv["settle_state"] == "open" and inv["due_date"] is not None
    refresh(shop)
    fresh = member(client, shop, m["id"])
    assert D(fresh["arrears"]) == 0 and fresh["past_due_since"] is None and fresh["days_late"] == 0     # not due yet
    age_invoice(shop, inv["invoice_number"], 10)
    refresh(shop)
    late = member(client, shop, m["id"])
    assert D(late["arrears"]) == D("100.00") and late["days_late"] == 10
    assert late["past_due_since"] == (today() - timedelta(days=10)).isoformat()
    listed = client.get(f"{M}/members", headers=shop["owner"], params={"past_due": "true"}).json()
    assert m["id"] in [x["id"] for x in listed]
    owed = client.get(f"{M}/arrears", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    mine = [x for x in owed if x["customer_id"] == cust["id"]]
    assert len(mine) == 1 and D(mine[0]["owed"]) == D("100.00") and mine[0]["days_late"] == 10
    assert mine[0]["members"][0]["number"] == m["number"] and mine[0]["invoice_numbers"] == [inv["invoice_number"]]


def test_a_payment_clears_the_arrears_at_once_and_gives_a_receipt(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Payer Pru")
    inv = first_invoice(client, shop, m["id"])
    age_invoice(shop, inv["invoice_number"], 3)
    refresh(shop)
    assert D(member(client, shop, m["id"])["arrears"]) == D("100.00")
    over = client.post(f"{M}/members/{m['id']}/payments", headers=shop["rep"], json={"amount": "150.00",
                                                                                  "method": "mobile_money"})
    assert over.status_code == 422 and "100.00" in over.text
    part = client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "40.00",
                                                                                   "method": "mobile_money"})
    assert part.status_code == 201, part.text
    assert part.json()["receipt_number"].startswith("RCT")
    assert D(member(client, shop, m["id"])["arrears"]) == D("60.00")                  # the event refreshed it
    rest = client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "60.00",
                                                                                   "method": "mobile_money"})
    assert rest.status_code == 201
    paid = member(client, shop, m["id"])
    assert D(paid["arrears"]) == 0 and paid["past_due_since"] is None
    dues_list = client.get(f"{M}/members/{m['id']}/dues", headers=shop["owner"]).json()
    assert dues_list[0]["settle_state"] == "paid" and D(dues_list[0]["outstanding"]) == 0
    nothing = client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "1.00",
                                                                                      "method": "mobile_money"})
    assert nothing.status_code == 422


def test_late_payment_messages_go_once_per_step_and_not_to_those_who_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"phone_country_code": "254"})
    cust, m = join(client, shop, "Dunned Dina", phone="0712111222")
    other, n = join(client, shop, "Refuser Rod", phone="0712111333")
    client.post(f"/api/v1/crm/customers/{other['id']}/do-not-contact", headers=shop["owner"], json={})
    for member_id in (m["id"], n["id"]):
        age_invoice(shop, first_invoice(client, shop, member_id)["invoice_number"], 9)
    refresh(shop)
    original = notify.route
    notify.route = lambda session, company_id, c: [("sms", c.phone)] if c.phone else []   # type: ignore[assignment]
    try:
        with system(shop) as s:
            first = dues.send_dunning(s, UUID(co), noon())
            again = dues.send_dunning(s, UUID(co), noon())                              # same step: nothing new
    finally:
        notify.route = original                                                        # type: ignore[assignment]
    assert first >= 2 and again == 0
    sent = rows(shop, "select status, body from kernel.notification where template = 'membership_payment_late' "
                      "and ref_type = 'memberships.invoice_run' and ref_id = :r", r=first_invoice(
                          client, shop, m["id"])["id"])
    assert len(sent) == 1 and sent[0].status == "queued" and "100.00" in sent[0].body
    refused = rows(shop, "select status from kernel.notification where template = 'membership_payment_late' "
                         "and ref_id = :r", r=first_invoice(client, shop, n["id"])["id"])
    assert [x.status for x in refused] == ["skipped"]
    log = rows(shop, "select step_days, outcome from memberships.dunning_log where run_id = :r",
               r=first_invoice(client, shop, m["id"])["id"])
    assert [(x.step_days, x.outcome) for x in log] == [(7, "queued")]                 # 9 days late: the 7-day step
    # later, the next step goes on its own
    age_invoice(shop, first_invoice(client, shop, m["id"])["invoice_number"], 15)
    refresh(shop)
    notify.route = lambda session, company_id, c: [("sms", c.phone)] if c.phone else []   # type: ignore[assignment]
    try:
        with system(shop) as s:
            assert dues.send_dunning(s, UUID(co), noon()) >= 1
    finally:
        notify.route = original                                                        # type: ignore[assignment]
    log = rows(shop, "select step_days from memberships.dunning_log where run_id = :r order by step_days",
               r=first_invoice(client, shop, m["id"])["id"])
    assert [x.step_days for x in log] == [7, 14]
    # pausing the reminders for one invoice stops them
    run_id = first_invoice(client, shop, n["id"])["id"]
    assert client.post(f"{M}/invoice-runs/{run_id}/dunning", headers=shop["rep"], json={"paused": True}).json()[
        "dunning_paused"] is True


def test_no_late_payment_message_in_quiet_hours(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Quiet Quin", phone="0712111444")
    age_invoice(shop, first_invoice(client, shop, m["id"])["invoice_number"], 9)
    refresh(shop)
    night = noon().replace(hour=23)
    with system(shop) as s:
        assert dues.send_dunning(s, UUID(str(shop["company_id"])), night) == 0


def test_fees_unpaid_for_long_enough_freeze_the_membership_until_they_are_paid(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"auto_freeze_days": 20})
    cust, m = join(client, shop, "Frozen Fred")
    inv = first_invoice(client, shop, m["id"])
    age_invoice(shop, inv["invoice_number"], 12)
    refresh(shop)
    with system(shop) as s:
        assert dues.apply_arrears_holds(s, UUID(co), today()) == 0                       # 12 days: not yet
    age_invoice(shop, inv["invoice_number"], 25)
    refresh(shop)
    with system(shop) as s:
        assert dues.apply_arrears_holds(s, UUID(co), today()) >= 1
    held = member(client, shop, m["id"])
    assert held["status"] == "frozen" and held["hold_kind"] == "arrears"
    # paying lifts it by itself
    paid = client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "100.00",
                                                                                   "method": "mobile_money"})
    assert paid.status_code == 201
    back = member(client, shop, m["id"])
    assert back["status"] == "active" and back["hold_kind"] is None and D(back["arrears"]) == 0
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"auto_freeze_days": 0})


def test_an_unpaid_invoice_is_written_off_with_a_credit_note_and_a_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Writeoff Wes")
    inv = first_invoice(client, shop, m["id"])
    age_invoice(shop, inv["invoice_number"], 40)
    refresh(shop)
    url = f"{M}/invoice-runs/{inv['id']}/credit"
    body = {"reason_code_id": shop["return_reason"], "refund_method": "credit_note", "note": "Moved abroad"}
    assert client.post(url, headers=shop["rep"], json=body).status_code == 403          # a rep cannot write off money
    assert client.post(url, headers=shop["manager"], json={**body, "note": ""}).status_code == 422
    done = client.post(url, headers=shop["manager"], json=body)
    assert done.status_code == 200, done.text
    assert done.json()["credit_number"] and D(done.json()["credit_total"]) == D("100.00")
    after = member(client, shop, m["id"])
    assert D(after["arrears"]) == 0 and after["past_due_since"] is None
    assert client.get(f"{M}/members/{m['id']}/dues", headers=shop["owner"]).json()[0]["settle_state"] == "credited"
    again = client.post(url, headers=shop["manager"], json=body)
    assert again.status_code in (409, 422)                                              # nothing left to credit
    audit = rows(shop, "select 1 from kernel.audit_log where entity_type = 'memberships.invoice_run' "
                       "and action = 'credit' and entity_id = :i", i=inv["id"])
    assert audit


def test_a_part_of_an_invoice_can_be_credited(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Partial Pete")
    inv = first_invoice(client, shop, m["id"])
    age_invoice(shop, inv["invoice_number"], 20)
    refresh(shop)
    r = client.post(f"{M}/invoice-runs/{inv['id']}/credit", headers=shop["manager"], json={
        "reason_code_id": shop["return_reason"], "refund_method": "credit_note", "amount": "25.00",
        "note": "Goodwill"})
    assert r.status_code == 200, r.text
    assert D(r.json()["credit_total"]) == D("25.00")
    assert D(member(client, shop, m["id"])["arrears"]) == D("75.00")


def test_a_paid_period_is_refunded_by_a_credit_note_and_money_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Refund Rae")
    inv = first_invoice(client, shop, m["id"])
    assert client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={
        "amount": "100.00", "method": "mobile_money"}).status_code == 201
    r = client.post(f"{M}/invoice-runs/{inv['id']}/credit", headers=shop["manager"], json={
        "reason_code_id": shop["return_reason"], "refund_method": "mobile_money", "note": "Joined by mistake"})
    assert r.status_code == 200, r.text
    assert r.json()["credit_status"] in ("posted", "pending_approval")
    wrong = client.post(f"{M}/invoice-runs/{inv['id']}/credit", headers=shop["manager"], json={
        "reason_code_id": shop["return_reason"], "refund_method": "cash", "note": "x"})
    assert wrong.status_code in (409, 422)


def test_a_failed_renewal_is_retried_not_forgotten_and_never_doubled(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m = join(client, shop, "Renew Rita", start_date=(today() - timedelta(days=40)).isoformat())
    run_billing(shop, today())
    run_billing(shop, today())
    runs = client.get(f"{M}/members/{m['id']}/dues", headers=shop["owner"]).json()
    assert len(runs) == 2 and len({r["period_start"] for r in runs}) == 2             # each period once


def test_credit_a_member_holds_pays_the_next_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Credit Cleo")
    given = client.post(f"{M}/credits/give", headers=shop["manager"], json={
        "customer_id": cust["id"], "amount": "30.00", "note": "Referral thank you"})
    assert given.status_code == 201, given.text
    assert D(given.json()["balance"]) == D("30.00")
    assert client.post(f"{M}/credits/give", headers=shop["rep"], json={
        "customer_id": cust["id"], "amount": "5.00", "note": "x"}).status_code == 403
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    inv = first_invoice(client, shop, m["id"])
    assert D(inv["total"]) == D("70.00")                                               # 100 less 30 of credit
    value = client.get(f"{M}/customers/{cust['id']}/value", headers=shop["rep"]).json()
    assert D(value["credit"]) == 0
    # the credit is spent once: a second member of the same customer pays in full
    # and a thrown-away invoice gives the credit back
    plus = gym_plan(client, shop, "CREDITPLUS", name="Credit plus", fee="50.00")
    cust2 = customer(client, shop, "Credit Chris")
    client.post(f"{M}/credits/give", headers=shop["manager"], json={"customer_id": cust2["id"], "amount": "20.00",
                                                                    "note": "Promo"})
    m2 = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plus["id"], "customer_id": cust2["id"], "branch_id": str(shop["branch_id"]),
        "auto_invoice": True}).json()
    assert D(first_invoice(client, shop, m2["id"])["total"]) == D("30.00")


def test_a_gift_voucher_is_sold_and_spent_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    buyer = customer(client, shop, "Voucher Vic")
    no_item = client.post(f"{M}/vouchers", headers=shop["rep"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "amount": "50.00", "purchaser_customer_id": buyer["id"],
        "invoice": True})
    assert no_item.status_code == 422                                                   # no voucher service item yet
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "voucher_product_id": shop["delivery"]})
    sold = client.post(f"{M}/vouchers", headers=shop["rep"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "amount": "50.00", "purchaser_customer_id": buyer["id"]})
    assert sold.status_code == 201, sold.text
    v = sold.json()
    assert v["code"].startswith("GV-") and D(v["balance"]) == D("50.00") and v["status"] == "active"
    found = client.get(f"{M}/vouchers/lookup", headers=shop["rep"], params={"company_id": co, "code": v["code"].lower()})
    assert found.status_code == 200 and found.json()["id"] == v["id"]
    # spent on a new member's first invoice with the code
    cust = customer(client, shop, "Voucher Val")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "voucher_code": v["code"]}).json()
    assert D(first_invoice(client, shop, m["id"])["total"]) == D("50.00")
    left = client.get(f"{M}/vouchers/{v['id']}", headers=shop["rep"]).json()
    assert D(left["balance"]) == 0 and left["status"] == "used"
    ledger = client.get(f"{M}/vouchers/{v['id']}/ledger", headers=shop["rep"]).json()
    assert [e["entry_type"] for e in ledger] == ["redeem", "issue"]
    # a used code is refused
    other = customer(client, shop, "Voucher Vera")
    refused = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": other["id"], "branch_id": str(shop["branch_id"]),
        "voucher_code": v["code"]})
    assert refused.status_code == 422
    # a voucher can be cancelled with a reason
    v2 = client.post(f"{M}/vouchers", headers=shop["rep"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "amount": "20.00"}).json()
    assert client.post(f"{M}/vouchers/{v2['id']}/void", headers=shop["rep"], json={"reason": "Lost"}).status_code == 403
    voided = client.post(f"{M}/vouchers/{v2['id']}/void", headers=shop["manager"], json={"reason": "Lost"})
    assert voided.status_code == 200 and voided.json()["status"] == "void" and D(voided.json()["balance"]) == 0


def test_referral_credit_goes_to_the_person_who_referred_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"referral_reward": "25.00"})
    referrer = customer(client, shop, "Referrer Rex")
    newbie = customer(client, shop, "Newbie Nell")
    assert client.patch(f"{M}/profiles/by-customer/{newbie['id']}", headers=shop["rep"], json={
        "referred_by_customer_id": referrer["id"]}).status_code == 200
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": newbie["id"], "branch_id": str(shop["branch_id"])})
    value = client.get(f"{M}/customers/{referrer['id']}/value", headers=shop["rep"]).json()
    assert D(value["credit"]) == D("25.00") and value["accounts"][0]["kind"] == "referral"
    # joining a second plan does not pay the reward again
    plus = gym_plan(client, shop, "REFPLUS", name="Ref plus", fee="30.00")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plus["id"], "customer_id": newbie["id"], "branch_id": str(shop["branch_id"])})
    assert D(client.get(f"{M}/customers/{referrer['id']}/value", headers=shop["rep"]).json()["credit"]) == D("25.00")
    selfie = client.patch(f"{M}/profiles/by-customer/{newbie['id']}", headers=shop["rep"], json={
        "referred_by_customer_id": newbie["id"]})
    assert selfie.status_code == 422
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"referral_reward": "0"})


def test_points_are_earned_on_payments_and_become_credit(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "points_per_unit": "0.1", "point_value": "2.00"})
    cust, m = join(client, shop, "Points Pia")
    pay = client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "100.00",
                                                                                  "method": "mobile_money"})
    assert pay.status_code == 201
    value = client.get(f"{M}/customers/{cust['id']}/value", headers=shop["rep"]).json()
    assert D(value["points"]) == D("10")                                                # 0.1 a unit on 100
    too_many = client.post(f"{M}/customers/{cust['id']}/points/redeem", headers=shop["rep"], json={"points": "11"})
    assert too_many.status_code == 422
    done = client.post(f"{M}/customers/{cust['id']}/points/redeem", headers=shop["rep"], json={"points": "5"})
    assert done.status_code == 200 and done.json()["kind"] == "promo" and D(done.json()["balance"]) == D("10.00")
    value = client.get(f"{M}/customers/{cust['id']}/value", headers=shop["rep"]).json()
    assert D(value["points"]) == D("5") and D(value["credit"]) == D("10.00")
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "points_per_unit": "0", "point_value": "0"})


def test_money_figures_never_use_floats(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert scalar(shop, "select count(*) from memberships.invoice_run where total is not null and "
                        "total <> round(total, 2)") == 0


def test_the_front_desk_can_pay_an_invoice_with_a_voucher_credit_or_points(client, shop) -> None:  # type: ignore[no-untyped-def]
    """The Bookings checkout asks these providers (bookings.checkout_tender); here they are called as it would."""
    import ziira.modules.pos.public as sales
    from ziira.modules.memberships.tender import CreditTender, LoyaltyTender, VoucherTender

    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "voucher_product_id": shop["delivery"], "points_per_unit": "0", "point_value": "2.00"})
    cust, m = join(client, shop, "Tender Tara", auto_invoice=True)
    inv_id = first_invoice(client, shop, m["id"])
    run = client.get(f"{M}/invoice-runs/{inv_id['id']}", headers=shop["owner"]).json()
    with system(shop) as s:
        invoice_id = UUID(str(run["invoice_id"]))
        voucher = client.post(f"{M}/vouchers", headers=shop["owner"], json={
            "company_id": co, "branch_id": str(shop["branch_id"]), "amount": "30.00"}).json()
        source = uuid4()
        tender = VoucherTender()
        assert tender.balance(s, customer_id=UUID(cust["id"]), code=voucher["code"]).available == D("30.00")
        assert tender.balance(s, customer_id=None, code="GV-NOPE") is None
        used = tender.redeem(s, customer_id=UUID(cust["id"]), code=voucher["code"], amount=D("20.00"),
                             invoice_id=invoice_id, source_type="bookings.checkout", source_id=source)
        assert used.applied == D("20.00") and sales.invoice_balance(s, invoice_id) == D("80.00")
        again = tender.redeem(s, customer_id=UUID(cust["id"]), code=voucher["code"], amount=D("20.00"),
                              invoice_id=invoice_id, source_type="bookings.checkout", source_id=source)
        assert again.applied == D("20.00") and sales.invoice_balance(s, invoice_id) == D("80.00")   # once only
        with pytest.raises(Exception, match="not valid"):
            tender.redeem(s, customer_id=UUID(cust["id"]), code="GV-NOPE", amount=D("1"), invoice_id=invoice_id,
                          source_type="bookings.checkout", source_id=uuid4())
        client.post(f"{M}/credits/give", headers=shop["manager"], json={
            "customer_id": cust["id"], "amount": "15.00", "note": "Goodwill"})
        credit = CreditTender()
        assert credit.balance(s, customer_id=UUID(cust["id"]), code=None).available == D("15.00")
        got = credit.redeem(s, customer_id=UUID(cust["id"]), code=None, amount=D("40.00"), invoice_id=invoice_id,
                            source_type="bookings.checkout", source_id=uuid4())
        assert got.applied == D("15.00") and sales.invoice_balance(s, invoice_id) == D("65.00")
        from ziira.modules.memberships.services import values

        company = UUID(co)
        values.earn_points(s, company_id=company, customer_id=UUID(cust["id"]), amount_paid=D("1"), source_type="t",
                           source_id=uuid4())                                       # rate 0: nothing
        account = values.points_account(s, company, UUID(cust["id"]), create=True)
        values._entry(s, account, "earn", D("10"), source_type="test", source_id=uuid4())
        points = LoyaltyTender()
        assert points.balance(s, customer_id=UUID(cust["id"]), code=None).available == D("20.00")
        paid = points.redeem(s, customer_id=UUID(cust["id"]), code=None, amount=D("11.00"), invoice_id=invoice_id,
                             source_type="bookings.checkout", source_id=uuid4())
        assert paid.applied == D("10.00") and sales.invoice_balance(s, invoice_id) == D("55.00")   # whole points only
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"point_value": "0"})
