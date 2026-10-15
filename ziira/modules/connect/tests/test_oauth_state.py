"""The signed OAuth state: tamper-proof, expiring, and nothing secret in it."""

import base64
import json
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.connect.api import oauth_routes as oauth
from ziira.sdk import ValidationFailed

T, C, U = uuid4(), uuid4(), uuid4()


def state(**kw: object) -> str:
    return oauth.make_state(tenant_id=T, connection_id=C, user_id=U, kind="zoho_books", nonce="n0nce", **kw)  # type: ignore[arg-type]


def test_round_trip() -> None:
    parsed = oauth.read_state(state())
    assert (parsed.tenant_id, parsed.connection_id, parsed.user_id, parsed.kind, parsed.nonce) == (
        T, C, U, "zoho_books", "n0nce")


def test_state_without_a_user_round_trips() -> None:
    value = oauth.make_state(tenant_id=T, connection_id=C, user_id=None, kind="quickbooks", nonce="x", now=1000.0)
    assert oauth.read_state(value, now=1001.0).user_id is None


def test_expiry() -> None:
    value = state(now=1_000_000.0)
    assert oauth.read_state(value, now=1_000_000.0 + oauth.STATE_MINUTES * 60 - 1).connection_id == C
    with pytest.raises(ValidationFailed, match="expired"):
        oauth.read_state(value, now=1_000_000.0 + oauth.STATE_MINUTES * 60 + 1)


def test_tampering_is_detected() -> None:
    payload, _, signature = state().partition(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    body["c"] = str(uuid4())                                                   # point at someone else's connection
    forged = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    for bad in (f"{forged}.{signature}", f"{payload}.{'0' * len(signature)}", payload, f".{signature}", "", "a.b.c",
                f"{payload}.{signature}x"):
        with pytest.raises(ValidationFailed):
            oauth.read_state(bad)


@settings(max_examples=100, deadline=None)
@given(junk=st.text(max_size=200))
def test_arbitrary_text_is_never_accepted(junk: str) -> None:
    with pytest.raises(ValidationFailed):
        oauth.read_state(junk)


def test_state_carries_no_secret_and_only_url_safe_characters() -> None:
    value = state()
    assert all(ch.isalnum() or ch in "-_." for ch in value)
    payload = value.partition(".")[0]
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    assert "secret" not in decoded and "token" not in decoded


def test_a_state_for_one_purpose_cannot_be_replayed_as_another_signature() -> None:
    from ziira.sdk import sign_value

    payload = state().partition(".")[0]
    with pytest.raises(ValidationFailed):
        oauth.read_state(f"{payload}.{sign_value(payload)}")                   # signed without the purpose prefix


def test_platform_app_credentials_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_SECRET", raising=False)
    assert oauth.platform_app("zoho_books") is None
    monkeypatch.setenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID", "pid")
    assert oauth.platform_app("zoho_books") is None                            # both are needed
    monkeypatch.setenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_SECRET", "psecret")
    assert oauth.platform_app("zoho_books") == ("pid", "psecret")
    assert oauth.platform_app("quickbooks") is None


def test_redirect_addresses() -> None:
    assert oauth.redirect_uri().endswith("/api/v1/connect/oauth/callback")
    assert "?oauth=failed&reason=denied" in oauth.web_url(None, oauth="failed", reason="denied")
    url = oauth.web_url(C, oauth="success")
    assert str(C) in url and url.endswith("?oauth=success")
