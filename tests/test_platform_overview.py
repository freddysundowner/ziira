"""The Super Admin's frame and landing page: search, alerts, set-up checklist, trends, feeds and the audit trail."""

from datetime import UTC, date, datetime
from decimal import Decimal as D  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from tests.platform_helpers import API, staff
from tests.test_operator_console import trail
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import overview

ALL = frozenset({"platform.view", "platform.subscribers", "platform.billing", "platform.units", "platform.licences",
                 "platform.settings", "platform.ai", "platform.operators"})


@pytest.fixture(scope="module")
def world(client, registry):  # type: ignore[no-untyped-def]
    make_tenant("Ovw Alpha")
    make_tenant("Ovw Beta")
    yield {"boss": staff(client, "superadmin"), "support": staff(client, "support"), "viewer": staff(client, "readonly"),
           "billing": staff(client, "billing")}


# --------------------------------------------------------------------------- pure rules
def test_twelve_month_buckets_end_with_the_current_month() -> None:
    starts = overview.bucket_starts("12m", date(2030, 3, 15))
    assert len(starts) == 12
    assert starts[0] == date(2029, 4, 1) and starts[-1] == date(2030, 3, 1)
    assert overview.bucket_starts("12m", date(2030, 12, 31))[0] == date(2030, 1, 1)


def test_twelve_week_buckets_start_on_mondays() -> None:
    starts = overview.bucket_starts("12w", date(2030, 3, 15))                       # a Friday
    assert starts[-1] == date(2030, 3, 11) and starts[0] == date(2029, 12, 24)      # 11 weeks earlier
    assert all(s.weekday() == 0 for s in starts)


def test_an_unknown_range_or_metric_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        overview.bucket_starts("5y", date(2030, 1, 1))
    with pytest.raises(ValidationFailed):
        overview.series("profit", "12m")


def test_series_fill_zero_and_keep_currencies_apart() -> None:
    starts = overview.bucket_starts("12m", date(2030, 3, 15))
    lines = overview.fill_series(starts, {("KES", date(2030, 2, 1)): D("150.50"), ("USD", date(2030, 3, 1)): D("20")})
    assert [x["currency"] for x in lines] == ["KES", "USD"]
    assert lines[0]["points"][-2] == "150.50" and lines[0]["points"][-1] == "0" and lines[0]["points"][0] == "0"
    assert lines[1]["points"][-1] == "20"


def test_wildcards_typed_in_search_are_plain_characters() -> None:
    assert overview._like("50%_off\\") == "%50\\%\\_off\\\\%"


FACTS = {"payments_attention": 2, "past_due": 3, "suspended": 0, "trials_ending": 1, "licences_expiring": 0,
         "pending_requests": 4, "failed_jobs": 0, "businesses_behind": 2, "businesses_unreadable": 0,
         "plugins_refused": 0, "ready": True, "problems": 0, "backup_reported": True, "backup_age_hours": 30.0,
         "mail_working": False, "ai_cap_reached": True}


def test_alerts_come_worst_first_and_only_for_areas_the_role_can_act_in() -> None:
    everything = overview.build_alerts(FACTS, ALL)
    assert [(a["key"], a["count"]) for a in everything] == [
        ("backup_old", 1), ("payments_attention", 2),                     # bad, by key
        ("ai_cap_reached", 1), ("businesses_behind", 2), ("mail_not_working", 1), ("past_due", 3),
        ("pending_requests", 4),                                           # warn
        ("trials_ending", 1)]                                              # info
    billing = overview.build_alerts(FACTS, frozenset({"platform.view", "platform.subscribers", "platform.billing"}))
    assert [a["key"] for a in billing] == ["payments_attention", "past_due", "pending_requests", "trials_ending"]
    assert overview.build_alerts(FACTS, frozenset({"platform.view"})) == []


def test_a_fresh_backup_or_unreported_backups_raise_nothing() -> None:
    assert overview.build_alerts({"backup_reported": True, "backup_age_hours": 20.0}, ALL) == []
    assert overview.build_alerts({"backup_reported": False, "backup_age_hours": None}, ALL) == []
    assert [a["key"] for a in overview.build_alerts({"backup_reported": True, "backup_age_hours": None}, ALL)] \
        == ["backup_old"]                                                  # backups exist as a place but none was taken


