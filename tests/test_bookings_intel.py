"""Intelligence checks and Command Center figures over bookings, the personal-data provider, the integrity check, and
the small public functions other units use. A real business, the real engine, today is 2026-10-14."""

from datetime import date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.bookings_helpers import ZONE, B, make_salon, reason
from tests.stock_helpers import system
from ziira.modules.bookings import intel_checks
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import engine

TODAY = date(2026, 10, 14)
INTEL = "/api/v1/intel"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Intel Salon", units=("intel", "command"))
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    return s


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=ZONE).astimezone()


def add(shop, resource: str, start: datetime, status: str, **extra: Any) -> str:  # type: ignore[no-untyped-def]
    """An appointment straight in the tables (the services have their own tests): a 60 minute one."""
    ident = str(uuid4())
    end = start + timedelta(minutes=60)
    sql(shop, "insert into bookings.appointment (id, tenant_id, company_id, branch_id, number, offer_id, status, starts_at, ends_at, "
              "client_name, price, customer_id, completed_at, late_cancellation, cancelled_at) values (:i, :t, :c, :b, :n, :o, :s, :a, :e, "
              "'Someone', :p, :cu, :done, :late, :cx)",
        i=ident, t=str(shop["tenant_id"]), c=str(shop["company_id"]), b=str(shop["branch_id"]), n=f"T-{ident[:8]}", o=shop["cut"],
        s=status, a=start, e=end, p=extra.get("price", Dec("58.00")), cu=extra.get("customer"), done=end if status == "completed" else None,
        late=extra.get("late", False), cx=end if status == "cancelled" else None)
    sql(shop, "insert into bookings.appointment_resource (tenant_id, appointment_id, resource_id, blocked, holds) "
              "values (:t, :a, :r, tstzrange(:s, :e, '[)'), :h)", t=str(shop["tenant_id"]), a=ident, r=resource, s=start, e=end,
        h=status not in ("cancelled", "no_show"))
    return ident


def run_check(shop, code: str, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=lambda metric, key: None, timezone="UTC")
        return check.run(s, ctx)


