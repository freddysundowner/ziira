"""Memberships: plans, members, packages, the credits ledger and recurring invoices, through the API and the real
invoice service. Dates are chosen by the tests (the recurring task is run for a given day)."""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from uuid import UUID, uuid4

import pytest

from tests.memberships_helpers import (
    M,
    cancel_reason,
    customer,
    make_member_shop,
    rows,
    run_billing,
    scalar,
    sign_up,
)
from tests.pos_helpers import POS
from tests.stock_helpers import system
from ziira.modules.memberships import public as memberships


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_member_shop(client, registry, "Members Co")


def balance(client, shop, member_id: str) -> D:  # type: ignore[no-untyped-def]
    return D(client.get(f"{M}/members/{member_id}", headers=shop["owner"]).json()["balance"])


def member(client, shop, member_id: str) -> dict:  # type: ignore[no-untyped-def]
    r = client.get(f"{M}/members/{member_id}", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- plans and permissions
def test_plans_and_packages_are_managed_by_people_with_the_right(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    body = {"company_id": co, "code": "silver", "name": "Silver", "fee": "50.00", "billing_interval": "quarter"}
    assert client.post(f"{M}/plans", headers=shop["rep"], json=body).status_code == 403     # a rep sells, not prices
    assert client.post(f"{M}/plans", headers=shop["cashier"], json=body).status_code == 403
    made = client.post(f"{M}/plans", headers=shop["fm"], json=body)
    assert made.status_code == 201 and made.json()["code"] == "SILVER"
    assert client.post(f"{M}/plans", headers=shop["fm"], json=body).status_code == 409      # the code is taken
    plans = client.get(f"{M}/plans", headers=shop["cashier"]).json()                       # a cashier may look
    assert {p["code"] for p in plans} >= {"GOLD", "SILVER"}
    retired = client.patch(f"{M}/plans/{made.json()['id']}", headers=shop["fm"], json={"status": "retired"})
    assert retired.json()["status"] == "retired"
    assert client.get(f"{M}/plans", headers=shop["cashier"], params={"status": "active"}).json() != []
    bad = client.post(f"{M}/plans", headers=shop["fm"], json={**body, "code": "x", "billing_interval": "decade"})
    assert bad.status_code == 422
    not_a_service = client.post(f"{M}/plans", headers=shop["fm"], json={
        **body, "code": "BAD", "service_product_id": shop["cement"]})
    assert not_a_service.status_code == 422 and "service" in not_a_service.text.lower()
    nobody = client.get(f"{M}/plans")
    assert nobody.status_code in (401, 403)


def test_a_business_cannot_see_another_business_s_memberships(client, shop, tenants) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import sign_in

    other = sign_in(client, "tenant-b", "owner@tenant-b.test").headers
    r = client.get(f"{M}/plans", headers=other)
    assert r.status_code in (200, 403, 404) and (r.status_code != 200 or r.json() == [])
    assert client.get(f"{M}/plans/{shop['plan']['id']}", headers=other).status_code in (403, 404)


# --------------------------------------------------------------------------- signing up
def test_signing_up_invoices_the_first_period_and_grants_the_credits(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Signup Sam")
    start = date(2026, 6, 10)
    r = sign_up(client, shop, cust, start, who="rep")
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "active" and m["number"].startswith("MEM-") and m["customer_name"] == "Signup Sam"
    assert m["next_renewal_date"] == "2026-07-10" and m["price"] == "100.00" and D(m["balance"]) == 4
    # the first period was invoiced once through the sales invoice service, at the plan's fee
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert len(runs) == 1 and runs[0]["status"] == "issued" and runs[0]["period_start"] == "2026-06-10"
    assert D(runs[0]["total"]) == D("100.00") and runs[0]["invoice_number"].startswith("INV-")
    invoice = client.get(f"{POS}/invoices/{runs[0]['invoice_id']}", headers=shop["owner"]).json()
    assert invoice["customer_id"] == cust["id"] and D(invoice["total"]) == D("100.00")
    assert scalar(shop, "select description from pos.sales_invoice_line where invoice_id = :i",
                  i=runs[0]["invoice_id"]) == "Gold membership, 2026-06-10 to 2026-07-09"
    history = client.get(f"{M}/members/{m['id']}/history", headers=shop["owner"]).json()
    assert [h["action"] for h in history] == ["started"]
    # the same customer cannot take the same plan twice
    assert sign_up(client, shop, cust, start).status_code == 409
    # a cashier may look but not sign people up
    assert sign_up(client, shop, customer(client, shop, "Cashier Try"), who="cashier").status_code == 403
    assert client.get(f"{M}/members/{m['id']}", headers=shop["cashier"]).status_code == 200


def test_a_failed_first_invoice_signs_nobody_up(client, shop) -> None:  # type: ignore[no-untyped-def]
    poor = customer(client, shop, "Over The Limit", limit="50")                   # fee 100.00, limit 50.00
    r = sign_up(client, shop, poor, date(2026, 6, 1))
    assert r.status_code in (400, 409, 422), r.text
    assert client.get(f"{M}/members", headers=shop["owner"], params={"customer_id": poor["id"]}).json() == []


def test_the_plan_s_price_at_sign_up_is_kept_when_the_plan_changes(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "SNAP", "name": "Snap", "fee": "80.00",
        "credits_per_period": "2", "service_product_id": shop["delivery"]}).json()
    cust = customer(client, shop, "Snapshot Sue")
    m = client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": "2026-03-01"}).json()
    client.patch(f"{M}/plans/{plan['id']}", headers=shop["owner"], json={"fee": "120.00", "credits_per_period": "9"})
    run_billing(shop, date(2026, 4, 2))
    again = member(client, shop, m["id"])
    assert again["price"] == "80.00" and again["next_renewal_date"] == "2026-05-01" and D(again["balance"]) == 2
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert sorted(D(r["total"]) for r in runs) == [D("80.00"), D("80.00")]


# --------------------------------------------------------------------------- renewals
def test_a_renewal_is_invoiced_once_unused_credits_expire_and_new_ones_are_granted(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Renewal Rita")
    m = sign_up(client, shop, cust, date(2026, 7, 5)).json()
    use = client.post(f"{M}/credits/consume", headers=shop["owner"], json={
        "customer_id": cust["id"], "quantity": "1", "source_id": str(uuid4())})
    assert use.status_code == 200 and D(use.json()["covered"]) == 1
    assert balance(client, shop, m["id"]) == 3
    run_billing(shop, date(2026, 7, 20))                                         # nothing is due for her yet
    assert member(client, shop, m["id"])["next_renewal_date"] == "2026-08-05"
    run_billing(shop, date(2026, 8, 6))
    after = member(client, shop, m["id"])
    assert after["next_renewal_date"] == "2026-09-05" and D(after["balance"]) == 4        # 3 expired, 4 granted
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert sorted(r["period_start"] for r in runs) == ["2026-07-05", "2026-08-05"]
    kinds = [r.entry_type for r in rows(shop, "select entry_type from memberships.credit_entry where holder_id = :h "
                                              "order by seq", h=m["id"])]
    assert kinds == ["grant", "use", "expiry", "grant"]
    # running the task again for the same day changes nothing
    run_billing(shop, date(2026, 8, 6))
    assert len(client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()) == 2
    assert balance(client, shop, m["id"]) == 4
    # a few days later: the renewal after that, a month on
    run_billing(shop, date(2026, 9, 6))
    assert member(client, shop, m["id"])["next_renewal_date"] == "2026-10-05"
    assert [h["action"] for h in client.get(f"{M}/members/{m['id']}/history", headers=shop["owner"]).json()] == [
        "renewed", "renewed", "started"]


def test_missed_periods_are_caught_up_within_the_limit_and_the_rest_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Catchup Cal")
    m = sign_up(client, shop, cust, date(2026, 1, 1)).json()
    assert client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co},
                        json={"catch_up_max_periods": 2}).status_code == 200
    run_billing(shop, date(2026, 5, 15))        # behind: Feb, Mar, Apr, May are due; only the last two are renewed
    after = member(client, shop, m["id"])
    assert after["next_renewal_date"] == "2026-06-01"
    runs = {r["period_start"]: r["status"] for r in client.get(
        f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()}
    assert runs == {"2026-01-01": "issued", "2026-02-01": "skipped", "2026-03-01": "skipped",
                    "2026-04-01": "issued", "2026-05-01": "issued"}
    flagged = rows(shop, "select message from kernel.exception_item where unit_name = 'memberships' "
                         "and kind = 'recurring_period_skipped' and ref_id in (select id from memberships.invoice_run "
                         "where owner_id = :m)", m=m["id"])
    assert len(flagged) == 2
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"catch_up_max_periods": 3})


