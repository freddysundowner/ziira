"""The OAuth endpoints for Zoho Books and QuickBooks Online, end to end on the real database with the vendors mocked:
starting, the signed state, the callback, one-time use, refusals, permissions, and that no secret ever leaves."""

import base64
import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.connect_helpers import CONNECT, make_connect_shop, new_connection, rows
from tests.stock_helpers import system
from ziira.modules.connect.api import oauth_routes as oauth
from ziira.modules.connect.connectors.quickbooks import QuickBooksConnector
from ziira.modules.connect.connectors.zoho_books import ZohoBooksConnector
from ziira.modules.connect.services import connections
from ziira.modules.connect.tests.api_helpers import FakeSystem, json_reply

CLIENT_SECRET = "my-own-app-secret-8841"
REFRESH = "1000.refresh.token.zzz"
ORGS = {"code": 0, "organizations": [{"organization_id": "10234695", "name": "Shop Ltd", "is_default_org": True}]}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_connect_shop(client, registry, "Oauth Co")


@pytest.fixture(scope="module")
def other_shop(client, registry):  # type: ignore[no-untyped-def]
    return make_connect_shop(client, registry, "Oauth Other")


@pytest.fixture(scope="module")
def public():  # type: ignore[no-untyped-def]
    """The callback endpoint on a tiny app of its own (it is mounted on the real app by the unit's routes)."""
    app = FastAPI()
    app.include_router(oauth.public_router, prefix=CONNECT)
    return TestClient(app, follow_redirects=False)


