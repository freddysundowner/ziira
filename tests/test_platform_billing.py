"""Subscriptions and billing over time, with a frozen clock: trial -> first invoice -> reminders -> past due -> grace ->
suspended -> paid; upgrades and downgrades; coupons; cancelling; comps; invoice numbers, voids and payments.

Time is passed in (`now=`), never waited for. 'T0' is 2030-01-01 09:00 UTC."""

from datetime import timedelta
from decimal import Decimal as D  # noqa: N817

import pytest

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, T0, make_plan
from ziira.kernel.errors import Conflict, ValidationFailed
from ziira.kernel.platform import billing, plans, settings, subscriptions
from ziira.plugins.messaging.providers import FakeEmail


@pytest.fixture(scope="module", autouse=True)
def price_list(registry):  # type: ignore[no-untyped-def]
    settings.set_value("billing.tax_lines", [{"name": "VAT", "rate_percent": "16"}], "test")
    settings.set_value("billing.invoice_prefix", "INV-", "test")
    make_plan("bronze-b", prices={("USD", "month"): "30.00", ("USD", "year"): "300.00"}, max_users=2)
    make_plan("silver-b", units=["products", "inventory"], prices={("USD", "month"): "60.00"}, trial_days=0)
    yield
    settings.set_value("billing.tax_lines", [], "test")


def new_business(name: str, plan: str = "bronze-b", mode: str = "trial", **kw):  # type: ignore[no-untyped-def]
    t = make_tenant(name)
    sub = subscriptions.start(t["tenant_id"], plan, currency="USD", mode=mode, now=T0, **kw)
    return t["tenant_id"], sub


def invoices_of(tenant_id, kind=None):  # type: ignore[no-untyped-def]
    rows = billing.list_invoices(tenant_id=tenant_id)
    return [i for i in rows if kind is None or i["kind"] == kind]


def mails(subject_part: str, to: str) -> list:  # type: ignore[type-arg]
    return [m for m in FakeEmail.sent if m.recipient == to and subject_part in (m.subject or "")]


# --------------------------------------------------------------------------- the whole story of a trial
def test_a_trial_becomes_an_invoice_then_reminders_dunning_suspension_and_payment(client) -> None:  # type: ignore[no-untyped-def]
    tid, sub = new_business("Bill Story")
    owner = "owner@bill-story.test"
    assert (sub["status"], sub["unit_amount"], sub["interval"]) == ("trialing", D("30.00"), "month")
    assert sub["trial_end"] == T0 + timedelta(days=14) == sub["period_end"]

    # Jan 9: the first invoice is made 14 days before the trial ends: 30.00 + 16% = 34.80, due when the trial ends
    first = billing.run_due(now=T0 + timedelta(days=8))
    assert first["invoices"] == 1 and first["reminders"] == 1
    inv = invoices_of(tid)[0]
    assert (inv["kind"], inv["status"], inv["subtotal"], inv["tax_total"], inv["total"]) == \
        ("first", "issued", D("30.00"), D("4.80"), D("34.80"))
    assert inv["due_date"].isoformat() == "2030-01-15" and inv["number"].startswith("INV-")
    assert inv["period_start"] == T0 + timedelta(days=14) and inv["period_end"] == T0 + timedelta(days=45)  # Jan 15 -> Feb 15
    assert mails("is due in 6 day(s)", owner)                                   # the -7 day reminder, 6 days before
    assert billing.run_due(now=T0 + timedelta(days=8))["invoices"] >= 0         # running again changes nothing here
    assert len(invoices_of(tid)) == 1

    # Jan 15 (due day): the day-0 reminder; the status is untouched
    billing.run_due(now=T0 + timedelta(days=14))
    assert mails("is due today", owner) and subscriptions.require(tid)["status"] == "trialing"

    # Jan 16 (1 day overdue): past due, and the business still works fully
    assert billing.run_due(now=T0 + timedelta(days=15))["moved"] == 1
    assert subscriptions.require(tid)["status"] == "past_due"
    # Jan 22 (7 days): grace; one reminder goes out for the offsets 3 and 7 together
    before = len(mails("overdue", owner))
    billing.run_due(now=T0 + timedelta(days=21))
    assert subscriptions.require(tid)["status"] == "grace" and len(mails("overdue", owner)) == before + 1
    # Feb 5 (21 days): suspended
    billing.run_due(now=T0 + timedelta(days=35))
    assert subscriptions.require(tid)["status"] == "suspended"

    # the owner can still sign in and see what to pay, but nothing else works
    owner_h = sign_in(client, "bill-story", owner).headers
    plan = client.get(f"{API}/billing/plan", headers=owner_h)
    assert plan.status_code == 200 and plan.json()["access"] == "billing_only" and plan.json()["owed"] == {"USD": "34.80"}
    refused = client.get(f"{API}/users", headers=owner_h)
    assert refused.status_code == 402 and refused.json()["error"] == "subscription_suspended"

    # paying the invoice puts everything back: active, the next period runs Jan 15 -> Feb 15
    paid = billing.record_payment(inv["id"], method="bank transfer", amount="34.80", reference="TX1",
                                  now=T0 + timedelta(days=36))
    assert paid["status"] == "paid" and paid["balance"] == D("0.00")
    now_sub = subscriptions.require(tid)
    assert (now_sub["status"], now_sub["trial_end"]) == ("active", None)
    assert (now_sub["period_start"], now_sub["period_end"]) == (T0 + timedelta(days=14), T0 + timedelta(days=45))
    assert client.get(f"{API}/users", headers=owner_h).status_code == 200
    kinds = [e["kind"] for e in subscriptions.timeline(tid)]
    assert {"created", "invoice.created", "status.past_due", "status.grace", "status.suspended", "status.active"} <= set(kinds)


