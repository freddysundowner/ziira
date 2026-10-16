"""The channel layer's rules that need no database: template wording, quiet hours, the Lead Intel request shapes, error
mapping and the webhook signature."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest

from ziira.kernel import templates
from ziira.kernel.messaging import quiet_until
from ziira.plugins.leadsintel import providers, unverified
from ziira.plugins.leadsintel.client import LeadIntelClient, LeadIntelError
from ziira.plugins.leadsintel.services import webhook
from ziira.sdk import Outgoing, TemplateSpec, ValidationFailed

NAIROBI = ZoneInfo("Africa/Nairobi")


# --------------------------------------------------------------------------- the shipped templates
def test_every_shipped_template_has_english_and_swahili_wording_that_uses_only_its_variables() -> None:
    catalogue = templates.catalogue()
    assert set(catalogue) == {"daily_brief", "urgent_alert", "overdue_reminder", "payment_due", "action_proposal",
                              "verification_code"}
    for shipped in catalogue.values():
        assert set(shipped.text) == {"en", "sw"}
        assert len(shipped.examples) == len(shipped.variables)
        for words in shipped.text.values():
            assert set(templates.PLACEHOLDER.findall(words["body"])) <= set(shipped.variables)
            assert words["subject"].strip()
    assert [b[0] for b in catalogue["action_proposal"].buttons["en"]] == ["approve", "reject", "why"]
    assert all(len(title) <= 20 for rows in catalogue["action_proposal"].buttons.values() for _, title in rows)


def test_a_template_is_filled_in_the_chosen_language_and_variables_are_cleaned() -> None:
    values = {"customer": "Juma", "invoice": "INV-7", "amount": "KES 1,200.00", "business": "Mama Shop",
              "due_date": "2026-09-30"}
    subject, body = templates.render("overdue_reminder", "en", values)
    assert subject == "Payment reminder"
    assert body.startswith("Dear Juma, invoice INV-7 of KES 1,200.00 to Mama Shop was due on 2026-09-30.")
    assert templates.render("overdue_reminder", "sw", values)[1].startswith("Mpendwa Juma, ankara INV-7 ya KES 1,200.00")
    assert templates.render("overdue_reminder", "fr", values)[1] == body                    # unknown language: English
    messy = {**values, "customer": "  Juma\n\n  Mwangi\t "}
    assert "Dear Juma Mwangi," in templates.render("overdue_reminder", "en", messy)[1]
    with pytest.raises(ValidationFailed, match="needs: amount"):
        templates.render("overdue_reminder", "en", {k: v for k, v in values.items() if k != "amount"})
    with pytest.raises(ValidationFailed, match="Unknown message template"):
        templates.render("nope", "en", {})
    assert len(templates.clean_value("x" * 5000)) == templates.MAX_VALUE


def test_positional_placeholders_follow_the_variable_order() -> None:
    assert templates.positional("Hi {name}, {business} says {summary}. Bye {name}", ("name", "business", "summary")) == \
        "Hi {{1}}, {{2}} says {{3}}. Bye {{1}}"


# --------------------------------------------------------------------------- quiet hours
def at(hour: int, minute: int = 0, day: int = 14) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NAIROBI)


def test_quiet_hours_across_midnight_defer_to_the_end() -> None:
    start, end = time(21, 0), time(7, 0)
    assert quiet_until(at(12), start, end) is None
    assert quiet_until(at(20, 59), start, end) is None
    assert quiet_until(at(21), start, end) == at(7, day=15)                                  # evening: until tomorrow
    assert quiet_until(at(23, 30), start, end) == at(7, day=15)
    assert quiet_until(at(2), start, end) == at(7)                                           # small hours: until 07:00
    assert quiet_until(at(6, 59), start, end) == at(7)
    assert quiet_until(at(7), start, end) is None


def test_quiet_hours_within_one_day_and_equal_times() -> None:
    assert quiet_until(at(13), time(12, 0), time(14, 0)) == at(14)
    assert quiet_until(at(14), time(12, 0), time(14, 0)) is None
    assert quiet_until(at(11, 59), time(12, 0), time(14, 0)) is None
    assert quiet_until(at(3), time(8, 0), time(8, 0)) is None                                # no period at all


# --------------------------------------------------------------------------- Lead Intel request shapes
def out(**kw) -> Outgoing:  # type: ignore[no-untyped-def]
    return Outgoing(UUID(int=7), uuid4(), "254712345678", None, kw.pop("body", "Hello there"), **kw)


def test_a_free_form_message_is_sent_as_flat_text() -> None:
    assert providers.whatsapp_body(out()) == {"to": "254712345678", "type": "text", "text": "Hello there"}
    assert len(providers.whatsapp_body(out(body="x" * 9000))["text"]) == providers.TEXT_MAX


def test_reply_buttons_are_limited_to_what_whatsapp_allows() -> None:
    body = providers.whatsapp_body(out(mode="buttons", buttons=(("approve:1", "Approve"), ("reject:1", "Reject"),
                                                                ("why:1", "A title far longer than twenty"), ("x", "4th"))))
    assert body["type"] == "buttons" and body["body"] == "Hello there"
    assert body["buttons"] == [{"id": "approve:1", "title": "Approve"}, {"id": "reject:1", "title": "Reject"},
                               {"id": "why:1", "title": "A title far longer t"}]               # 3 at most, 20 characters
    long = providers.whatsapp_body(out(mode="buttons", buttons=(("a", "A"),), body="y" * 2000))
    assert len(long["body"]) == providers.BUTTON_BODY_MAX and long["body"].endswith("…")


def test_a_template_message_carries_its_parameters_and_quick_reply_payloads() -> None:
    body = providers.whatsapp_body(out(mode="template", template_name="ziira_action_proposal", template_language="sw",
                                       template_params=("Mama Shop", "Remind Juma"),
                                       buttons=(("approve:abc", "Idhinisha"), ("reject:abc", "Kataa"))))
    assert body == {"to": "254712345678", "type": "template", "name": "ziira_action_proposal", "language": "sw",
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": "Mama Shop"},
                                                        {"type": "text", "text": "Remind Juma"}]},
                        {"type": "button", "sub_type": "quick_reply", "index": "0",
                         "parameters": [{"type": "payload", "payload": "approve:abc"}]},
                        {"type": "button", "sub_type": "quick_reply", "index": "1",
                         "parameters": [{"type": "payload", "payload": "reject:abc"}]}]}


def test_the_idempotency_key_is_stable_per_message_and_mode_and_short_enough() -> None:
    message = out()
    assert providers.idempotency_key(message) == providers.idempotency_key(out()) == f"ziira-{UUID(int=7)}-text"
    assert providers.idempotency_key(out(mode="template")) != providers.idempotency_key(message)   # other content
    assert len(providers.idempotency_key(message)) <= 200


def call(handler, message=None, **config):  # type: ignore[no-untyped-def]
    from ziira.plugins.leadsintel import client as client_module

    previous = client_module.client_factory
    client_module.client_factory = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    try:
        return providers.LeadIntelWhatsApp().send(
            message or out(), {"platform_key": "li_platform_SECRET", "webhook_secret": "s"},
            {"tenant_ref": "T1", "connection_id": "C1", **config})
    finally:
        client_module.client_factory = previous


def test_a_send_goes_to_the_documented_address_with_the_key_and_idempotency_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"messageId": "wamid.1", "status": "accepted"})

    result = call(handler)
    assert result.accepted and result.provider_ref == "wamid.1"
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://app.leadsintel.net/api/external-platform/whatsapp/connections/T1/C1/send"
    assert request.headers["authorization"] == "Bearer li_platform_SECRET"
    assert request.headers["idempotency-key"] == f"ziira-{UUID(int=7)}-text"
    assert json.loads(request.content) == {"to": "254712345678", "type": "text", "text": "Hello there"}


@pytest.mark.parametrize(("status", "code", "permanent"), [
    (400, "invalid_whatsapp_message", True), (401, "invalid_platform_key", True), (404, "connection_not_found", True),
    (409, "connection_inactive", True)])
def test_refusals_that_will_not_pass_are_permanent_and_never_echo_the_key(status, code, permanent) -> None:  # type: ignore[no-untyped-def]
    result = call(lambda r: httpx.Response(status, json={"error": code, "detail": "nope"}))
    assert not result.accepted and result.permanent_failure is permanent
    assert "li_platform_SECRET" not in result.message and result.message


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_outages_and_rate_limits_are_raised_so_the_kernel_retries(status) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LeadIntelError) as raised:
        call(lambda r: httpx.Response(status, json={"error": "x"}, headers={"Retry-After": "7"}))
    assert raised.value.retryable
    assert "li_platform_SECRET" not in str(raised.value)


def test_a_502_on_a_free_form_message_means_the_window_is_closed_but_on_a_template_it_is_an_outage() -> None:
    result = call(lambda r: httpx.Response(502, json={"error": "send_failed"}))
    assert not result.accepted and result.permanent_failure and "24-hour window" in result.message
    with pytest.raises(LeadIntelError):
        call(lambda r: httpx.Response(502, json={"error": "send_failed"}), out(mode="template"))


def test_an_unreachable_service_is_a_retryable_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LeadIntelError) as raised:
        call(down)
    assert raised.value.status == 0 and raised.value.retryable


def test_the_client_never_logs_or_returns_a_body_it_does_not_understand() -> None:
    client = LeadIntelClient("li_platform_SECRET", factory=lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>not json</html>"))))
    assert client.call("GET", "/x") == {}


# --------------------------------------------------------------------------- what is not documented
def test_the_undocumented_requests_are_isolated_and_follow_the_documented_pattern() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "templates" in request.url.path and request.method == "GET":
            return httpx.Response(200, json={"templates": [{"status": "REJECTED", "reason": "Too promotional"}]})
        if "templates" in request.url.path:
            return httpx.Response(202, json={"id": "tpl-9", "status": "PENDING"})
        return httpx.Response(404)

    client = LeadIntelClient("k", factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert not hasattr(unverified, "send_sms")                       # Lead Intel is WhatsApp only in Ziira
    spec = TemplateSpec("ziira_payment_due", "en", "utility", "Hi {{1}}", ("customer",), ("Juma",), ("Pay", "Later"))
    assert unverified.submit_template(client, "T", "C", spec).status == "submitted"
    posted = json.loads(seen[0].content)
    assert posted["category"] == "UTILITY" and posted["components"][0] == {
        "type": "BODY", "text": "Hi {{1}}", "example": {"body_text": [["Juma"]]}}
    assert posted["components"][1]["buttons"] == [{"type": "QUICK_REPLY", "text": "Pay"},
                                                  {"type": "QUICK_REPLY", "text": "Later"}]
    state = unverified.template_state(client, "T", "C", spec, "tpl-9")
    assert state.status == "rejected" and state.reason == "Too promotional"


# --------------------------------------------------------------------------- the webhook signature
SECRET = "whsec_test"


def signed(body: bytes, ts_ms: int, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), f"{ts_ms}.".encode() + body, hashlib.sha256).hexdigest()


def test_the_signature_is_the_hex_hmac_of_timestamp_dot_body() -> None:
    body = b'{"messages":[]}'
    assert webhook.signature_of(SECRET, "1788206400000", body) == signed(body, 1788206400000)
    assert len(webhook.signature_of(SECRET, "1", b"")) == 64


def test_a_good_signature_passes_and_every_defect_is_rejected() -> None:
    body = b'{"messages":[{"id":"w1"}]}'
    now = 1_788_206_400_000
    good = signed(body, now)
    webhook.check_signature(SECRET, str(now), good, body, now_ms=now)                       # genuine
    webhook.check_signature(SECRET, str(now - 299_000), signed(body, now - 299_000), body, now_ms=now)   # inside 5 minutes
    for ts, sig, payload in [
        (str(now), good, body + b" "),                                                       # body changed by one byte
        (str(now), good[:-1] + ("0" if good[-1] != "0" else "1"), body),                     # signature changed
        (str(now), signed(body, now, "another-secret"), body),                               # wrong secret
        (str(now + 1), good, body),                                                          # timestamp changed
        (str(now - 301_000), signed(body, now - 301_000), body),                             # too old
        (str(now + 301_000), signed(body, now + 301_000), body),                             # from the future
        ("abc", good, body), ("", good, body), (None, good, body), (str(now), None, body), (str(now), "", body)]:
        with pytest.raises(webhook.Rejected):
            webhook.check_signature(SECRET, ts, sig, payload, now_ms=now)  # type: ignore[arg-type]
    with pytest.raises(webhook.Rejected):                                                    # absurdly large body
        big = b"x" * (webhook.MAX_BODY + 1)
        webhook.check_signature(SECRET, str(now), signed(big, now), big, now_ms=now)


def test_a_signature_in_capitals_is_compared_as_lower_case_hex() -> None:
    body, now = b"{}", 1_788_206_400_000
    webhook.check_signature(SECRET, str(now), signed(body, now).upper(), body, now_ms=now)


def test_the_current_time_is_used_by_default() -> None:
    body = b"{}"
    now = int(datetime.now(UTC).timestamp() * 1000)
    webhook.check_signature(SECRET, str(now), signed(body, now), body)
    with pytest.raises(webhook.Rejected):
        webhook.check_signature(SECRET, str(now - 10 * 60_000), signed(body, now - 10 * 60_000), body)