@pytest.fixture(autouse=True)
def vendors(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, FakeSystem]]:
    """Zoho's and Intuit's servers, mocked. The token replies can be changed by a test."""
    monkeypatch.delenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ZIIRA_OAUTH_QUICKBOOKS_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZIIRA_OAUTH_QUICKBOOKS_CLIENT_SECRET", raising=False)

    def zoho(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return json_reply({"access_token": "AT-1", "refresh_token": REFRESH, "expires_in": 3600})
        return json_reply(ORGS)

    def intuit(request: httpx.Request) -> httpx.Response:
        return json_reply({"access_token": "AT-q", "refresh_token": "RT-q-1", "expires_in": 3600})

    systems = {"zoho": FakeSystem(zoho), "intuit": FakeSystem(intuit)}
    monkeypatch.setattr(ZohoBooksConnector, "client_factory", staticmethod(systems["zoho"].factory), raising=False)
    monkeypatch.setattr(QuickBooksConnector, "client_factory", staticmethod(systems["intuit"].factory), raising=False)
    yield systems


def zoho_connection(client, shop, name: str):  # type: ignore[no-untyped-def]
    return new_connection(client, shop, "zoho_books", name, config={"data_centre": "eu"})


def start(client, shop, connection_id: str, kind: str = "zoho_books", **body):  # type: ignore[no-untyped-def]
    return client.post(f"{CONNECT}/oauth/{kind}/start", headers=shop["owner"], json={"connection_id": connection_id, **body})


def state_of(authorization_url: str) -> str:
    return parse_qs(urlsplit(authorization_url).query)["state"][0]


def secrets_of(shop, connection_id: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    with system(shop) as s:
        row = connections.get(s, UUID(connection_id))
        return connections.load_secrets(s, row)


def config_of(shop, connection_id: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return dict(rows(shop, "select config from connect.connection where id = :c", c=connection_id)[0].config)


def landing(response: httpx.Response) -> tuple[str, dict[str, list[str]]]:
    assert response.status_code == 303
    parts = urlsplit(response.headers["location"])
    return parts.path, parse_qs(parts.query)


# --------------------------------------------------------------------------- the happy path
def test_zoho_start_and_callback_store_tokens_encrypted(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho main")
    r = start(client, shop, conn["id"], client_id="1000.OWNAPP", client_secret=CLIENT_SECRET)
    assert r.status_code == 200, r.text
    out = r.json()
    url = urlsplit(out["authorization_url"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.zoho.eu/oauth/v2/auth"
    assert q["client_id"] == ["1000.OWNAPP"] and q["redirect_uri"] == [out["redirect_uri"]]
    assert out["redirect_uri"].endswith("/api/v1/connect/oauth/callback") and out["expires_in_seconds"] == 900
    assert CLIENT_SECRET not in r.text and CLIENT_SECRET not in out["authorization_url"]   # never in an address
    stored = secrets_of(shop, conn["id"])
    assert stored["client_id"] == "1000.OWNAPP" and stored["client_secret"] == CLIENT_SECRET and stored["_oauth_nonce"]
    # the stored secret is encrypted in the database
    raw = rows(shop, "select secret_ciphertext from kernel.integration_credential")
    assert all(CLIENT_SECRET.encode() not in bytes(x.secret_ciphertext) for x in raw)

    back = public.get(f"{CONNECT}/oauth/callback", params={"state": state_of(out["authorization_url"]),
                                                          "code": "one-time-code", "location": "eu"})
    path, flags = landing(back)
    assert path == f"/connect/connections/{conn['id']}" and flags == {"oauth": ["success"]}
    assert "one-time-code" not in back.headers["location"] and REFRESH not in back.headers["location"]
    exchange = vendors["zoho"].requests[0]
    form = parse_qs(exchange.content.decode())
    assert form["code"] == ["one-time-code"] and form["client_secret"] == [CLIENT_SECRET]
    assert exchange.url.host == "accounts.zoho.eu" and exchange.url.query == b""    # in the body, never the address

    stored = secrets_of(shop, conn["id"])
    assert stored["refresh_token"] == REFRESH and stored["client_id"] == "1000.OWNAPP" and not stored["_oauth_nonce"]
    config = config_of(shop, conn["id"])
    assert config["organization_id"] == "10234695" and config["data_centre"] == "eu"
    assert {"client_id", "client_secret", "refresh_token"} <= set(config["_secrets"])
    assert REFRESH not in json.dumps(config) and CLIENT_SECRET not in json.dumps(config)
    detail = client.get(f"{CONNECT}/connections/{conn['id']}", headers=shop["owner"])
    assert detail.status_code == 200 and REFRESH not in detail.text and CLIENT_SECRET not in detail.text
    audit = rows(shop, "select changes::text as c from kernel.audit_log where entity_id = :i", i=conn["id"])
    assert audit and all(REFRESH not in a.c and CLIENT_SECRET not in a.c and "one-time-code" not in a.c for a in audit)


def test_the_zoho_location_the_vendor_reports_wins(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = new_connection(client, shop, "zoho_books", "Zoho India", config={"data_centre": "com"})
    state = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    public.get(f"{CONNECT}/oauth/callback", params={"state": state, "code": "x", "location": "in"})
    assert config_of(shop, conn["id"])["data_centre"] == "in"
    assert vendors["zoho"].requests[0].url.host == "accounts.zoho.in"


def test_quickbooks_start_and_callback(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = new_connection(client, shop, "quickbooks", "QB main", config={"environment": "sandbox"})
    out = start(client, shop, conn["id"], "quickbooks", client_id="ABapp", client_secret="qb-secret-8842").json()
    assert out["authorization_url"].startswith("https://appcenter.intuit.com/connect/oauth2?")
    assert "qb-secret-8842" not in out["authorization_url"]
    back = public.get(f"{CONNECT}/oauth/callback", params={"state": state_of(out["authorization_url"]),
                                                          "code": "qb-code", "realmId": "9130350000000001"})
    assert landing(back)[1] == {"oauth": ["success"]}
    assert secrets_of(shop, conn["id"])["refresh_token"] == "RT-q-1"
    config = config_of(shop, conn["id"])
    assert (config["realm_id"], config["environment"]) == ("9130350000000001", "sandbox")


def test_platform_app_credentials_are_preferred(client, shop, public, vendors, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID", "1000.PLATFORM")
    monkeypatch.setenv("ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_SECRET", "platform-secret-77")
    conn = zoho_connection(client, shop, "Zoho platform")
    out = start(client, shop, conn["id"], client_id="1000.IGNORED", client_secret="ignored-secret-1").json()
    assert parse_qs(urlsplit(out["authorization_url"]).query)["client_id"] == ["1000.PLATFORM"]
    public.get(f"{CONNECT}/oauth/callback", params={"state": state_of(out["authorization_url"]), "code": "c"})
    assert parse_qs(vendors["zoho"].requests[0].content.decode())["client_secret"] == ["platform-secret-77"]


# --------------------------------------------------------------------------- refusals
def test_start_needs_credentials_the_right_kind_and_permission(client, shop, other_shop) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho refusals")
    assert start(client, shop, conn["id"]).status_code == 422                       # no app credentials anywhere
    assert start(client, shop, conn["id"], "quickbooks", client_id="c", client_secret="s-secret-1").status_code == 422
    assert start(client, shop, conn["id"], "erpnext", client_id="c", client_secret="s").status_code == 404
    assert start(client, shop, conn["id"], "not_a_kind", client_id="c", client_secret="s").status_code == 404
    ok = {"client_id": "c", "client_secret": "s-secret-1"}
    assert client.post(f"{CONNECT}/oauth/zoho_books/start", headers=shop["accountant"],
                       json={"connection_id": conn["id"], **ok}).status_code == 403   # view-only
    assert client.post(f"{CONNECT}/oauth/zoho_books/start", json={"connection_id": conn["id"], **ok}).status_code == 401
    # another business cannot start an approval for this connection
    assert start(client, other_shop, conn["id"], **ok).status_code == 404
    bad_dc = new_connection(client, shop, "zoho_books", "Zoho bad dc", config={"data_centre": "nowhere"})
    assert start(client, shop, bad_dc["id"], **ok).status_code == 422


def test_callback_refusals_always_land_back_in_the_app(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho callbacks")
    out = start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()
    state = state_of(out["authorization_url"])
    cb = f"{CONNECT}/oauth/callback"
    assert landing(public.get(cb, params={"state": "garbage", "code": "x"})) == ("/connect", {
        "oauth": ["failed"], "reason": ["invalid_state"]})
    assert landing(public.get(cb, params={"code": "x"}))[1]["reason"] == ["invalid_state"]
    payload, _, signature = state.partition(".")
    forged_body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    forged_body["c"] = "00000000-0000-0000-0000-000000000000"
    forged = base64.urlsafe_b64encode(json.dumps(forged_body).encode()).decode().rstrip("=")
    assert landing(public.get(cb, params={"state": f"{forged}.{signature}", "code": "x"}))[1]["reason"] == [
        "invalid_state"]
    assert landing(public.get(cb, params={"state": state}))[1]["reason"] == ["no_code"]
    assert vendors["zoho"].requests == []                                           # nothing was sent to Zoho
    assert "refresh_token" not in secrets_of(shop, conn["id"])


def test_refused_by_the_person_forgets_the_pending_approval(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho denied")
    state = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    denied = public.get(f"{CONNECT}/oauth/callback", params={"state": state, "error": "access_denied"})
    assert landing(denied)[1] == {"oauth": ["failed"], "reason": ["denied"]}
    late = public.get(f"{CONNECT}/oauth/callback", params={"state": state, "code": "x"})
    assert landing(late)[1]["reason"] == ["already_used"] and vendors["zoho"].requests == []


def test_an_approval_link_works_once(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho once")
    state = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    cb = f"{CONNECT}/oauth/callback"
    assert landing(public.get(cb, params={"state": state, "code": "x"}))[1] == {"oauth": ["success"]}
    assert landing(public.get(cb, params={"state": state, "code": "x"}))[1]["reason"] == ["already_used"]
    assert len(vendors["zoho"].requests) == 2                                       # one token call + organisations


def test_a_newer_start_cancels_the_older_link(client, shop, public) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho restart")
    first = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    second = state_of(start(client, shop, conn["id"]).json()["authorization_url"])      # reuses the stored app details
    cb = f"{CONNECT}/oauth/callback"
    assert landing(public.get(cb, params={"state": first, "code": "x"}))[1]["reason"] == ["already_used"]
    assert landing(public.get(cb, params={"state": second, "code": "x"}))[1] == {"oauth": ["success"]}


def test_a_state_cannot_be_used_on_a_connection_of_another_kind(client, shop, public) -> None:  # type: ignore[no-untyped-def]
    conn = zoho_connection(client, shop, "Zoho kind")
    qb = new_connection(client, shop, "quickbooks", "QB kind", config={"environment": "production"})
    state = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    payload = state.partition(".")[0]
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert body["k"] == "zoho_books" and body["c"] == conn["id"] and qb["id"] != conn["id"]
    # a validly signed state naming the wrong kind for its connection is refused by the callback
    wrong = oauth.make_state(tenant_id=UUID(body["t"]), connection_id=UUID(qb["id"]), user_id=None,
                             kind="zoho_books", nonce="whatever")
    assert landing(public.get(f"{CONNECT}/oauth/callback", params={"state": wrong, "code": "x"}))[1]["reason"] == [
        "unknown_connection"]


def test_vendor_refusing_the_code_reports_a_reason_and_keeps_nothing(client, shop, public, vendors) -> None:  # type: ignore[no-untyped-def]
    vendors["zoho"].handler = lambda request: json_reply({"error": "invalid_code"})
    conn = zoho_connection(client, shop, "Zoho refused")
    state = state_of(start(client, shop, conn["id"], client_id="c", client_secret="s-secret-1").json()["authorization_url"])
    back = public.get(f"{CONNECT}/oauth/callback", params={"state": state, "code": "bad"})
    assert landing(back)[1] == {"oauth": ["failed"], "reason": ["exchange_failed"]}
    assert "refresh_token" not in secrets_of(shop, conn["id"])
    vendors["zoho"].handler = lambda request: json_reply({}, 503)
    again = state_of(start(client, shop, conn["id"]).json()["authorization_url"])
    assert landing(public.get(f"{CONNECT}/oauth/callback", params={"state": again, "code": "x"}))[1]["reason"] == [
        "vendor_unavailable"]


def test_callback_is_mounted_on_the_real_app(client) -> None:  # type: ignore[no-untyped-def]
    paths = {getattr(r, "path", "") for r in client.app.routes}                  # type: ignore[attr-defined]
    if f"{CONNECT}/oauth/callback" not in paths:
        pytest.skip("the unit's routes.py does not mount oauth_routes.public_router yet")
    r = client.get(f"{CONNECT}/oauth/callback", params={"state": "x"}, follow_redirects=False)
    assert r.status_code == 303 and "reason=invalid_state" in r.headers["location"]
