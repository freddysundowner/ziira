"""Platform email and behaviour settings in the Super Admin: providers, write-only secrets, test, activation, the mail log,
env fallback, the registration guard and the public config. Mail transports are mocked: nothing is ever sent."""

import json

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from tests.platform_helpers import API, staff
from tests.test_operator_console import age_confirmation, trail
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.platform import behaviour, mail
from ziira.plugins.messaging.providers import _HttpChannel

SECRET = "sk_live_" + "a1B2c3D4" * 3


@pytest.fixture(autouse=True)
def clean(registry):  # type: ignore[no-untyped-def]
    with master_session() as m:
        m.execute(text("delete from master.platform_email_provider"))
        m.execute(text("delete from master.platform_mail_log"))
        m.execute(text("delete from master.platform_setting where key like 'email.%' or key like 'registration.%' "
                       "or key like 'public.%'"))
    mail.invalidate()
    yield
    mail.invalidate()


@pytest.fixture
def boss(client):  # type: ignore[no-untyped-def]
    return staff(client, "superadmin")


class Server:
    """A fake mail API: records requests and answers with a scripted status and body."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.body = 200, {"id": "m-1"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def server(monkeypatch):  # type: ignore[no-untyped-def]
    fake = Server()
    monkeypatch.setattr(_HttpChannel, "client_factory",
                        staticmethod(lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))))
    return fake


def setup_resend(client, boss, secret: str = SECRET) -> None:  # type: ignore[no-untyped-def]
    h = boss["headers"]
    r = client.put(f"{API}/operator/email/providers/resend", headers=h, json={"secrets": {"api_key": secret}})
    assert r.status_code == 200, r.text
    r = client.put(f"{API}/operator/email/sender", headers=h, json={
        "from_address": "hello@example.test", "from_name": "Ziira", "reply_to": "help@example.test"})
    assert r.status_code == 200, r.text


def test_secret_is_write_only_and_a_test_then_activation_switch_the_mailer(client, boss, server) -> None:  # type: ignore[no-untyped-def]
    h = boss["headers"]
    setup_resend(client, boss)
    page = client.get(f"{API}/operator/email", headers=h).json()
    assert SECRET not in json.dumps(page)
    resend = next(p for p in page["providers"] if p["name"] == "resend")
    assert resend["configured"] and next(f for f in resend["fields"] if f["name"] == "api_key")["is_set"]
    # going live needs a delivered test first
    refused = client.put(f"{API}/operator/email/active", headers=h, json={"provider": "resend"})
    assert refused.status_code == 422
    test = client.post(f"{API}/operator/email/test", headers=h, json={"provider": "resend", "to": "jane@gmail.test"})
    assert test.status_code == 200 and test.json()["ok"] and test.json()["to"] == "j***@gmail.test"
    sent = server.requests[0]
    assert sent.headers["authorization"] == f"Bearer {SECRET}"
    body = json.loads(sent.content)
    assert body["from"] == "Ziira <hello@example.test>" and body["to"] == ["jane@gmail.test"]
    assert body["reply_to"] == "help@example.test"
    assert client.put(f"{API}/operator/email/active", headers=h, json={"provider": "resend"}).status_code == 200
    assert mail.status()["source"] == "platform" and mail.status()["working"]
    # the platform mailer now uses it, and the log keeps only the masked address
    from ziira.kernel import platform_mail

    platform_mail.send("owner@shop.test", "Hello", "Body", "registration")
    assert len(server.requests) == 2
    log = client.get(f"{API}/operator/email/log", headers=h).json()
    assert [(x["kind"], x["recipient_masked"], x["status"]) for x in log[:2]] == [
        ("registration", "o***@shop.test", "sent"), ("test", "j***@gmail.test", "sent")]
    assert "owner@shop.test" not in json.dumps(log) and SECRET not in json.dumps(log)
    lines = trail()
    assert not any(SECRET in json.dumps(x, default=str) for x in lines)
    assert {x["action"] for x in lines} >= {"email.provider_save", "email.test", "email.activate"}


def test_the_top_test_button_tests_the_only_filled_provider_before_anything_is_live(client, boss, server, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The owner's case: Brevo (here Resend) is saved but not live; 'Send a test email' at the top names no provider.
    In production nothing is live yet (here: no environment fallback, no development fake)."""
    h = boss["headers"]
    monkeypatch.setattr(mail, "active", lambda: None)
    nothing = client.post(f"{API}/operator/email/test", headers=h, json={"to": "jane@gmail.test"})
    assert nothing.status_code == 422 and "fill in a provider" in nothing.text
    setup_resend(client, boss)
    r = client.post(f"{API}/operator/email/test", headers=h, json={"to": "jane@gmail.test"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["provider"] == "resend"
    # and the result lets the provider be made live
    assert client.put(f"{API}/operator/email/active", headers=h, json={"provider": "resend"}).status_code == 200


def test_provider_errors_are_mapped_and_an_echoed_secret_is_scrubbed(client, boss, server) -> None:  # type: ignore[no-untyped-def]
    setup_resend(client, boss)
    server.status, server.body = 401, {"message": "bad key"}
    r = client.post(f"{API}/operator/email/test", headers=boss["headers"], json={"provider": "resend"})
    assert not r.json()["ok"] and "refused the API key" in r.json()["message"]
    server.status, server.body = 422, {"message": f"The key {SECRET} cannot send from this domain"}
    r = client.post(f"{API}/operator/email/test", headers=boss["headers"], json={"provider": "resend"})
    assert not r.json()["ok"] and SECRET not in r.text and "***" in r.text
    assert SECRET not in json.dumps(client.get(f"{API}/operator/email/log", headers=boss["headers"]).json())


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=16, max_size=40))
def test_no_secret_ever_comes_back(client, boss, server, secret) -> None:  # type: ignore[no-untyped-def]
    setup_resend(client, boss, secret)
    server.status, server.body = 400, {"message": f"invalid {secret}"}
    outputs = [client.post(f"{API}/operator/email/test", headers=boss["headers"], json={"provider": "resend"}).text,
               client.get(f"{API}/operator/email", headers=boss["headers"]).text,
               client.get(f"{API}/operator/email/log", headers=boss["headers"]).text,
               json.dumps(trail(), default=str)]
    assert all(secret not in out for out in outputs)