def test_an_invoice_overdue_for_90_days_expires_the_subscription(client) -> None:  # type: ignore[no-untyped-def]
    tid, _ = new_business("Bill Expire")
    billing.run_due(now=T0 + timedelta(days=10))
    due = T0 + timedelta(days=14)
    billing.run_due(now=due + timedelta(days=89))
    assert subscriptions.require(tid)["status"] == "suspended"
    billing.run_due(now=due + timedelta(days=90))
    assert subscriptions.require(tid)["status"] == "expired"
    owner = sign_in(client, "bill-expire", "owner@bill-expire.test").headers
    assert client.get(f"{API}/users", headers=owner).status_code == 200                 # read-only: reads work
    write = client.post(f"{API}/users", headers=owner, json={"full_name": "Late Hire", "email": "late@x.test"})
    assert write.status_code == 402 and write.json()["error"] == "subscription_ended"


def test_the_dunning_steps_are_the_vendors_data(client) -> None:  # type: ignore[no-untyped-def]
    settings.set_value("billing.dunning", {"reminders": [0], "past_due_after_days": 0, "grace_after_days": 2,
                                           "suspend_after_days": 3, "expire_after_days": 4}, "test")
    try:
        tid, _ = new_business("Bill Fast Dunning")
        billing.run_due(now=T0 + timedelta(days=10))
        due = T0 + timedelta(days=14)
        steps = []
        for days in (0, 2, 3, 4):
            billing.run_due(now=due + timedelta(days=days, hours=1))
            steps.append(subscriptions.require(tid)["status"])
        assert steps == ["past_due", "grace", "suspended", "expired"]
    finally:
        settings.set_value("billing.dunning", settings.DEFAULT_DUNNING, "test")


# --------------------------------------------------------------------------- changing plan
def test_an_upgrade_applies_now_and_is_prorated_a_downgrade_waits() -> None:
    tid, sub = new_business("Bill Change", mode="active")
    assert sub["period_end"] == T0 + timedelta(days=31)                               # Jan 1 -> Feb 1 (31 days)
    # Jan 22, 10 days left: (60.00 - 30.00) x 10 / 31 = 9.677 -> 9.68
    up = subscriptions.change_plan(tid, "silver-b", now=T0 + timedelta(days=21))
    assert up["effective"] == "now" and up["prorated_due"] == D("9.68")
    assert (up["subscription"]["plan_code"], up["subscription"]["unit_amount"]) == ("silver-b", D("60.00"))
    assert "inventory" in up["subscription"]["entitlements"]["units"]

    # going back down starts at the end of the period; today's plan stays
    down = subscriptions.change_plan(tid, "bronze-b", now=T0 + timedelta(days=24))
    assert down["effective"] == "period_end" and down["prorated_due"] == D("0.00")
    cur = subscriptions.require(tid)
    assert cur["plan_code"] == "silver-b" and cur["pending_plan_id"] is not None

    # the renewal is billed at the new (lower) price: 30.00 + 4.80 = 34.80; paying it makes the change real
    billing.run_due(now=T0 + timedelta(days=25))
    renewal = invoices_of(tid, "renewal")[0]
    assert renewal["total"] == D("34.80") and renewal["period_start"] == T0 + timedelta(days=31)
    billing.record_payment(renewal["id"], method="cash", amount="34.80", now=T0 + timedelta(days=26))
    after = subscriptions.require(tid)
    assert (after["plan_code"], after["unit_amount"], after["pending_plan_id"]) == ("bronze-b", D("30.00"), None)
    assert "inventory" not in after["entitlements"]["units"]
    assert after["period_start"] == T0 + timedelta(days=31) and after["status"] == "active"