def test_a_renewal_that_cannot_be_invoiced_waits_and_is_flagged_then_goes_through_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Limit Larry", limit="150")                       # room for one 100.00 invoice
    m = sign_up(client, shop, cust, date(2026, 2, 1)).json()
    run_billing(shop, date(2026, 3, 2))                                              # a second invoice breaks the limit
    waiting = member(client, shop, m["id"])
    assert waiting["next_renewal_date"] == "2026-03-01" and D(waiting["balance"]) == 4         # not renewed
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"], "status": "failed"}).json()
    assert len(runs) == 1 and runs[0]["message"]
    assert len(rows(shop, "select 1 from kernel.exception_item where kind = 'recurring_invoice_failed' "
                          "and ref_id = :r", r=runs[0]["id"])) == 1
    run_billing(shop, date(2026, 3, 2))                                              # tried again, flagged only once
    assert len(rows(shop, "select 1 from kernel.exception_item where kind = 'recurring_invoice_failed' "
                          "and ref_id = :r", r=runs[0]["id"])) == 1
    client.post(f"/api/v1/crm/customers/{cust['id']}/credit", headers=shop["fm"], json={
        "credit_limit": "100000", "payment_terms_days": 14, "reason": "Raised"})
    run_billing(shop, date(2026, 3, 3))
    done = member(client, shop, m["id"])
    assert done["next_renewal_date"] == "2026-04-01"
    mine = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert sorted(r["status"] for r in mine) == ["issued", "issued"]
    assert scalar(shop, "select count(*) from pos.sales_invoice where customer_id = :c", c=cust["id"]) == 2