def findings(client, shop, code: str, *statuses: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {"check_code": code, "limit": 100}
    named = [s for s in statuses if s != "open"]             # "open" is what the list returns when no status is named
    if named:
        params["status"] = named
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- no-shows
def test_no_show_rate_is_flagged_silent_below_the_limit_tuned_and_resolved(client, shop) -> None:  # type: ignore[no-untyped-def]
    for i in range(6):                                       # Anna: 3 of 6 missed (50%); Brian: 1 of 6 (17%)
        add(shop, shop["anna"], at(1 + i, 9), "no_show" if i < 3 else "completed")
        add(shop, shop["brian"], at(1 + i, 11), "no_show" if i == 0 else "completed")
    found = direct(shop, intel_checks.NoShowRate())
    assert [(c.entity_id, c.value) for c in found] == [(__import__("uuid").UUID(shop["anna"]), Dec("50.0"))]
    assert found[0].severity == "high" and "3 of 6" in found[0].summary and found[0].branch_id == shop["branch_id"]
    assert direct(shop, intel_checks.NoShowRate(), no_show_percent="60") == []                  # the business may set a higher limit
    assert [c.entity_id for c in direct(shop, intel_checks.NoShowRate(), no_show_percent="10")].__len__() == 2
    assert direct(shop, intel_checks.NoShowRate(), min_appointments=7) == []                    # too few to judge
    run_check(shop, "bookings.no_show_rate")
    assert len(findings(client, shop, "bookings.no_show_rate", "open")) == 1
    sql(shop, "update bookings.appointment set status = 'completed' where status = 'no_show'")
    run_check(shop, "bookings.no_show_rate")
    assert findings(client, shop, "bookings.no_show_rate", "open") == []                        # resolves by itself


def test_late_cancellations(client, shop) -> None:  # type: ignore[no-untyped-def]
    for i in range(4):
        add(shop, shop["anna"], at(8, 9 + i), "cancelled", late=True)
    assert direct(shop, intel_checks.LateCancellations()) == []                                  # 4 is under the limit of 5
    add(shop, shop["anna"], at(9, 9), "cancelled", late=True)
    found = direct(shop, intel_checks.LateCancellations())
    assert len(found) == 1 and found[0].value == Dec(5) and found[0].branch_id == shop["branch_id"]
    assert direct(shop, intel_checks.LateCancellations(), late_cancel_count=6) == []


def test_unused_working_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    # Brian works 40 hours a week; over the last 14 days (10 working days = 80 hours) he has few bookings
    found = {c.entity_id: c for c in direct(shop, intel_checks.LowUtilisation())}
    brian = found[__import__("uuid").UUID(shop["brian"])]
    assert brian.severity == "low" and brian.value < Dec(30) and "working time" in brian.summary
    assert direct(shop, intel_checks.LowUtilisation(), utilisation_percent="0.1") == []
    assert direct(shop, intel_checks.LowUtilisation(), min_hours=1000) == []                     # not enough hours to judge


def test_refused_double_bookings(client, shop) -> None:  # type: ignore[no-untyped-def]
    for _ in range(5):
        sql(shop, "insert into bookings.booking_refusal (tenant_id, company_id, branch_id, attempted_start, source, created_at) "
                  "values (:t, :c, :b, :a, 'staff', :n)", t=str(shop["tenant_id"]), c=str(shop["company_id"]),
            b=str(shop["branch_id"]), a=at(20, 9), n=datetime(2026, 10, 13, 12, 0))
    sql(shop, "insert into bookings.booking_refusal (tenant_id, company_id, branch_id, attempted_start, source, created_at) "
              "values (:t, :c, :b, :a, 'recurring', :n)", t=str(shop["tenant_id"]), c=str(shop["company_id"]),
        b=str(shop["branch_id"]), a=at(20, 9), n=datetime(2026, 10, 13, 12, 0))
    found = direct(shop, intel_checks.DoubleBookingRefused())
    assert len(found) == 1 and found[0].value == Dec(5)                                           # repeats do not count
    assert direct(shop, intel_checks.DoubleBookingRefused(), refused_count=6) == []


def test_long_gaps_in_the_diary(client, shop) -> None:  # type: ignore[no-untyped-def]
    add(shop, shop["brian"], at(15, 9), "confirmed")
    add(shop, shop["brian"], at(15, 14), "confirmed")                                             # 10:00 to 14:00: a 4 hour gap
    add(shop, shop["brian"], at(16, 9), "confirmed")
    add(shop, shop["brian"], at(16, 10), "confirmed")                                             # back to back: none
    found = direct(shop, intel_checks.LongIdleGaps())
    gaps = [c for c in found if c.period_start == date(2026, 10, 15)]
    assert len(gaps) == 1 and gaps[0].value == Dec(240) and "4 h 0 min" in gaps[0].summary
    assert not [c for c in found if c.period_start == date(2026, 10, 16)]
    assert direct(shop, intel_checks.LongIdleGaps(), gap_minutes=300) == []


def test_finished_appointments_never_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    customer = shop["customer"]["id"]
    add(shop, shop["anna"], at(5, 15), "completed", customer=customer)
    add(shop, shop["anna"], at(6, 15), "completed")                                               # no customer: not billable yet
    sql(shop, "update bookings.appointment set invoice_id = :i where number in (select number from bookings.appointment "
              "where status = 'completed' and customer_id is not null and starts_at < :s)", i=str(uuid4()), s=at(5, 0))
    found = direct(shop, intel_checks.CompletedNotInvoiced())
    assert len(found) == 1 and found[0].amount == Dec("58.00") and "no invoice" in found[0].summary
    assert direct(shop, intel_checks.CompletedNotInvoiced(), invoice_after_days=30) == []
    run_check(shop, "bookings.completed_not_invoiced")
    assert len(findings(client, shop, "bookings.completed_not_invoiced", "open")) == 1


# --------------------------------------------------------------------------- the Command Center
def test_the_command_center_figures(client, shop) -> None:  # type: ignore[no-untyped-def]
    add(shop, shop["anna"], at(14, 9), "completed")
    add(shop, shop["anna"], at(14, 11), "no_show")
    add(shop, shop["brian"], at(14, 9), "confirmed")
    add(shop, shop["brian"], at(14, 11), "cancelled")
    add(shop, shop["brian"], at(14, 13), "requested")
    from ziira.modules.bookings.pulse import BookingsPulse

    with system(shop) as s:
        figures = {f.metric: f.value for f in BookingsPulse().figures(s, shop["company_id"], TODAY)}
    assert figures == {"bookings.appointments": Dec(4), "bookings.completed": Dec(1), "bookings.no_shows": Dec(1),
                       "bookings.requests_waiting": Dec(sql(shop, "select count(*) from bookings.appointment "
                                                                  "where status = 'requested'")[0][0])}
    assert pulse is not None


# --------------------------------------------------------------------------- personal data
def test_the_personal_data_provider_finds_exports_and_erases(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings.privacy import BookingsPersonalData
    from ziira.sdk import Subject

    done = add(shop, shop["anna"], at(2, 15), "completed")
    sql(shop, "update bookings.appointment set client_name = 'Private Person', client_phone = '254733445566', "
              "client_email = 'private@example.test', note = 'allergic' where id = :i", i=done)
    live = add(shop, shop["anna"], datetime.now(ZONE).astimezone() + timedelta(days=3), "confirmed")
    sql(shop, "update bookings.appointment set client_name = 'Private Person', client_phone = '254733445566' where id = :i", i=live)
    provider = BookingsPersonalData()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], Subject(raw="254733445566", phone="254733445566"))
        assert {r.record_id.hex for r in found} >= {done.replace("-", ""), live.replace("-", "")}
        record = next(r for r in found if str(r.record_id) == done)
        assert "allergic" in str(provider.export(s, record))
        outcome = provider.anonymise(s, record, "asked")
        assert outcome.status == "anonymised"
        blocked = provider.anonymise(s, next(r for r in found if str(r.record_id) == live), "asked")
        assert blocked.status == "partial" and blocked.kept          # still to come: the name is needed
    row = sql(shop, "select client_name, client_phone, client_email, note from bookings.appointment where id = :i", i=done)[0]
    assert row[1:] == (None, None, None) and "Private Person" not in row[0]
    assert sql(shop, "select client_phone from bookings.appointment where id = :i", i=live) == [("254733445566",)]


