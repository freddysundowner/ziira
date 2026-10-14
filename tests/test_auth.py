"""Sign-in, sessions, refresh tokens, sign-out and the development tenant header."""

import pytest
from sqlalchemy import text

from tests.conftest import OWNER_PASSWORD, make_tenant, sign_in

WS = "auth-co"
OWNER = "owner@auth-co.test"


@pytest.fixture(scope="module")
def tenant(registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Auth Co")
    registry.enable(t["tenant_id"], "products")
    return t


def test_owner_signs_in_with_workspace_code(client, tenant) -> None:  # type: ignore[no-untyped-def]
    me = client.get("/api/v1/auth/me", headers=sign_in(client, WS, OWNER).headers).json()
    assert me["tenant_id"] == str(tenant["tenant_id"])
    [owner] = me["roles"]
    assert owner["role_name"] == "Owner" and owner["scope"] == "tenant"
    # Owner holds kernel permissions and those of every enabled unit
    assert {"users.manage", "approvals.decide", "products.manage", "prices.manage"} <= set(owner["permissions"])
    assert "stock.adjust" not in owner["permissions"]          # inventory is not enabled


def test_wrong_credentials_are_refused_and_audited(client, tenant) -> None:  # type: ignore[no-untyped-def]
    for workspace, login, password in ((WS, OWNER, "wrong-pass"), ("no-such-co", OWNER, OWNER_PASSWORD),
                                       (WS, "nobody@auth-co.test", OWNER_PASSWORD)):
        r = client.post("/api/v1/auth/sign-in", json={"workspace": workspace, "login": login,
                                                      "password": password, "device_id": "d1"})
        assert r.status_code == 401
        assert r.json()["message"] == "Wrong login or password"   # same message every time
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    system_context(tenant["tenant_id"])
    with tenant_session(tenant["tenant_id"]) as s:
        failed = s.execute(text("select count(*) from kernel.audit_log where action = 'login_failed'")).scalar()
    assert failed == 2      # the unknown workspace has no tenant to record it in


def test_requests_without_credentials_are_refused(client, tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings

    monkeypatch.setattr(get_settings(), "dev_tenant_header", False)
    assert client.get("/api/v1/products/products").status_code == 401
    r = client.get("/api/v1/products/products", headers={"X-Tenant-ID": str(tenant["tenant_id"])})
    assert r.status_code == 401
    assert client.get("/api/v1/products/products",
                      headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/v1/products/products", headers=sign_in(client, WS, OWNER).headers).status_code == 200


def test_token_tenant_wins_over_tenant_header(client, tenant, tenants) -> None:  # type: ignore[no-untyped-def]
    headers = {**sign_in(client, WS, OWNER).headers, "X-Tenant-ID": str(tenants["A"]["tenant_id"])}
    assert client.get("/api/v1/auth/me", headers=headers).json()["tenant_id"] == str(tenant["tenant_id"])


def test_refresh_rotates_and_is_bound_to_the_device(client, tenant) -> None:  # type: ignore[no-untyped-def]
    signed = sign_in(client, WS, OWNER, device_id="phone-1")
    wrong_device = client.post("/api/v1/auth/refresh", json={"refresh_token": signed.refresh_token,
                                                             "device_id": "laptop"})
    assert wrong_device.status_code == 401
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": signed.refresh_token, "device_id": "phone-1"})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["session_id"] == signed.session_id and new["refresh_token"] != signed.refresh_token
    # The old refresh token is used up
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": signed.refresh_token, "device_id": "phone-1"})
    assert again.status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 200


def test_idle_session_cannot_refresh(client, tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings

    signed = sign_in(client, WS, OWNER, device_id="idle")
    monkeypatch.setattr(get_settings(), "session_idle_hours", -1)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": signed.refresh_token, "device_id": "idle"})
    assert r.status_code == 401


def test_sign_out_ends_the_session(client, tenant) -> None:  # type: ignore[no-untyped-def]
    signed = sign_in(client, WS, OWNER)
    assert client.post("/api/v1/auth/sign-out", headers=signed.headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=signed.headers).status_code == 401
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": signed.refresh_token, "device_id": "test-device"})
    assert r.status_code == 401


def test_remote_sign_out_of_another_device(client, tenant) -> None:  # type: ignore[no-untyped-def]
    laptop = sign_in(client, WS, OWNER, device_id="laptop")
    phone = sign_in(client, WS, OWNER, device_id="phone")
    sessions = client.get("/api/v1/auth/sessions", headers=laptop.headers).json()
    assert {s["id"] for s in sessions} >= {laptop.session_id, phone.session_id}
    assert client.delete(f"/api/v1/auth/sessions/{phone.session_id}", headers=laptop.headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=phone.headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=laptop.headers).status_code == 200


def test_disabled_user_is_signed_out_and_cannot_sign_in(client, tenant) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER)
    user = client.post("/api/v1/users", headers=owner.headers,
                       json={"full_name": "Temp Clerk", "phone": "0700000001", "password": "clerk-pass-1"}).json()
    clerk = sign_in(client, WS, "0700000001", "clerk-pass-1")          # sign in by phone
    r = client.post(f"/api/v1/users/{user['id']}/status", headers=owner.headers, json={"active": False})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert client.get("/api/v1/auth/me", headers=clerk.headers).status_code == 401
    r = client.post("/api/v1/auth/sign-in", json={"workspace": WS, "login": "0700000001",
                                                  "password": "clerk-pass-1", "device_id": "d"})
    assert r.status_code == 401


def test_invited_user_cannot_sign_in_until_a_password_is_set(client, tenant) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER)
    user = client.post("/api/v1/users", headers=owner.headers,
                       json={"full_name": "New Hire", "email": "Hire@Auth-Co.test"}).json()
    assert user["status"] == "invited" and user["email"] == "hire@auth-co.test"
    r = client.post("/api/v1/auth/sign-in", json={"workspace": WS, "login": "hire@auth-co.test",
                                                  "password": "anything-1", "device_id": "d"})
    assert r.status_code == 401
    assert client.post(f"/api/v1/users/{user['id']}/password", headers=owner.headers,
                       json={"password": "hire-pass-1"}).status_code == 204
    hire = sign_in(client, WS, "hire@auth-co.test", "hire-pass-1")
    # Changing your own password needs the current one, and signs you out everywhere
    bad = client.post("/api/v1/auth/password", headers=hire.headers,
                      json={"current_password": "wrong-pass", "new_password": "hire-pass-2"})
    assert bad.status_code == 401
    assert client.post("/api/v1/auth/password", headers=hire.headers,
                       json={"current_password": "hire-pass-1", "new_password": "hire-pass-2"}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=hire.headers).status_code == 401
    sign_in(client, WS, "hire@auth-co.test", "hire-pass-2")


def test_production_refuses_development_shortcuts() -> None:
    from ziira.kernel.config import Settings

    with pytest.raises(RuntimeError, match="DEV_TENANT_HEADER"):
        Settings(env="production").check_safe_for_production()
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(env="production", dev_tenant_header=False).check_safe_for_production()
    with pytest.raises(RuntimeError, match="CREDENTIALS_KEY"):
        Settings(env="production", dev_tenant_header=False, secret_key="x" * 40).check_safe_for_production()
    with pytest.raises(RuntimeError, match="PLATFORM_EMAIL"):  # open registration needs a way to send the link
        Settings(env="production", dev_tenant_header=False, secret_key="x" * 40, credentials_key="y" * 40,
                 mfa_default_policy="privileged").check_safe_for_production()
    with pytest.raises(RuntimeError, match="MFA_DEFAULT_POLICY"):           # owners and finance must use a second factor
        Settings(env="production", dev_tenant_header=False, secret_key="x" * 40, credentials_key="y" * 40,
                 registration_mode="closed").check_safe_for_production()
    Settings(env="production", dev_tenant_header=False, secret_key="x" * 40, credentials_key="y" * 40,
             registration_mode="closed", mfa_default_policy="privileged").check_safe_for_production()