def test_proration_is_a_company_choice(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"prorate_first_period": True})
    cust = customer(client, shop, "Prorata Pat")
    m = sign_up(client, shop, cust, date(2026, 1, 15)).json()
    # 15 Jan to 31 Jan is 17 of 31 days: 100.00 x 17 / 31 = 54.84, 4 credits x 17 / 31 = 2.19, rounded to 2
    assert m["next_renewal_date"] == "2026-02-01" and D(m["balance"]) == 2
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert D(runs[0]["total"]) == D("54.84")
    run_billing(shop, date(2026, 2, 2))                                                  # then the full fee, on the 1st
    assert member(client, shop, m["id"])["next_renewal_date"] == "2026-03-01"
    full = {D(r["total"]) for r in client.get(f"{M}/invoice-runs", headers=shop["owner"],
                                              params={"owner_id": m["id"]}).json()}
    assert full == {D("54.84"), D("100.00")}
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"prorate_first_period": False})


# --------------------------------------------------------------------------- hold and cancel
def test_pausing_stops_credits_and_renewals_and_resuming_adds_the_days_held(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Pause Pam")
    m = sign_up(client, shop, cust, date(2026, 9, 1)).json()
    paused = client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={"note": "Travelling"})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    with system(shop) as s:
        assert memberships.member_credit_balance(s, UUID(cust["id"])) == 0 and memberships.active_membership(
            s, UUID(cust["id"])) is None
    use = client.post(f"{M}/credits/consume", headers=shop["owner"], json={
        "customer_id": cust["id"], "source_id": str(uuid4())}).json()
    assert D(use["covered"]) == 0 and D(use["remaining"]) == 1
    assert client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={}).status_code == 409
    run_billing(shop, date(2026, 10, 5))                                                 # held: nothing is renewed
    assert member(client, shop, m["id"])["next_renewal_date"] == "2026-10-01"
    resumed = client.post(f"{M}/members/{m['id']}/resume", headers=shop["rep"], json={})
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"
    held = (date.today() - date(date.today().year, date.today().month, date.today().day)).days   # paused today: 0 days
    assert held == 0 and resumed.json()["next_renewal_date"] == "2026-10-01"
    with system(shop) as s:
        assert memberships.member_credit_balance(s, UUID(cust["id"])) == 4


