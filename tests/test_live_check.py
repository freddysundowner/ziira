"""The live-check harness builds the right requests in a dry run (no network) and hides secrets."""

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("live_check", Path(__file__).parent.parent / "scripts" / "live_check.py")
assert spec and spec.loader
lc = importlib.util.module_from_spec(spec)
sys.modules["live_check"] = lc
spec.loader.exec_module(lc)

DARAJA = {"ZIIRA_LIVE_DARAJA_CONSUMER_KEY": "ck-secret-1", "ZIIRA_LIVE_DARAJA_CONSUMER_SECRET": "cs-secret-2",
          "ZIIRA_LIVE_DARAJA_SHORTCODE": "174379", "ZIIRA_LIVE_DARAJA_PASSKEY": "pk-secret-3",
          "ZIIRA_LIVE_DARAJA_CALLBACK_URL": "https://example.test/cb"}


def body(ex):  # type: ignore[no-untyped-def]
    return json.loads(ex.request_body)


def test_daraja_dry_run_builds_token_push_and_query_requests() -> None:
    report = lc.daraja_check(phone="0708374149", amount="1", polls=3, dry_run=True, echo=False, env=DARAJA)
    assert report.passed
    token, push, query = report.exchanges
    assert token.method == "GET" and token.url.startswith("https://sandbox.safaricom.co.ke/oauth/v1/generate")
    assert token.headers["authorization"] == lc.HIDDEN
    assert push.url == "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    sent = body(push)
    assert sent["BusinessShortCode"] == "174379" and sent["Amount"] == 1 and sent["PartyA"] == "254708374149"
    assert sent["CallBackURL"] == "https://example.test/cb" and sent["TransactionType"] == "CustomerPayBillOnline"
    assert sent["Password"] == lc.HIDDEN
    assert query.url.endswith("/mpesa/stkpushquery/v1/query") and body(query)["CheckoutRequestID"] == "ws_CO_DRYRUN"
    assert report.exchanges[-1].status == 200


def test_secrets_never_appear_in_what_is_printed() -> None:
    report = lc.daraja_check(phone="254708374149", amount="1", polls=1, dry_run=True, echo=False, env=DARAJA)
    everything = json.dumps([vars(e) for e in report.exchanges])
    for secret in ("ck-secret-1", "cs-secret-2", "pk-secret-3", "dry-run-token"):
        assert secret not in everything


def test_sms_dry_run_posts_the_blessedtexts_payload() -> None:
    env = {"ZIIRA_LIVE_SMS_API_KEY": "sms-key-123", "ZIIRA_LIVE_SMS_SENDER_ID": "SENDER"}
    report = lc.sms_check(to="254700000000", text="hello", dry_run=True, echo=False, env=env)
    [ex] = report.exchanges
    assert report.passed and ex.url == "https://sms.blessedtexts.com/api/sms/v1/sendsms"
    assert body(ex) == {"api_key": lc.HIDDEN, "sender_id": "SENDER", "message": "hello", "phone": "254700000000"}


@pytest.mark.parametrize(("provider", "url", "auth_header"), [
    ("brevo", "https://api.brevo.com/v3/smtp/email", "api-key"),
    ("resend", "https://api.resend.com/emails", "authorization"),
    ("sendgrid", "https://api.sendgrid.com/v3/mail/send", "authorization")])
def test_api_email_dry_run_requests(provider: str, url: str, auth_header: str) -> None:
    env = {"ZIIRA_LIVE_EMAIL_FROM_ADDRESS": "from@example.test", "ZIIRA_LIVE_EMAIL_API_KEY": "email-key-9"}
    report = lc.email_check(provider=provider, to="to@example.test", dry_run=True, echo=False, env=env)
    [ex] = report.exchanges
    assert report.passed and ex.url == url and ex.headers[auth_header] == lc.HIDDEN
    assert "to@example.test" in ex.request_body and "email-key-9" not in ex.request_body


def test_smtp_dry_run_records_the_message_and_hides_the_password() -> None:
    env = {"ZIIRA_LIVE_EMAIL_FROM_ADDRESS": "from@example.test", "ZIIRA_LIVE_SMTP_HOST": "smtp.example.test",
           "ZIIRA_LIVE_SMTP_USERNAME": "user", "ZIIRA_LIVE_SMTP_PASSWORD": "pw-secret"}
    report = lc.email_check(provider="smtp", to="to@example.test", dry_run=True, echo=False, env=env)
    [ex] = report.exchanges
    assert report.passed and ex.url == "smtp.example.test:587" and ex.headers["starttls"] == "yes"
    assert "pw-secret" not in json.dumps(vars(ex)) and "To: to@example.test" in ex.request_body


def test_the_callback_address_is_signed_like_the_app_signs_it() -> None:
    from ziira.modules.payments.services.intents import callback_url
    from ziira.sdk import settings_public_base_url
    tenant, intent = uuid.uuid4(), uuid.uuid4()
    assert lc.signed_callback_url(settings_public_base_url(), tenant, intent) == callback_url(tenant, intent)


def test_callback_dry_run_posts_a_success_body_and_hides_the_signature(capsys: pytest.CaptureFixture[str]) -> None:
    tenant, intent = uuid.uuid4(), uuid.uuid4()
    report = lc.callback_check(api_url="http://api.test", tenant_id=str(tenant), intent_id=str(intent),
                               checkout_id="ws_CO_1", amount="5", phone="0708374149", dry_run=True, echo=False)
    [ex] = report.exchanges
    stk = body(ex)["Body"]["stkCallback"]
    assert report.passed and f"/callbacks/stk/{tenant.hex}/{intent}/" in ex.url
    assert stk["CheckoutRequestID"] == "ws_CO_1" and stk["ResultCode"] == 0
    items = {i["Name"]: i["Value"] for i in stk["CallbackMetadata"]["Item"]}
    assert items["Amount"] == 5.0 and items["PhoneNumber"] == 254708374149
    assert lc.HIDDEN in capsys.readouterr().out


def test_refuses_to_run_in_production_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZIIRA_ENV", "production")
    assert lc.main(["sms", "--to", "1", "--dry-run"]) == 2