def test_changing_interval_waits_for_the_period_end() -> None:
    tid, _ = new_business("Bill Interval", mode="active")
    res = subscriptions.change_plan(tid, "bronze-b", interval="year", now=T0 + timedelta(days=3))
    assert res["effective"] == "period_end"
    with pytest.raises(ValidationFailed, match="end of the period"):
        subscriptions.change_plan(tid, "bronze-b", interval="year", effective="now", now=T0 + timedelta(days=3))
    billing.run_due(now=T0 + timedelta(days=25))
    assert invoices_of(tid, "renewal")[0]["subtotal"] == D("300.00")                  # the yearly price


def test_a_retired_plan_cannot_be_chosen() -> None:
    make_plan("old-b", prices={("USD", "month"): "1.00"})
    plans.update_plan("old-b", {"status": "retired"})
    tid, _ = new_business("Bill Retired")
    with pytest.raises(ValidationFailed, match="retired"):
        subscriptions.change_plan(tid, "old-b")


def test_a_plan_edit_does_not_change_what_a_subscriber_was_sold() -> None:
    make_plan("grandfather", units=["products"], prices={("USD", "month"): "10.00"}, max_users=3)
    tid, _ = new_business("Bill Grandfather", plan="grandfather", mode="active")
    plans.update_plan("grandfather", {"max_users": 50})
    assert subscriptions.require(tid)["entitlements"]["max_users"] == 3
    synced = subscriptions.sync_to_plan(tid)
    assert synced["entitlements"]["max_users"] == 50 and synced["unit_amount"] == D("10.00")


# --------------------------------------------------------------------------- coupons
def test_a_coupon_discounts_the_next_invoice_once() -> None:
    plans.create_coupon({"code": "ONCE10", "percent_off": "10", "duration": "once"})
    tid, _ = new_business("Bill Coupon", plan="silver-b", mode="active")
    subscriptions.apply_coupon(tid, "ONCE10", now=T0)
    billing.run_due(now=T0 + timedelta(days=20))
    first = invoices_of(tid, "renewal")[0]
    # 60.00 less 6.00 = 54.00; 16% of that = 8.64; total 62.64
    assert (first["subtotal"], first["discount_total"], first["tax_total"], first["total"]) == \
        (D("60.00"), D("6.00"), D("8.64"), D("62.64"))
    billing.record_payment(first["id"], method="cash", amount="62.64", now=T0 + timedelta(days=21))
    assert subscriptions.require(tid)["coupon_id"] is None                               # used up
    billing.run_due(now=T0 + timedelta(days=50))
    second = invoices_of(tid, "renewal")[0]
    assert second["total"] == D("69.60") and second["discount_total"] == D("0.00")      # 60.00 + 9.60 tax
    assert plans.get_coupon("ONCE10")["redeemed"] == 1


def test_a_repeating_fixed_coupon_lasts_for_its_invoices() -> None:
    plans.create_coupon({"code": "FIVE2X", "amounts": {"USD": "5.00"}, "duration": "repeating", "duration_periods": 2})
    tid, _ = new_business("Bill Coupon Fixed", plan="silver-b", mode="active")
    subscriptions.apply_coupon(tid, "FIVE2X", now=T0)
    totals = []
    for day in (20, 50, 80):
        billing.run_due(now=T0 + timedelta(days=day))
        invoice = invoices_of(tid)[0]
        totals.append(invoice["total"])
        billing.record_payment(invoice["id"], method="cash", amount=str(invoice["total"]), now=T0 + timedelta(days=day))
    # 55.00 + 8.80 = 63.80 twice, then 60.00 + 9.60 = 69.60
    assert totals == [D("63.80"), D("63.80"), D("69.60")]