def test_a_hold_with_a_resume_date_ends_by_itself_and_the_days_held_are_added(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Auto Resume")
    m = sign_up(client, shop, cust, date(2026, 8, 1)).json()
    client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={"resume_on": "2099-01-01", "frozen": True})
    assert member(client, shop, m["id"])["status"] == "frozen"
    from ziira.modules.memberships.services import members as svc

    with system(shop) as s:
        # held from today until 10 days later: the renewal moves 10 days
        s.execute(__import__("sqlalchemy").text(
            "update memberships.member set resume_on = :r, paused_from = :p where id = :i"),
            {"r": date(2026, 10, 28), "p": date(2026, 10, 18), "i": m["id"]})
        assert svc.process_member(s, UUID(m["id"]), date(2026, 10, 28)) == "resumed"
    again = member(client, shop, m["id"])
    assert again["status"] == "active" and again["next_renewal_date"] == "2026-09-11"      # 1 Sep + 10 days


def test_cancelling_needs_a_reason_and_ends_at_the_end_of_the_period(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Cancel Carl")
    m = sign_up(client, shop, cust, date(2026, 5, 1)).json()
    assert client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={}).status_code == 422
    r = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": cancel_reason(client, shop), "note": "Moving"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["cancel_at"] == "2026-06-01"
    with system(shop) as s:
        assert memberships.active_membership(s, UUID(cust["id"])).id == UUID(m["id"])      # still a member this period
    assert client.post(f"{M}/members/{m['id']}/undo-cancel", headers=shop["rep"]).json()["cancel_at"] is None
    client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={"reason_code_id": cancel_reason(client, shop)})
    run_billing(shop, date(2026, 6, 2))
    ended = member(client, shop, m["id"])
    assert ended["status"] == "cancelled" and D(ended["balance"]) == 0
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert len(runs) == 1                                                                # no renewal invoice
    assert client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": cancel_reason(client, shop)}).status_code == 409
    # joining again is allowed once the first has ended
    assert sign_up(client, shop, cust, date(2026, 6, 5)).status_code == 201


def test_cancelling_now_ends_it_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Cancel Now")
    m = sign_up(client, shop, cust, date(2026, 5, 1)).json()
    r = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": cancel_reason(client, shop), "at_period_end": False})
    assert r.json()["status"] == "cancelled" and D(r.json()["balance"]) == 0


def test_a_fixed_term_membership_expires_at_its_end_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Term Tom")
    m = sign_up(client, shop, cust, date(2026, 1, 1), end_date="2026-03-15").json()
    run_billing(shop, date(2026, 3, 20))
    ended = member(client, shop, m["id"])
    assert ended["status"] == "expired" and D(ended["balance"]) == 0
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json()
    assert sorted(r["period_start"] for r in runs) == ["2026-01-01", "2026-02-01", "2026-03-01"]


# --------------------------------------------------------------------------- credits
def test_credits_are_spent_once_per_source_and_given_back_on_release(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Credit Cleo")
    cid = UUID(cust["id"])
    m = sign_up(client, shop, cust, date(2026, 10, 1)).json()
    source = uuid4()
    with system(shop) as s:
        first = memberships.consume_credit(s, customer_id=cid, service_ref="haircut", quantity=D(3),
                                           source_type="booking", source_id=source)
        assert (first.covered, first.remaining, first.discount_percent, first.replayed) == (D(3), D(0), D(10), False)
        again = memberships.consume_credit(s, customer_id=cid, service_ref="haircut", quantity=D(3),
                                           source_type="booking", source_id=source)
        assert again.replayed and again.covered == D(3)
        assert memberships.member_credit_balance(s, cid) == D(1)
        more = memberships.consume_credit(s, customer_id=cid, service_ref="haircut", quantity=D(3),
                                          source_type="booking", source_id=uuid4())
        assert (more.covered, more.remaining) == (D(1), D(2))                          # never below zero
        assert memberships.member_credit_balance(s, cid) == D(0)
        assert memberships.release_credit(s, source_type="booking", source_id=source) == D(3)
        assert memberships.release_credit(s, source_type="booking", source_id=source) == D(0)    # only once
        assert memberships.member_credit_balance(s, cid) == D(3)
        spent = memberships.consume_credit(s, customer_id=cid, service_ref="haircut", quantity=D(1),
                                           source_type="booking", source_id=source)    # the same source, after release
        assert spent.covered == D(1) and not spent.replayed
    assert balance(client, shop, m["id"]) == 2
    types = [r.entry_type for r in rows(shop, "select entry_type from memberships.credit_entry where holder_id = :h "
                                              "order by seq", h=m["id"])]
    assert types == ["grant", "use", "use", "reversal", "use"]
    ledger = client.get(f"{M}/members/{m['id']}/credits", headers=shop["owner"]).json()
    assert D(sum(D(e["quantity"]) for e in ledger)) == 2
    with pytest.raises(Exception, match="cannot|immutable|forbid"):                    # entries are never changed
        rows(shop, "update memberships.credit_entry set quantity = 99 where holder_id = :h", h=m["id"])


def test_overdraw_is_allowed_only_when_the_company_says_so(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Overdraw Ollie")
    cid = UUID(cust["id"])
    m = sign_up(client, shop, cust, date(2026, 10, 1)).json()
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"allow_overdraw": True})
    with system(shop) as s:
        got = memberships.consume_credit(s, customer_id=cid, service_ref=None, quantity=D(6), source_type="job",
                                         source_id=uuid4())
    assert (got.covered, got.remaining) == (D(6), D(0)) and balance(client, shop, m["id"]) == -2
    assert rows(shop, "select 1 from memberships.credit_entry") != []
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"allow_overdraw": False})


