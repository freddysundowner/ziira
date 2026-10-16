"""The platform's arithmetic and rules that need no database: proration, tax lines, billing periods, dunning steps,
access by status, recurring value, licence state, and roles. Every expectation is worked out by hand in the comment."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ziira.kernel.errors import NotInPlan, SubscriptionEnded, SubscriptionInactive, ValidationFailed
from ziira.kernel.platform import billing, dashboard, entitlements, licences, permissions, settings, subscriptions

D = Decimal
T0 = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


def line(description: str, unit: str, qty: str = "1") -> dict:  # type: ignore[type-arg]
    return billing._line(description, qty, unit)


# --------------------------------------------------------------------------- proration
def test_proration_charges_the_difference_for_the_days_left() -> None:
    # 30-day period (1 Jan -> 31 Jan), 10 days left: (60.00 - 30.00) x 10 / 30 = 10.00
    start, end = T0, T0 + timedelta(days=30)
    assert subscriptions.prorate_due(D("30.00"), D("60.00"), start, end, end - timedelta(days=10)) == D("10.00")


def test_proration_rounds_to_the_cent_and_counts_a_part_day_as_a_day() -> None:
    # 31-day period; 6 days 12 hours left counts as 7 days; (25.00 - 10.00) x 7 / 31 = 3.387... -> 3.39
    start, end = T0, T0 + timedelta(days=31)
    now = end - timedelta(days=6, hours=12)
    assert subscriptions.prorate_due(D("10.00"), D("25.00"), start, end, now) == D("3.39")


def test_proration_is_zero_at_the_end_and_never_negative() -> None:
    start, end = T0, T0 + timedelta(days=30)
    assert subscriptions.prorate_due(D("30.00"), D("60.00"), start, end, end) == D("0.00")
    assert subscriptions.prorate_due(D("60.00"), D("30.00"), start, end, start) == D("0.00")      # a cheaper plan: no credit


def test_billing_periods_use_calendar_months_and_years() -> None:
    assert subscriptions.add_interval(datetime(2030, 1, 31, tzinfo=UTC), "month") == datetime(2030, 2, 28, tzinfo=UTC)
    assert subscriptions.add_interval(datetime(2032, 1, 31, tzinfo=UTC), "month") == datetime(2032, 2, 29, tzinfo=UTC)
    assert subscriptions.add_interval(datetime(2030, 12, 15, tzinfo=UTC), "month") == datetime(2031, 1, 15, tzinfo=UTC)
    assert subscriptions.add_interval(datetime(2032, 2, 29, tzinfo=UTC), "year") == datetime(2033, 2, 28, tzinfo=UTC)
    assert subscriptions.add_interval(T0, "one_time") is None


# --------------------------------------------------------------------------- invoice totals
VAT = [{"name": "VAT", "rate_percent": "16"}]


def test_exclusive_tax_is_added_to_the_net() -> None:
    # 100.00 + 16% = 16.00 tax, total 116.00
    t = billing.compute_totals([line("Plan", "100.00")], VAT, tax_inclusive=False)
    assert (t["subtotal"], t["discount_total"], t["tax_total"], t["total"]) == (D("100.00"), D("0.00"), D("16.00"), D("116.00"))
    assert t["tax_lines"] == [{"name": "VAT", "rate_percent": "16", "amount": "16.00"}]


def test_inclusive_tax_is_part_of_the_price() -> None:
    # 116.00 holds 16%: net 100.00, tax 16.00, total stays 116.00
    t = billing.compute_totals([line("Plan", "116.00")], VAT, tax_inclusive=True)
    assert (t["tax_total"], t["total"]) == (D("16.00"), D("116.00"))


def test_two_tax_lines_exclusive_and_inclusive() -> None:
    two = [{"name": "Sales", "rate_percent": "10"}, {"name": "Levy", "rate_percent": "5"}]
    ex = billing.compute_totals([line("Plan", "200.00")], two, tax_inclusive=False)
    assert [x["amount"] for x in ex["tax_lines"]] == ["20.00", "10.00"] and ex["total"] == D("230.00")
    # inclusive: 115.00 holds 15% -> base 100.00; Sales 115 x 10 / 115 = 10.00, Levy 5.00, total 115.00
    inc = billing.compute_totals([line("Plan", "115.00")], two, tax_inclusive=True)
    assert [x["amount"] for x in inc["tax_lines"]] == ["10.00", "5.00"] and inc["total"] == D("115.00")


def test_a_discount_reduces_the_net_before_tax() -> None:
    # 60.00 charge, coupon -6.00: net 54.00; 16% = 8.64; total 62.64
    t = billing.compute_totals([line("Plan", "60.00"), line("Coupon", "-6.00")], VAT, tax_inclusive=False)
    assert (t["subtotal"], t["discount_total"], t["tax_total"], t["total"]) == (D("60.00"), D("6.00"), D("8.64"), D("62.64"))


def test_rounding_goes_half_up_per_tax_line() -> None:
    # 10.05 x 16% = 1.608 -> 1.61
    t = billing.compute_totals([line("Plan", "10.05")], VAT, tax_inclusive=False)
    assert t["tax_total"] == D("1.61") and t["total"] == D("11.66")


def test_no_tax_lines_means_no_tax() -> None:
    t = billing.compute_totals([line("Plan", "42.00")], [], tax_inclusive=False)
    assert t["tax_total"] == D("0.00") and t["total"] == D("42.00")


def test_discounts_larger_than_charges_are_refused() -> None:
    with pytest.raises(ValidationFailed):
        billing.compute_totals([line("Plan", "5.00"), line("Coupon", "-6.00")], VAT, tax_inclusive=False)


def test_quantities_multiply_into_the_line() -> None:
    assert line("Extra users", "7.50", "3")["amount"] == "22.50"


# --------------------------------------------------------------------------- dunning steps
def test_the_dunning_ladder_follows_the_default_schedule() -> None:
    cfg = settings.DEFAULT_DUNNING          # past due after 1 day, grace after 7, suspended after 21, expired after 90
    steps = {d: billing._target_status(d, cfg) for d in (-5, 0, 1, 6, 7, 20, 21, 89, 90)}
    assert steps == {-5: None, 0: None, 1: "past_due", 6: "past_due", 7: "grace", 20: "grace", 21: "suspended",
                     89: "suspended", 90: "expired"}


def test_dunning_settings_must_be_in_order() -> None:
    with pytest.raises(ValidationFailed, match="in order"):
        settings._dunning({"past_due_after_days": 10, "grace_after_days": 5})
    clean = settings._dunning({"reminders": [7, -7, 7, 0]})
    assert clean["reminders"] == [-7, 0, 7]


def test_tax_line_settings_are_validated_data() -> None:
    assert settings._tax_lines([{"name": "VAT", "rate_percent": "16.0"}]) == [{"name": "VAT", "rate_percent": "16"}]
    for bad in ([{"name": "", "rate_percent": "5"}], [{"name": "X", "rate_percent": "101"}],
                [{"name": "X", "rate_percent": "abc"}], "VAT 16"):
        with pytest.raises(ValidationFailed):
            settings._tax_lines(bad)


# --------------------------------------------------------------------------- access by status
@pytest.mark.parametrize(("status", "access"), [
    ("trialing", "full"), ("active", "full"), ("past_due", "warning"), ("grace", "warning"),
    ("suspended", "billing_only"), ("cancelled", "read_only"), ("expired", "read_only")])
def test_each_status_has_one_access_level(status: str, access: str) -> None:
    assert entitlements.STATUS_ACCESS[status] == access


def allowed(access: str, method: str, path: str, query: dict[str, str] | None = None) -> bool:
    try:
        entitlements.check_access(access, "suspended", "msg", method, path, query or {})
        return True
    except (SubscriptionInactive, SubscriptionEnded):
        return False


def test_a_suspended_account_reaches_billing_sign_in_and_offline_uploads_only() -> None:
    s = "billing_only"
    assert allowed(s, "GET", "/api/v1/billing/plan") and allowed(s, "POST", "/api/v1/billing/cancel")
    assert allowed(s, "POST", "/api/v1/auth/refresh") and allowed(s, "POST", "/api/v1/pos/sync/upload")
    assert allowed(s, "GET", "/api/v1/units") and allowed(s, "GET", "/api/v1/organisation")
    assert allowed(s, "GET", "/api/v1/products/products", {"format": "csv"})              # the data export
    assert not allowed(s, "GET", "/api/v1/products/products")
    assert not allowed(s, "POST", "/api/v1/pos/sales")
    assert not allowed(s, "POST", "/api/v1/units/pos/enable")                             # a write, even under /units
    assert not allowed(s, "POST", "/api/v1/products/products", {"format": "csv"})


def test_a_read_only_account_reads_everything_and_writes_nothing_but_billing_and_uploads() -> None:
    r = "read_only"
    assert allowed(r, "GET", "/api/v1/products/products") and allowed(r, "HEAD", "/api/v1/finance/reports")
    assert allowed(r, "POST", "/api/v1/billing/change-request") and allowed(r, "POST", "/api/v1/pos/sync/upload")
    assert not allowed(r, "POST", "/api/v1/products/products") and not allowed(r, "DELETE", "/api/v1/crm/customers/x")


def test_a_warning_or_full_account_is_never_stopped() -> None:
    for access in ("full", "warning"):
        assert allowed(access, "POST", "/api/v1/products/products")


def test_the_two_refusals_have_their_own_codes_and_402() -> None:
    with pytest.raises(SubscriptionInactive) as inactive:
        entitlements.check_access("billing_only", "suspended", "pay", "GET", "/api/v1/x", {})
    with pytest.raises(SubscriptionEnded) as ended:
        entitlements.check_access("read_only", "cancelled", "ended", "POST", "/api/v1/x", {})
    assert (inactive.value.status, inactive.value.code) == (402, "subscription_suspended")
    assert (ended.value.status, ended.value.code) == (402, "subscription_ended")
    assert ended.value.details == {"subscription_status": "cancelled"}
    assert NotInPlan("x").status == 402 and NotInPlan("x").code == "not_in_plan"


# --------------------------------------------------------------------------- monthly value
def sub(amount: str, interval: str, **kw) -> dict:  # type: ignore[type-arg]
    return {"unit_amount": D(amount), "interval": interval, "is_comp": False, "coupon_id": None,
            "coupon_periods_left": None, "currency": "USD", **kw}


def test_recurring_value_per_month() -> None:
    assert dashboard.monthly_value(sub("30.00", "month"), {}) == D("30.00")
    assert dashboard.monthly_value(sub("300.00", "year"), {}) == D("25.00")           # 300 / 12
    assert dashboard.monthly_value(sub("100.00", "year"), {}) == D("8.33")            # 8.333 rounds to 8.33
    assert dashboard.monthly_value(sub("30.00", "month", is_comp=True), {}) == D("0.00")
    assert dashboard.monthly_value(sub("500.00", "one_time"), {}) == D("0.00")


def test_a_running_coupon_lowers_the_recurring_value() -> None:
    coupon = {"percent_off": D("10"), "amounts": {}}
    assert dashboard.monthly_value(sub("60.00", "month", coupon_id=1, coupon_periods_left=2), {1: coupon}) == D("54.00")
    assert dashboard.monthly_value(sub("60.00", "month", coupon_id=1, coupon_periods_left=0), {1: coupon}) == D("60.00")


# --------------------------------------------------------------------------- roles
def test_roles_hold_the_permissions_the_design_gives_them() -> None:
    p = permissions
    assert p.permissions_of("superadmin") == frozenset(p.PERMISSIONS)
    assert "platform.operators" not in p.permissions_of("billing") and "platform.billing" in p.permissions_of("billing")
    assert p.permissions_of("support") == {"platform.view", "platform.subscribers"}
    assert p.permissions_of("content") == {"platform.view", "platform.content"}
    assert p.permissions_of("readonly") == {"platform.view"}
    assert p.permissions_of("nobody") == frozenset()
    for role in p.ROLES:
        assert "platform.view" in p.permissions_of(role) or role == "nobody"
    with pytest.raises(Exception, match="platform.plans"):
        p.check("support", "platform.plans")


# --------------------------------------------------------------------------- licences
PAYLOAD = {"kind": "licence", "licence_no": "LIC-000001", "customer": "Acme", "issued_at": T0.isoformat(),
           "valid_until": (T0 + timedelta(days=365)).isoformat(), "update_until": None, "grace_days": 30,
           "instance_id": None, "entitlements": {"units": ["products"], "max_users": 5}}


def state(now: datetime, payload: dict | None = None, **kw):  # type: ignore[no-untyped-def,type-arg]
    return licences.evaluate(payload or PAYLOAD, now=now, revoked=kw.get("revoked", set()),
                             this_instance=kw.get("instance", "inst-1"), clock_rolled_back=kw.get("rolled", False))


def test_a_licence_is_valid_until_its_date_then_graced_then_read_only() -> None:
    end = T0 + timedelta(days=365)
    assert state(T0 + timedelta(days=100)).status == "valid" and state(T0 + timedelta(days=100)).access == "full"
    # within 30 days of the end: still valid, but the owner is told to renew
    near = state(end - timedelta(days=10))
    assert (near.status, near.access, near.renewal_due, near.days_left) == ("valid", "warning", True, 10)
    # 1 to 30 days past the end (grace_days 30): everything works, with a warning
    late = state(end + timedelta(days=5))
    assert (late.status, late.access) == ("grace", "warning") and late.grace_ends == end + timedelta(days=30)
    # past the grace: read-only, never deleted
    over = state(end + timedelta(days=31))
    assert (over.status, over.access) == ("expired", "read_only")


def test_a_perpetual_licence_never_expires_but_may_stop_updates() -> None:
    perpetual = {**PAYLOAD, "valid_until": None, "update_until": (T0 + timedelta(days=100)).isoformat()}
    early = state(T0 + timedelta(days=50), perpetual)
    late = state(T0 + timedelta(days=5000), perpetual)
    assert (early.status, early.updates_ended, early.days_left) == ("valid", False, None)
    assert (late.status, late.access, late.updates_ended) == ("valid", "full", True)


def test_a_revoked_licence_is_read_only() -> None:
    s = state(T0 + timedelta(days=1), revoked={"LIC-000001"})
    assert (s.status, s.access) == ("revoked", "read_only")


def test_an_instance_bound_licence_works_only_there() -> None:
    bound = {**PAYLOAD, "instance_id": "inst-1"}
    assert state(T0 + timedelta(days=1), bound).status == "valid"
    assert state(T0 + timedelta(days=1), bound, instance="inst-2").status == "wrong_instance"


def test_a_clock_moved_back_makes_the_licence_read_only() -> None:
    s = state(T0 + timedelta(days=1), rolled=True)
    assert (s.status, s.access) == ("clock_rollback", "read_only")


def test_signatures_verify_and_any_change_breaks_them() -> None:
    private, public = licences.generate_keypair()
    other_private, other_public = licences.generate_keypair()
    text = licences.sign(PAYLOAD, private)
    assert licences.verify(text, public) == PAYLOAD
    with pytest.raises(ValidationFailed, match="signature"):
        licences.verify(text, other_public)                                       # another vendor's key
    with pytest.raises(ValidationFailed, match="signature"):
        licences.verify(text.replace('"max_users": 5', '"max_users": 500'), public)   # an edited licence
    with pytest.raises(ValidationFailed, match="signature"):
        licences.verify(licences.sign(PAYLOAD, other_private), public)            # signed with the wrong key
    with pytest.raises(ValidationFailed, match="not a Ziira licence"):
        licences.verify("{}", public)
    with pytest.raises(ValidationFailed, match="not a Ziira licence"):
        licences.verify("hello", public)
    with pytest.raises(ValidationFailed, match="no vendor public key"):
        licences.verify(text, "")


def test_canonical_form_ignores_key_order() -> None:
    assert licences.canonical({"b": 1, "a": 2}) == licences.canonical({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