def test_coupons_are_checked(registry) -> None:  # type: ignore[no-untyped-def]
    plans.create_coupon({"code": "ONLYGOLD", "percent_off": "5", "plan_codes": ["silver-b"], "max_redemptions": 1})
    tid, _ = new_business("Bill Coupon Check")                                       # on bronze-b
    with pytest.raises(ValidationFailed, match="not valid for this plan"):
        subscriptions.apply_coupon(tid, "ONLYGOLD")
    other, _ = new_business("Bill Coupon Gold", plan="silver-b", mode="active")
    subscriptions.apply_coupon(other, "ONLYGOLD")
    third, _ = new_business("Bill Coupon Gold2", plan="silver-b", mode="active")
    with pytest.raises(ValidationFailed, match="used up"):
        subscriptions.apply_coupon(third, "ONLYGOLD")


# --------------------------------------------------------------------------- cancelling, comps, free plans
def test_cancelling_ends_at_the_period_end_without_another_invoice(client) -> None:  # type: ignore[no-untyped-def]
    tid, _ = new_business("Bill Cancel", mode="active")
    s = subscriptions.cancel(tid, at_period_end=True, reason="closing the shop", now=T0 + timedelta(days=5))
    assert s["cancel_at_period_end"] is True and s["status"] == "active"
    billing.run_due(now=T0 + timedelta(days=20))
    assert invoices_of(tid) == []
    billing.run_due(now=T0 + timedelta(days=31, hours=1))
    assert subscriptions.require(tid)["status"] == "cancelled" and invoices_of(tid) == []
    owner = sign_in(client, "bill-cancel", "owner@bill-cancel.test").headers
    assert client.get(f"{API}/users", headers=owner).status_code == 200
    assert client.post(f"{API}/users", headers=owner, json={"full_name": "Z", "email": "z@x.test"}).status_code == 402


def test_a_cancellation_can_be_taken_back_before_it_happens() -> None:
    tid, _ = new_business("Bill Uncancel", mode="active")
    subscriptions.cancel(tid, at_period_end=True)
    assert subscriptions.uncancel(tid)["cancel_at_period_end"] is False
    with pytest.raises(ValidationFailed, match="not set to cancel"):
        subscriptions.uncancel(tid)


def test_cancelling_now_makes_it_read_only_at_once() -> None:
    tid, _ = new_business("Bill Cancel Now", mode="active")
    assert subscriptions.cancel(tid, at_period_end=False, now=T0 + timedelta(days=2))["status"] == "cancelled"


def test_a_comp_is_never_billed_or_dunned() -> None:
    tid, _ = new_business("Bill Comp")
    comp = subscriptions.make_comp(tid, None, until=None, reason="our friend the charity", now=T0 + timedelta(days=1))
    assert (comp["status"], comp["unit_amount"], comp["is_comp"]) == ("active", D("0.00"), True)
    for day in (10, 40, 400):
        billing.run_due(now=T0 + timedelta(days=day))
        assert invoices_of(tid) == []
    assert subscriptions.require(tid)["status"] == "active"
    with pytest.raises(ValidationFailed, match="Say why"):
        subscriptions.make_comp(tid, None, until=None, reason="x")


def test_a_free_plan_rolls_on_without_invoices() -> None:
    make_plan("free-b", prices={("USD", "month"): "0.00"}, trial_days=7)
    tid, sub = new_business("Bill Free", plan="free-b")
    assert sub["unit_amount"] == D("0.00")
    billing.run_due(now=T0 + timedelta(days=8))
    s = subscriptions.require(tid)
    assert s["status"] == "active" and invoices_of(tid) == []
    assert s["period_start"] == T0 + timedelta(days=7)                               # the paid-for period begins at the trial end


def test_extending_a_trial_moves_the_first_invoice_and_clears_dunning() -> None:
    tid, _ = new_business("Bill Extend")
    s = subscriptions.extend_trial(tid, 10, now=T0 + timedelta(days=5))
    assert s["trial_end"] == T0 + timedelta(days=24)                                  # 14 + 10 days from the original end
    with pytest.raises(ValidationFailed):
        subscriptions.extend_trial(tid, 0)


def test_suspend_and_reactivate_by_hand() -> None:
    tid, _ = new_business("Bill Manual")
    with pytest.raises(ValidationFailed, match="Say why"):
        subscriptions.suspend(tid, "no")
    sus = subscriptions.suspend(tid, "fraud check pending", by="Ann", now=T0)
    assert sus["status"] == "suspended" and sus["status_reason"].startswith("manual:")
    back = subscriptions.reactivate(tid, reason="cleared", by="Ann", now=T0 + timedelta(days=1))
    assert back["status"] == "trialing"                                              # the trial is still running