def test_manual_adjustments_need_a_note_the_right_and_stay_above_zero(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Adjust Abe")
    m = sign_up(client, shop, cust, date(2026, 10, 1)).json()
    body = {"holder_type": "membership", "holder_id": m["id"], "quantity": "2", "note": "Goodwill visits"}
    assert client.post(f"{M}/credits/adjust", headers=shop["rep"], json=body).status_code == 403
    assert client.post(f"{M}/credits/adjust", headers=shop["owner"], json={**body, "note": " "}).status_code == 422
    assert client.post(f"{M}/credits/adjust", headers=shop["boss"], json=body).status_code == 201
    assert balance(client, shop, m["id"]) == 6
    too_much = client.post(f"{M}/credits/adjust", headers=shop["boss"], json={**body, "quantity": "-7"})
    assert too_much.status_code == 422 and balance(client, shop, m["id"]) == 6
    assert client.post(f"{M}/credits/adjust", headers=shop["boss"], json={**body, "quantity": "-6"}).status_code == 201
    assert balance(client, shop, m["id"]) == 0


# --------------------------------------------------------------------------- packages
def test_selling_a_package_invoices_it_and_credits_pay_for_covered_services(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Package Pia")
    cid = UUID(cust["id"])
    sold = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "purchased_on": "2026-10-01"})
    assert sold.status_code == 201, sold.text
    p = sold.json()
    assert p["number"].startswith("PKG-") and D(p["balance"]) == 10 and p["expires_on"] == "2026-12-30"
    runs = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": p["id"]}).json()
    assert len(runs) == 1 and D(runs[0]["total"]) == D("500.00") and runs[0]["status"] == "issued"
    with system(shop) as s:
        facial = memberships.consume_credit(s, customer_id=cid, service_ref="facial", quantity=D(1),
                                            source_type="booking", source_id=uuid4())
        assert (facial.covered, facial.remaining) == (D(0), D(1))                         # the package covers massage only
        massage = memberships.consume_credit(s, customer_id=cid, service_ref="massage", quantity=D(2),
                                             source_type="booking", source_id=uuid4())
        assert massage.covered == D(2) and massage.covered_by[0][0] == "package"
        assert memberships.member_credit_balance(s, cid, "massage") == D(8)
        assert memberships.member_credit_balance(s, cid, "facial") == D(0)
    summary = client.get(f"{M}/customers/{cust['id']}/credits", headers=shop["owner"]).json()
    assert [D(x["balance"]) for x in summary["packages"]] == [D(8)] and summary["memberships"] == []


def test_a_package_expires_and_unused_credits_are_written_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Expiry Eve")
    p = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "purchased_on": "2026-01-01", "invoice": False}).json()
    assert p["expires_on"] == "2026-04-01"
    run_billing(shop, date(2026, 3, 31))
    assert client.get(f"{M}/sold-packages/{p['id']}", headers=shop["owner"]).json()["status"] == "active"
    run_billing(shop, date(2026, 4, 2))
    done = client.get(f"{M}/sold-packages/{p['id']}", headers=shop["owner"]).json()
    assert done["status"] == "expired" and D(done["balance"]) == 0
    assert [r.entry_type for r in rows(shop, "select entry_type from memberships.credit_entry where holder_id = :h "
                                              "order by seq", h=p["id"])] == ["purchase", "expiry"]
    assert runs_for(client, shop, p["id"]) == []                                       # sold without an invoice