def test_only_a_superadmin_may_use_the_email_page_and_changes_are_confirmed(client, boss) -> None:  # type: ignore[no-untyped-def]
    for role in ("billing", "support", "content", "readonly"):
        other = staff(client, role)
        assert client.get(f"{API}/operator/email", headers=other["headers"]).status_code == 403
        assert client.put(f"{API}/operator/email/sender", headers=other["headers"], json={"from_address": "a@b.co"}
                          ).status_code == 403
    age_confirmation(boss, 30)
    stale = client.put(f"{API}/operator/email/sender", headers=boss["headers"], json={"from_address": "a@b.co"})
    assert stale.status_code == 403 and stale.json()["error"] == "mfa_step_up_required"


def test_without_platform_settings_the_environment_or_development_fake_is_used(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert mail.status()["source"] == "development" and mail.status()["working"]
    env = get_settings()
    monkeypatch.setattr(env, "platform_email_provider", "smtp")
    monkeypatch.setattr(env, "platform_email_secret", json.dumps({"host": "smtp.env.test", "port": 465,
                                                                  "username": "u", "password": "pw-env-secret-123"}))
    monkeypatch.setattr(env, "platform_email_config", json.dumps({"from_address": "env@example.test"}))
    page = client.get(f"{API}/operator/email", headers=boss["headers"]).json()
    assert page["source"] == "environment" and page["environment"]["host"] == "smtp.env.test"
    assert "pw-env-secret-123" not in json.dumps(page)
    moved = client.post(f"{API}/operator/email/move-from-environment", headers=boss["headers"])
    assert moved.status_code == 200
    smtp = next(p for p in moved.json()["providers"] if p["name"] == "smtp")
    values = {f["name"]: f["value"] for f in smtp["fields"] if not f["secret"]}
    assert values["host"] == "smtp.env.test" and values["security"] == "ssl"
    assert not next(f for f in smtp["fields"] if f["name"] == "password")["is_set"]       # the secret is asked for
    assert moved.json()["sender"]["from_address"] == "env@example.test"
    assert moved.json()["source"] == "environment"                 # still the environment until the provider is tested and made live


def test_registration_cannot_be_opened_without_working_email(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    h = boss["headers"]
    monkeypatch.setattr(get_settings(), "env", "production")
    monkeypatch.setattr(get_settings(), "platform_email_provider", "")
    assert not mail.status()["working"]
    refused = client.put(f"{API}/operator/platform/behaviour/registration.mode", headers=h, json={"value": "open"})
    assert refused.status_code == 422 and "working email" in refused.json()["message"]
    assert client.put(f"{API}/operator/platform/behaviour/registration.mode", headers=h,
                      json={"value": "closed"}).status_code == 200
    # an environment that says open still reads as closed to the public while nothing can send mail
    monkeypatch.setattr(get_settings(), "registration_mode", "open")
    behaviour.set_value("registration.mode", "", "test")
    assert client.get(f"{API}/public/config").json()["registration"] == "closed"


def test_public_config_has_only_non_secret_values(client, boss) -> None:  # type: ignore[no-untyped-def]
    h = boss["headers"]
    for key, value in (("public.terms_url", "https://example.test/terms"), ("public.support_email", "s@example.test"),
                       ("public.web_url", "https://app.example.test/")):
        assert client.put(f"{API}/operator/platform/behaviour/{key}", headers=h, json={"value": value}).status_code == 200
    setup_resend(client, boss)
    body = client.get(f"{API}/public/config").json()
    assert set(body) == {"registration", "terms_url", "privacy_url", "help_url", "site_url", "support_email"}
    assert body["terms_url"] == "https://example.test/terms"
    assert behaviour.public_web_url() == "https://app.example.test"
    bad = client.put(f"{API}/operator/platform/behaviour/public.terms_url", headers=h, json={"value": "javascript:alert(1)"})
    assert bad.status_code == 422


def test_masking_and_log_purge(registry) -> None:  # type: ignore[no-untyped-def]
    assert mail.mask("john@gmail.com") == "j***@gmail.com" and mail.mask("nonsense") == "***"
    mail._log("billing", "a@b.test", True, "x", None)
    with master_session() as m:
        m.execute(text("update master.platform_mail_log set sent_at = now() - interval '200 days'"))
    assert mail.purge_log() == 1 and mail.log_lines() == []