def test_risks_name_the_dangerous_settings_the_role_can_fix() -> None:
    def risks(perms=ALL, **kw):  # type: ignore[no-untyped-def]
        base = {"environment": "production", "mfa_off": False, "mail_working": True, "registration_mode": "closed",
                "ai_has_provider": True, "permissions": perms}
        return [r["key"] for r in overview.build_risks(**{**base, **kw})]
    assert risks() == []
    assert risks(mfa_off=True) == ["mfa_off"]
    assert risks(mail_working=False, registration_mode="open") == ["registration_without_email"]
    assert risks(mail_working=False) == ["mail_not_configured"]
    assert risks(ai_has_provider=False) == ["no_ai_provider"]
    assert risks(perms=frozenset({"platform.view"}), mail_working=False, ai_has_provider=False) == []


# --------------------------------------------------------------------------- the database
def test_revenue_is_summed_per_month_and_currency_and_ignores_reversed_payments(world) -> None:  # type: ignore[no-untyped-def]
    invoice = uuid4()
    with master_session() as m:
        m.execute(text("insert into master.billing_invoice (id, currency, status, total, amount_paid) "
                       "values (:i, 'KES', 'paid', 100, 100)"), {"i": invoice})
        for paid_on, amount, currency, reversed_ in (("2041-02-10", "100.00", "KES", False), ("2041-02-20", "50.50", "KES", False),
                                                     ("2041-03-05", "20.00", "USD", False), ("2041-03-06", "999.00", "KES", True)):
            m.execute(text("insert into master.billing_payment (invoice_id, method, amount, currency, paid_on, reversed_at) "
                           "values (:i, 'cash', :a, :c, :d, case when :r then now() end)"),
                      {"i": invoice, "a": amount, "c": currency, "d": paid_on, "r": reversed_})
    try:
        out = overview.series("revenue", "12m", today=date(2041, 3, 15))
        by = {x["currency"]: x["points"] for x in out["series"]}
        assert by["KES"][-2] == "150.50" and by["KES"][-1] == "0"           # February; the reversed March payment is out
        assert by["USD"][-1] == "20.00" and by["USD"][-2] == "0"
        weekly = overview.series("revenue", "12w", today=date(2041, 3, 15))
        kes = {x["currency"]: x["points"] for x in weekly["series"]}["KES"]
        assert kes[6] == "100.00" and kes[8] == "50.50" and kes[7] == "0"   # weeks of Feb 4 and Feb 18 (a Sunday and a Wednesday)
        feed = overview.feed(limit=50)
        assert any(p["amount"] == D("50.50") and p["reversed"] is False for p in feed["payments"])
    finally:
        with master_session() as m:
            m.execute(text("delete from master.billing_payment where invoice_id = :i"), {"i": invoice})
            m.execute(text("delete from master.billing_invoice where id = :i"), {"i": invoice})


def test_signups_count_the_businesses_created_in_each_bucket(world) -> None:  # type: ignore[no-untyped-def]
    before = overview.series("signups", "12m")["series"][0]["points"][-1]
    make_tenant(f"Ovw Gamma {uuid4().hex[:6]}")
    after = overview.series("signups", "12m")["series"][0]["points"][-1]
    assert int(after) == int(before) + 1


def test_search_finds_by_name_and_code_and_hides_operators_from_roles_without_the_permission(client, world) -> None:  # type: ignore[no-untyped-def]
    hits = client.get(f"{API}/operator/search", params={"q": "ovw-alp"}, headers=world["support"]["headers"]).json()
    assert [(h["kind"], h["id"], h["to"]) for h in hits if h["kind"] == "subscriber"] == [
        ("subscriber", "ovw-alpha", "/operator/subscribers/ovw-alpha")]
    by_name = client.get(f"{API}/operator/search", params={"q": "Ovw Beta"}, headers=world["support"]["headers"]).json()
    assert {h["id"] for h in by_name} == {"ovw-beta"}
    mail = world["boss"]["email"]
    assert any(h["kind"] == "operator" for h in client.get(f"{API}/operator/search", params={"q": mail},
                                                          headers=world["boss"]["headers"]).json())
    assert not any(h["kind"] == "operator" for h in client.get(f"{API}/operator/search", params={"q": mail},
                                                              headers=world["support"]["headers"]).json())