def test_the_integrity_check_finds_and_fixes_a_stale_hold(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings.hooks import AppointmentHoldsCheck

    ident = add(shop, shop["brian"], at(26, 9), "cancelled")
    sql(shop, "update bookings.appointment_resource set holds = true where appointment_id = :a", a=ident)
    with system(shop) as s:
        problems = AppointmentHoldsCheck().run(s)
        assert any("still holds" in p for p in problems)
        AppointmentHoldsCheck().run(s, fix=True)
    with system(shop) as s:
        assert AppointmentHoldsCheck().run(s) == []


# --------------------------------------------------------------------------- what other units use
def test_products_lists_service_items_and_crm_matches_or_creates(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.crm.public import match_or_create_customer
    from ziira.modules.products.public import service_items

    with system(shop) as s:
        items = service_items(s, shop["company_id"])
        assert [i.sku for i in items] == ["DELIVERY"] and all(i.product_type == "service" for i in items)
        assert service_items(s, shop["company_id"], "zzz") == []
        made, created = match_or_create_customer(s, shop["company_id"], name="Fresh Face", phone="0788000111")
        again, created_again = match_or_create_customer(s, shop["company_id"], name="Other Name", phone="+254 788 000 111")
        by_email, _ = match_or_create_customer(s, shop["company_id"], name="Mail", email="MAIL@example.test")
        same_mail, mail_new = match_or_create_customer(s, shop["company_id"], name="Mail 2", email="mail@example.test")
        assert created and not created_again and made.id == again.id and made.phone == "254788000111"
        assert by_email.id == same_mail.id and not mail_new
        with pytest.raises(Exception, match="phone number or an email"):
            match_or_create_customer(s, shop["company_id"], name="Nobody")


def test_plain_text_exists_for_every_check() -> None:
    from ziira.modules.intel.domain import plain

    for check in intel_checks.ALL_CHECKS:
        for lang in plain.LANGS:
            p = plain.plain_check(check.code, lang, fallback_title=check.title, area=check.area, params=check.params)
            assert p.title and p.why and p.todo and p.topic == ("cash" if check.code == "bookings.tips_held" else "customers")
    assert reason is not None and B