def runs_for(client, shop, owner_id: str) -> list:  # type: ignore[no-untyped-def]
    return client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": owner_id}).json()


def test_a_package_that_is_not_used_up_can_be_refunded_by_someone_with_the_right(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Refund Rae")
    p = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    assert client.post(f"{M}/sold-packages/{p['id']}/refund", headers=shop["rep"], json={"note": "x"}).status_code == 403
    r = client.post(f"{M}/sold-packages/{p['id']}/refund", headers=shop["boss"], json={"note": "Changed her mind"})
    assert r.status_code == 200 and r.json()["status"] == "refunded" and D(r.json()["balance"]) == 0
    assert client.post(f"{M}/sold-packages/{p['id']}/refund", headers=shop["boss"],
                       json={"note": "again"}).status_code == 409


# --------------------------------------------------------------------------- recurring invoices
def schedule(client, shop, cust, **extra):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "customer_id": cust["id"],
            "name": "Rent", "billing_interval": "month", "start_date": "2026-09-01",
            "lines": [{"product_id": shop["delivery"], "description": "Monthly retainer", "quantity": "1",
                       "unit_price": "250.00"}], **extra}
    return client.post(f"{M}/recurring-invoices", headers=shop.get("acct", shop["owner"]), json=body)


def invoices_of(shop, cust) -> int:  # type: ignore[no-untyped-def]
    return int(scalar(shop, "select count(*) from pos.sales_invoice where customer_id = :c", c=cust["id"]))


def test_a_recurring_invoice_issues_each_period_exactly_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Retainer Ltd")
    made = schedule(client, shop, cust)
    assert made.status_code == 201, made.text
    s = made.json()
    assert D(s["total"]) == D("250.00") and s["next_run"] == "2026-09-01" and s["status"] == "active"
    assert client.post(f"{M}/recurring-invoices", headers=shop["rep"], json={}).status_code in (403, 422)
    run_billing(shop, date(2026, 8, 31))
    assert invoices_of(shop, cust) == 0
    run_billing(shop, date(2026, 9, 15))
    run_billing(shop, date(2026, 9, 15))                                                  # twice: still one
    assert invoices_of(shop, cust) == 1
    got = client.get(f"{M}/recurring-invoices/{s['id']}", headers=shop["owner"]).json()
    assert got["next_run"] == "2026-10-01" and got["last_run_status"] == "issued" and got["last_invoice_number"]
    run_billing(shop, date(2026, 11, 3))                                                  # October and November
    assert invoices_of(shop, cust) == 3
    assert client.get(f"{M}/recurring-invoices/{s['id']}", headers=shop["owner"]).json()["next_run"] == "2026-12-01"
    invoice = rows(shop, "select i.total, l.description from pos.sales_invoice i join pos.sales_invoice_line l "
                         "on l.invoice_id = i.id where i.customer_id = :c limit 1", c=cust["id"])[0]
    assert invoice.total == D("250.00") and invoice.description == "Monthly retainer"