def test_search_needs_two_characters_and_treats_wildcards_as_text(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    assert client.get(f"{API}/operator/search", params={"q": "o"}, headers=boss).json() == []
    assert client.get(f"{API}/operator/search", params={"q": "%%"}, headers=boss).json() == []
    assert client.get(f"{API}/operator/search", params={"q": "x" * 101}, headers=boss).status_code == 422


def test_alerts_for_a_role_without_areas_are_empty_and_others_have_the_shape(client, world) -> None:  # type: ignore[no-untyped-def]
    overview.clear_cache()
    quiet = client.get(f"{API}/operator/alerts", headers=world["viewer"]["headers"]).json()
    assert quiet == {"total": 0, "worst": None, "items": []}
    loud = client.get(f"{API}/operator/alerts", headers=world["boss"]["headers"]).json()
    assert loud["total"] == len(loud["items"])
    assert all({"key", "severity", "count", "to", "needs"} == set(a) for a in loud["items"])
    assert all(a["needs"] in ALL for a in loud["items"])


def test_system_tiles_are_counts_and_never_secrets(client, world) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/operator/dashboard/system", headers=world["viewer"]["headers"])
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["ready"], bool) and body["ai_spend_usd"].replace(".", "").isdigit()
    assert "key" not in " ".join(body)


def test_setup_lists_each_step_and_risks_follow_the_role(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = client.get(f"{API}/operator/setup", headers=world["boss"]["headers"]).json()
    assert [i["key"] for i in boss["items"]] == ["email", "registration", "ai", "payments", "plans", "website", "licence"]
    assert next(i for i in boss["items"] if i["key"] == "licence")["optional"] is True
    assert boss["environment"] and boss["mode"] in ("saas", "selfhosted")
    viewer = client.get(f"{API}/operator/setup", headers=world["viewer"]["headers"]).json()
    assert [r for r in viewer["risks"] if r["needs"] != "platform.view"] == []


def test_the_dashboard_series_endpoint_checks_its_arguments(client, world) -> None:  # type: ignore[no-untyped-def]
    ok = client.get(f"{API}/operator/dashboard/series", params={"metric": "signups", "range": "12w"},
                    headers=world["viewer"]["headers"])
    assert ok.status_code == 200 and len(ok.json()["buckets"]) == 12
    assert client.get(f"{API}/operator/dashboard/series", params={"metric": "profit"},
                      headers=world["viewer"]["headers"]).status_code == 422


def test_the_audit_trail_filters_and_exports_a_safe_csv_that_is_itself_logged(client, world) -> None:  # type: ignore[no-untyped-def]
    tag = f"ovw-{uuid4().hex[:6]}"
    with master_session() as m:
        for who, action, target, outcome, when in (
                ("Ann Audit", "plan.update", f"{tag}-a", "ok", datetime(2041, 5, 1, 23, 30, tzinfo=UTC)),
                ("Bob Audit", "plan.update", f"={tag}-b", "refused", datetime(2041, 5, 3, 1, 0, tzinfo=UTC)),
                ("Ann Audit", "invoice.void", f"{tag}-c", "ok", datetime(2041, 5, 9, 12, 0, tzinfo=UTC))):
            m.execute(text("insert into master.operator_action_log (operator_id, operator_name, action, target, outcome, "
                           "occurred_at) values (:o, :n, :a, :t, :out, :w)"),
                      {"o": uuid4(), "n": who, "a": action, "t": target, "out": outcome, "w": when})
    boss = world["boss"]["headers"]

    def lines(**params):  # type: ignore[no-untyped-def]
        r = client.get(f"{API}/operator/audit", params={"target": tag, **params}, headers=boss)
        assert r.status_code == 200, r.text
        return r.json()

    assert lines()["total"] == 3
    assert [x["target"] for x in lines(operator="ann")["items"]] == [f"{tag}-c", f"{tag}-a"]      # newest first
    assert lines(action="invoice")["total"] == 1 and lines(outcome="refused")["total"] == 1
    assert lines(date_from="2041-05-02", date_to="2041-05-03")["total"] == 1                    # the 3rd, to the end of the day
    assert lines(date_from="2041-05-01", date_to="2041-05-01")["total"] == 1
    assert client.get(f"{API}/operator/audit", params={"date_from": "2041-05-09", "date_to": "2041-05-01"},
                      headers=boss).status_code == 422
    assert lines(limit=1, offset=1)["items"][0]["target"] == f"={tag}-b"
    export = client.get(f"{API}/operator/audit/export", params={"target": tag}, headers=boss)
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    rows = export.text.strip().split("\r\n")
    assert rows[0] == "When (UTC),Operator,Action,Target,Outcome,Reason" and len(rows) == 4
    assert f"'={tag}-b" in export.text and f",={tag}-b" not in export.text                       # defused for spreadsheets
    assert [x["detail"]["lines"] for x in trail("audit.export")][-1] == 3
    for role in ("support", "viewer", "billing"):
        assert client.get(f"{API}/operator/audit", headers=world[role]["headers"]).status_code == 403
        assert client.get(f"{API}/operator/audit/export", headers=world[role]["headers"]).status_code == 403
