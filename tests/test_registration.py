"""Self-service registration: a person creates their own business, and what stops abuse."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from ziira.kernel import registration
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session

REGISTER, VERIFY, SIGN_IN = "/api/v1/register", "/api/v1/register/verify", "/api/v1/auth/sign-in"


@pytest.fixture(autouse=True)
def fresh_limits(registry):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    yield


def body(name="Acme Traders", email=None, **kw):  # type: ignore[no-untyped-def]
    return {"business_name": name, "owner_name": "Jane Doe", "email": email or f"jane-{uuid4().hex[:8]}@acme.test",
            "password": "a-good-password-1", "currency": "usd", "phone_country_code": "44", "country": "gb", **kw}


def verify(client, token, device="dev-1"):  # type: ignore[no-untyped-def]
    return client.post(VERIFY, json={"token": token, "device_id": device})


def test_a_business_registers_verifies_and_is_signed_in(client, registry) -> None:  # type: ignore[no-untyped-def]
    payload = body("Globex Imports")
    asked = client.post(REGISTER, json=payload)
    assert asked.status_code == 202, asked.text
    token = asked.json()["dev_token"]
    assert token.startswith("zg_") and "check your email" in asked.json()["message"].lower()
    # nothing exists yet: no tenant, no database
    with master_session() as s:
        assert s.execute(text("select count(*) from master.tenant where code = 'globex-imports'")).scalar_one() == 0
    done = verify(client, token)
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["workspace"] == "globex-imports" and out["business_name"] == "Globex Imports" and out["access_token"]
    headers = {"Authorization": f"Bearer {out['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["tenant_id"] == out["tenant_id"]
    company = client.get("/api/v1/companies", headers=headers).json()[0]
    assert company["name"] == "Globex Imports" and company["branches"][0]["code"] == "HQ"
    units = client.get("/api/v1/units", headers=headers)
    assert units.status_code in (200, 404)
    # the owner signs in again later with just the email and password
    again = client.post(SIGN_IN, json={"login": payload["email"].upper(), "password": payload["password"],
                                       "device_id": "dev-2"})
    assert again.status_code == 200 and again.json()["tenant_id"] == out["tenant_id"]
    # the business is set up for its own country and has the default modules on
    with master_session() as s:
        db = s.execute(text("select db_name from master.tenant where code = 'globex-imports'")).scalar_one()
    assert db.endswith("globex_imports")
    settings = client.get(f"/api/v1/companies/{company['id']}/settings", headers=headers).json()
    assert settings["phone_country_code"] == "44"
    with master_session():
        pass
    from tests.stock_helpers import system

    with system({"tenant_id": out["tenant_id"]}) as s:
        assert s.execute(text("select country, base_currency from kernel.company")).one() == ("GB", "USD")
    assert client.get("/api/v1/pos/tills", headers=headers).status_code == 200                # pos is enabled
    assert client.get("/api/v1/finance/accounts", headers=headers).status_code == 200         # so is finance
    for path in ("/api/v1/purchasing/suppliers", "/api/v1/crm/customers", "/api/v1/people/employees",
                 "/api/v1/intel/findings", "/api/v1/command/overview"):                      # every business module is
        assert client.get(path, headers=headers).status_code == 200, path
    assert client.get("/api/v1/plugins/messaging/channels", headers=headers).status_code == 404   # a plugin is not


def test_the_link_works_once_and_the_token_is_only_stored_as_a_hash(client, registry) -> None:  # type: ignore[no-untyped-def]
    token = client.post(REGISTER, json=body("Once Only Ltd")).json()["dev_token"]
    with master_session() as s:
        stored = s.execute(text("select token_hash, password_hash from master.registration")).one()
    assert token not in stored.token_hash and stored.password_hash.startswith("scrypt$")
    assert verify(client, token).status_code == 200
    second = verify(client, token)
    assert second.status_code == 409 and "already been used" in second.json()["message"]


def test_bad_links_and_expired_links_are_refused(client, registry) -> None:  # type: ignore[no-untyped-def]
    assert verify(client, "zg_" + "x" * 40).status_code == 401
    assert verify(client, "not-a-token").status_code == 401
    token = client.post(REGISTER, json=body("Late Comers")).json()["dev_token"]
    with master_session() as s:
        s.execute(text("update master.registration set expires_at = now() - interval '1 minute'"))
    expired = verify(client, token)
    assert expired.status_code == 401 and "expired" in expired.json()["message"]
    assert client.post(VERIFY, json={"token": token, "device_id": ""}).status_code in (401, 422)


def test_the_same_business_name_gets_its_own_workspace_code(client, registry) -> None:  # type: ignore[no-untyped-def]
    codes = []
    for _ in range(3):
        done = verify(client, client.post(REGISTER, json=body("Twin Shop")).json()["dev_token"])
        assert done.status_code == 200, done.text
        codes.append(done.json()["workspace"])
    assert codes[0] == "twin-shop" and set(codes) >= {"twin-shop", "twin-shop-2", "twin-shop-3"} - {codes[0]} | {codes[0]}
    assert len(set(codes)) == 3
    odd = verify(client, client.post(REGISTER, json=body("  ÄÖ!!  ")).json()["dev_token"])
    assert odd.status_code == 200 and odd.json()["workspace"] == "business"                   # nothing usable in the name


def test_one_person_can_register_several_businesses(client, registry) -> None:  # type: ignore[no-untyped-def]
    email, password = f"multi-{uuid4().hex[:6]}@acme.test", "a-good-password-1"
    for name in ("First Venture", "Second Venture"):
        assert verify(client, client.post(REGISTER, json=body(name, email=email)).json()["dev_token"]).status_code == 200
    asked = client.post(SIGN_IN, json={"login": email, "password": password, "device_id": "d"})
    assert asked.status_code == 409 and asked.json()["error"] == "choose_business"
    assert [b["workspace"] for b in asked.json()["businesses"]] == ["first-venture", "second-venture"]


def test_a_new_request_replaces_the_earlier_unverified_one(client, registry) -> None:  # type: ignore[no-untyped-def]
    email = f"again-{uuid4().hex[:6]}@acme.test"
    first = client.post(REGISTER, json=body("Retry Co", email=email)).json()["dev_token"]
    second = client.post(REGISTER, json=body("Retry Co", email=email)).json()["dev_token"]
    assert first != second
    assert verify(client, first).status_code == 401                                            # the old link is dead
    assert verify(client, second).status_code == 200


def test_input_is_validated_before_anything_is_saved(client, registry) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"business_name": "x"}, {"owner_name": " "}, {"email": "nope"}, {"email": "a@b"},
                {"password": "short"}, {"currency": "us"}, {"currency": "123"}, {"phone_country_code": "9999"},
                {"phone_country_code": "abc"}, {"country": "GBR"}, {"country": "1"}, {"tax_id": "!!"}, {"business_name": "x" * 121}, {"password": "p" * 201}):
        assert client.post(REGISTER, json=body(**bad)).status_code == 422, bad
    with master_session() as s:
        assert s.execute(text("select count(*) from master.registration")).scalar_one() == 0
    assert client.post(REGISTER, json={}).status_code == 422


def test_requests_are_rate_limited_per_email_and_per_address(client, registry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    email = f"spam-{uuid4().hex[:6]}@acme.test"
    for _ in range(3):
        assert client.post(REGISTER, json=body(email=email)).status_code == 202
    blocked = client.post(REGISTER, json=body(email=email))
    assert blocked.status_code == 429 and blocked.json()["error"] == "too_many_requests"
    assert client.post(REGISTER, json=body()).status_code == 202                               # another email is fine
    from ziira.kernel.errors import TooManyRequests

    monkeypatch.setattr(get_settings(), "registration_per_ip_per_hour", 2)
    for _ in range(2):                                                                         # the same address, 2 emails
        registration.register(business_name="Ip Co", owner_name="Jane Doe", email=f"ip-{uuid4().hex[:6]}@acme.test",
                              password="a-good-password-1", currency="USD", ip_address="203.0.113.9")
    with pytest.raises(TooManyRequests):
        registration.register(business_name="Ip Co", owner_name="Jane Doe", email=f"ip-{uuid4().hex[:6]}@acme.test",
                              password="a-good-password-1", currency="USD", ip_address="203.0.113.9")
    registration.register(business_name="Ip Co", owner_name="Jane Doe", email=f"ip-{uuid4().hex[:6]}@acme.test",
                          password="a-good-password-1", currency="USD", ip_address="203.0.113.10")   # another address


def test_closed_and_invitation_only_modes(client, registry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    monkeypatch.setattr(settings, "registration_mode", "closed")
    closed = client.post(REGISTER, json=body())
    assert closed.status_code == 403 and "closed" in closed.json()["message"]
    monkeypatch.setattr(settings, "registration_mode", "invite")
    assert client.post(REGISTER, json=body()).status_code == 403                               # no code
    assert client.post(REGISTER, json=body(invite_code="INV-WRONG")).status_code == 403
    code = registration.create_invite(uses=1, days=1, note="for a test")
    with master_session() as s:
        assert s.execute(text("select count(*) from master.invite_code where code_hash like '%' || :c || '%'"),
                         {"c": code}).scalar_one() == 0                                         # only a hash is kept
    token = client.post(REGISTER, json=body("Invited Co", invite_code=code.lower())).json()["dev_token"]
    assert verify(client, token).status_code == 200
    again = client.post(REGISTER, json=body("Uninvited Co", invite_code=code))
    assert again.status_code == 403 and "not valid" in again.json()["message"]               # the one use is spent


def test_expired_registrations_are_purged(client, registry) -> None:  # type: ignore[no-untyped-def]
    client.post(REGISTER, json=body("Old Request"))
    with master_session() as s:
        s.execute(text("update master.registration set expires_at = now() - interval '30 days'"))
    assert registration.purge(days=7) == 1
    with master_session() as s:
        assert s.execute(text("select count(*) from master.registration")).scalar_one() == 0


def test_a_failed_provisioning_leaves_the_link_usable(client, registry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    token = client.post(REGISTER, json=body("Fragile Co")).json()["dev_token"]

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    monkeypatch.setattr(registration, "create_tenant", boom)
    broken = verify(client, token)
    assert broken.status_code == 503 and broken.json()["error"] == "unavailable"
    monkeypatch.undo()
    assert verify(client, token).status_code == 200                                            # try again: it works


def test_when_the_email_cannot_be_sent_registration_says_so(client, registry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "platform_email_provider", "no-such-provider")
    r = client.post(REGISTER, json=body())
    assert r.status_code == 503 and r.json()["error"] == "unavailable"


def test_production_refuses_open_registration_without_a_way_to_send_email(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import Settings

    secure = {"env": "production", "dev_tenant_header": False, "secret_key": "s" * 40, "credentials_key": "c" * 40,
              "mfa_default_policy": "privileged"}
    with pytest.raises(RuntimeError, match="PLATFORM_EMAIL_PROVIDER"):
        Settings(**secure, registration_mode="open").check_safe_for_production()
    Settings(**secure, registration_mode="closed").check_safe_for_production()
    Settings(**secure, registration_mode="open", platform_email_provider="smtp").check_safe_for_production()
    with pytest.raises(RuntimeError, match="REGISTRATION_MODE"):
        Settings(**secure, registration_mode="wide-open").check_safe_for_production()


def test_the_time_zone_chosen_at_registration_becomes_the_companys(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import system

    token = client.post(REGISTER, json=body("Zoned Traders", timezone="Pacific/Auckland")).json()["dev_token"]
    out = verify(client, token).json()
    headers = {"Authorization": f"Bearer {out['access_token']}"}
    company = client.get("/api/v1/companies", headers=headers).json()[0]
    assert client.get(f"/api/v1/companies/{company['id']}/settings", headers=headers).json()["timezone"] == "Pacific/Auckland"
    with system({"tenant_id": out["tenant_id"]}) as s:           # stored as a setting, not a column
        assert s.execute(text("select settings->>'timezone' from kernel.company")).scalar_one() == "Pacific/Auckland"
    # one that names no zone starts in UTC; a made-up one is refused before anything is saved
    plain = verify(client, client.post(REGISTER, json=body("Plain Traders")).json()["dev_token"]).json()
    h2 = {"Authorization": f"Bearer {plain['access_token']}"}
    c2 = client.get("/api/v1/companies", headers=h2).json()[0]
    assert client.get(f"/api/v1/companies/{c2['id']}/settings", headers=h2).json()["timezone"] == "UTC"
    bad = client.post(REGISTER, json=body("Nowhere Ltd", timezone="Mars/Olympus"))
    assert bad.status_code == 422 or bad.status_code == 400, bad.text
    with master_session() as s:
        assert s.execute(text("select count(*) from master.registration where business_name = 'Nowhere Ltd'")).scalar_one() == 0