# --------------------------------------------------------------------------- invoices and payments
def test_invoice_numbers_run_in_order_and_drafts_have_none() -> None:
    tid, _ = new_business("Bill Numbers")
    a = billing.create_invoice(tenant_id=tid, currency="USD", lines=[{"description": "Setup", "unit_amount": "100.00"}])
    assert a["status"] == "draft" and a["number"] is None and a["total"] == D("116.00")
    first = billing.issue_invoice(a["id"], now=T0)
    b = billing.create_invoice(tenant_id=tid, currency="USD", lines=[{"description": "Training", "unit_amount": "50.00",
                                                                      "quantity": "2"}], issue=True, now=T0)
    prefix, n = first["number"].rsplit("-", 1)
    assert b["number"] == f"{prefix}-{int(n) + 1:06d}" and b["total"] == D("116.00")
    assert b["issue_date"].isoformat() == "2030-01-01" and b["due_date"].isoformat() == "2030-01-15"  # due_days 14
    voided = billing.void_invoice(first["id"], "wrong customer")
    assert voided["status"] == "void" and voided["number"] == first["number"]
    c = billing.create_invoice(tenant_id=tid, currency="USD", lines=[{"description": "X", "unit_amount": "1"}], issue=True)
    assert c["number"] == f"{prefix}-{int(n) + 2:06d}"                                 # a void number is never reused


def test_an_issued_invoice_cannot_be_edited_and_a_draft_can() -> None:
    tid, _ = new_business("Bill Edit")
    d = billing.create_invoice(tenant_id=tid, currency="USD", lines=[{"description": "Setup", "unit_amount": "10.00"}])
    d2 = billing.update_draft(d["id"], lines=[{"description": "Setup", "unit_amount": "20.00"}], notes="thanks")
    assert d2["total"] == D("23.20") and d2["notes"] == "thanks"
    billing.issue_invoice(d["id"], now=T0)
    with pytest.raises(Conflict, match="Only a draft"):
        billing.update_draft(d["id"], notes="changed")
    with pytest.raises(Conflict, match="already issued"):
        billing.issue_invoice(d["id"])


def test_payments_partial_full_overpaid_and_reversed() -> None:
    tid, _ = new_business("Bill Pay")
    inv = billing.create_invoice(tenant_id=tid, currency="USD", issue=True, now=T0,
                                 lines=[{"description": "Setup", "unit_amount": "100.00"}])        # total 116.00
    part = billing.record_payment(inv["id"], method="cash", amount="50.00", now=T0)
    assert (part["status"], part["amount_paid"], part["balance"]) == ("issued", D("50.00"), D("66.00"))
    with pytest.raises(ValidationFailed, match="more than the 66.00"):
        billing.record_payment(inv["id"], method="cash", amount="66.01")
    full = billing.record_payment(inv["id"], method="bank", amount="66.00", reference="R2", now=T0)
    assert full["status"] == "paid" and full["paid_at"] is not None
    with pytest.raises(Conflict, match="issued invoices"):
        billing.record_payment(inv["id"], method="cash", amount="1.00")
    pay = billing.list_payments(inv["id"])[1]
    back = billing.reverse_payment(pay["id"], "bounced cheque")
    assert (back["status"], back["amount_paid"], back["paid_at"]) == ("issued", D("50.00"), None)
    assert billing.list_payments(inv["id"])[1]["reversed_at"] is not None
    with pytest.raises(Conflict, match="already reversed"):
        billing.reverse_payment(pay["id"], "again")
    with pytest.raises(Conflict, match="Reverse the payments first"):
        billing.void_invoice(inv["id"], "nope")


def test_the_printable_invoice_shows_the_numbers_and_escapes_text() -> None:
    tid, _ = new_business("Bill Print")
    inv = billing.create_invoice(tenant_id=tid, currency="USD", issue=True, now=T0, notes="<script>alert(1)</script>",
                                 lines=[{"description": "Setup <b>", "unit_amount": "100.00"}])
    page = billing.invoice_html(inv)
    assert inv["number"] in page and "116.00" in page and "VAT (16%)" in page and "16.00" in page
    assert "<script>" not in page and "&lt;script&gt;" in page and "Setup &lt;b&gt;" in page