def test_a_schedule_with_a_run_limit_ends_by_itself(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Term Fees Ltd")
    s = schedule(client, shop, cust, name="Term fees", max_runs=2, start_date="2026-01-01").json()
    run_billing(shop, date(2026, 6, 1))
    assert invoices_of(shop, cust) == 2
    assert client.get(f"{M}/recurring-invoices/{s['id']}", headers=shop["owner"]).json()["status"] == "ended"
    ended_on = schedule(client, shop, cust, name="Until", start_date="2026-01-01", end_date="2026-02-15").json()
    run_billing(shop, date(2026, 6, 1))
    assert client.get(f"{M}/recurring-invoices/{ended_on['id']}", headers=shop["owner"]).json()["status"] == "ended"
    assert invoices_of(shop, cust) == 4


def test_a_draft_schedule_waits_for_a_person_to_issue_or_discard(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Draft Dan")
    s = schedule(client, shop, cust, name="Reviewed", mode="draft", start_date="2026-07-01").json()
    run_billing(shop, date(2026, 8, 5))
    assert invoices_of(shop, cust) == 0
    waiting = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={
        "owner_id": s["id"], "status": "pending_review"}).json()
    waiting.sort(key=lambda r: r["period_start"])
    assert [r["period_start"] for r in waiting] == ["2026-07-01", "2026-08-01"]
    run_billing(shop, date(2026, 8, 5))
    assert len(client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": s["id"]}).json()) == 2
    assert client.post(f"{M}/invoice-runs/{waiting[0]['id']}/issue", headers=shop["cashier"]).status_code == 403
    issued = client.post(f"{M}/invoice-runs/{waiting[0]['id']}/issue", headers=shop["fm"])
    assert issued.status_code == 200 and issued.json()["status"] == "issued" and invoices_of(shop, cust) == 1
    assert client.post(f"{M}/invoice-runs/{waiting[0]['id']}/issue", headers=shop["fm"]).status_code == 409
    assert client.post(f"{M}/invoice-runs/{waiting[1]['id']}/discard", headers=shop["fm"],
                       json={"note": "  "}).status_code == 422
    gone = client.post(f"{M}/invoice-runs/{waiting[1]['id']}/discard", headers=shop["fm"], json={"note": "Closed"})
    assert gone.json()["status"] == "discarded" and invoices_of(shop, cust) == 1


def test_a_paused_schedule_skips_the_periods_it_was_paused_for(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Pause Co")
    s = schedule(client, shop, cust, name="Pausable", start_date="2026-04-01").json()
    run_billing(shop, date(2026, 4, 3))
    assert invoices_of(shop, cust) == 1
    assert client.post(f"{M}/recurring-invoices/{s['id']}/pause", headers=shop["acct"], json={}).json()[
        "status"] == "paused"
    run_billing(shop, date(2026, 7, 10))
    assert invoices_of(shop, cust) == 1
    back = client.post(f"{M}/recurring-invoices/{s['id']}/resume", headers=shop["acct"])
    assert back.status_code == 200 and back.json()["status"] == "active"
    assert back.json()["next_run"] >= "2026-05-01"
    run_billing(shop, date(2026, 7, 10))
    assert invoices_of(shop, cust) <= 4


def test_a_failing_recurring_invoice_is_flagged_and_never_issued_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Tight Credit", limit="300")
    s = schedule(client, shop, cust, name="Tight", start_date="2026-01-01").json()
    run_billing(shop, date(2026, 3, 5))                  # three invoices of 250.00 do not fit in a 300.00 limit
    got = client.get(f"{M}/recurring-invoices/{s['id']}", headers=shop["owner"]).json()
    assert got["last_run_status"] == "failed" and invoices_of(shop, cust) == 1
    assert got["next_run"] == "2026-02-01"               # the failed period is tried again, none is passed over
    flagged = rows(shop, "select count(*) as n from kernel.exception_item where kind = 'recurring_invoice_failed' "
                         "and ref_id in (select id from memberships.invoice_run where owner_id = :s)", s=s["id"])
    assert flagged[0].n == 1
    run_billing(shop, date(2026, 3, 5))
    assert invoices_of(shop, cust) == 1
    client.post(f"/api/v1/crm/customers/{cust['id']}/credit", headers=shop["fm"], json={
        "credit_limit": "100000", "payment_terms_days": 14, "reason": "Raised"})
    run_billing(shop, date(2026, 3, 5))
    assert invoices_of(shop, cust) == 3
    assert client.get(f"{M}/recurring-invoices/{s['id']}", headers=shop["owner"]).json()["next_run"] == "2026-04-01"
    # "run now" does the same work on demand, and cannot double up either
    assert client.post(f"{M}/recurring-invoices/{s['id']}/run", headers=shop["acct"]).status_code == 200
    assert invoices_of(shop, cust) >= 3


def test_the_overview_counts_what_needs_attention(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{M}/summary", headers=shop["owner"])
    assert r.status_code == 200 and set(r.json()) >= {"active_members", "failed_runs", "drafts_waiting"}
    assert r.json()["active_members"] >= 5
    assert client.get(f"{M}/invoicing", headers=shop["owner"]).json() == {"available": True}
