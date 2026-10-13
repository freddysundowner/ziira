"""Security: forged and damaged tokens, sessions, API keys, enumeration, hostile credentials and escalation."""

import time
from uuid import uuid4

import pytest

from tests.conftest import OWNER_PASSWORD, make_tenant, sign_in

WS = "sec-co"
OWNER = "owner@sec-co.test"


@pytest.fixture(scope="module")
def sec(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Sec Co")
    registry.enable(t["tenant_id"], "products")
    other = make_tenant("Sec Other")
    owner = sign_in(client, WS, OWNER)
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner.headers).json()}
    users = {}
    for name, role in (("cashier", "Cashier"), ("keeper", "Storekeeper"), ("manager", "Branch Manager"),
                       ("pwchange", "Cashier"), ("pwreset", "Cashier")):
        u = client.post("/api/v1/users", headers=owner.headers, json={
            "full_name": name, "email": f"{name}@sec-co.test", "password": f"{name}-pass-1"}).json()
        client.post(f"/api/v1/users/{u['id']}/roles", headers=owner.headers, json={
            "role_id": roles[role], "scope": "company", "company_id": str(t["company_id"])})
        users[name] = {"id": u["id"], "headers": sign_in(client, WS, f"{name}@sec-co.test", f"{name}-pass-1").headers}
    return {**t, "owner": owner, "roles": roles, "users": users, "other": other}


def me(client, headers):  # type: ignore[no-untyped-def]
    return client.get("/api/v1/auth/me", headers=headers)


# --------------------------------------------------------------------------- forged and damaged access tokens
def token_of(sec) -> str:  # type: ignore[no-untyped-def]
    return sec["owner"].headers["Authorization"].split(" ", 1)[1]


def test_a_good_token_works(client, sec) -> None:  # type: ignore[no-untyped-def]
    assert me(client, sec["owner"].headers).status_code == 200


def test_tampering_with_the_signature_or_the_payload_is_refused(client, sec) -> None:  # type: ignore[no-untyped-def]
    token = token_of(sec)
    body, signature = token.split(".")
    other_body = sec["users"]["cashier"]["headers"]["Authorization"].split(" ", 1)[1].split(".")[0]
    flipped = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    for forged in (f"{body}.{flipped}", f"{other_body}.{signature}", f"{body}.", f".{signature}", body, "a.b.c",
                   "", ".", token + "x", "x" * 20000, f"{body}.{signature}.{signature}"):
        r = me(client, {"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401, (forged[:40], r.status_code)


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "bearer", "Basic abc", "Token abc", "abc", "Bearer a b",
                                    "Bearer \x7f"])
def test_malformed_authorization_headers_are_refused(client, sec, header: str) -> None:  # type: ignore[no-untyped-def]
    try:
        r = me(client, {"Authorization": header})
    except Exception:                                  # the HTTP client itself refuses some header values
        return
    assert r.status_code in (400, 401), (header, r.status_code)


def test_expired_and_foreign_tokens_are_refused(client, sec) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings
    from ziira.kernel.security import read_token, sign_token

    payload = {k: v for k, v in read_token(token_of(sec)).items() if k != "exp"}
    assert me(client, {"Authorization": f"Bearer {sign_token(payload, 5)}"}).status_code == 200     # control
    assert me(client, {"Authorization": f"Bearer {sign_token(payload, -1)}"}).status_code == 401    # expired
    settings = get_settings()
    real = settings.secret_key
    settings.secret_key = "an-attackers-guess-of-the-secret-key-0123456789"
    try:
        forged = sign_token(payload, 5)
    finally:
        settings.secret_key = real
    assert me(client, {"Authorization": f"Bearer {forged}"}).status_code == 401                      # wrong key


@pytest.mark.parametrize("payload", [
    {}, {"t": "x"}, {"t": "not-a-uuid", "u": "x", "s": "y"},
    {"t": str(uuid4()), "u": str(uuid4()), "s": str(uuid4())},                         # a tenant that does not exist
    {"t": 5, "u": None, "s": []}, {"u": "1", "s": "2"}])
def test_signed_but_meaningless_tokens_are_refused_not_crashes(client, sec, payload) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.security import sign_token

    r = me(client, {"Authorization": f"Bearer {sign_token(payload, 5)}"})
    assert r.status_code == 401, (payload, r.status_code, r.text)


def test_a_session_of_one_user_cannot_be_used_with_the_identity_of_another(client, sec) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.security import read_token, sign_token

    owner_payload = read_token(token_of(sec))
    cashier_payload = read_token(sec["users"]["cashier"]["headers"]["Authorization"].split(" ", 1)[1])
    mixed = {"t": owner_payload["t"], "u": owner_payload["u"], "s": cashier_payload["s"]}
    assert me(client, {"Authorization": f"Bearer {sign_token(mixed, 5)}"}).status_code == 401


def test_the_tenant_header_cannot_override_a_token(client, sec) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/auth/me", headers={**sec["owner"].headers, "X-Tenant-ID": str(sec["other"]["tenant_id"])})
    assert r.status_code == 200 and r.json()["user_id"] == str(sec["owner_id"])


# --------------------------------------------------------------------------- sessions and refresh tokens
@pytest.mark.parametrize("garbage", ["", "zr_", "zr_x_y", "zr_" + "0" * 32 + "_x", "zk_" + "0" * 32 + "_x", "x" * 10000,
                                     "zr_" + "g" * 32 + "_x", "zr_" + uuid4().hex + "_" + "y" * 43])
def test_garbage_refresh_tokens_are_refused(client, sec, garbage: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": garbage, "device_id": "d"})
    assert r.status_code in (401, 422), (garbage[:30], r.status_code)


def test_a_used_refresh_token_cannot_be_replayed(client, sec) -> None:  # type: ignore[no-untyped-def]
    first = sign_in(client, WS, OWNER, device_id="replay-device")
    old = {"refresh_token": first.refresh_token, "device_id": "replay-device"}
    second = client.post("/api/v1/auth/refresh", json=old)
    assert second.status_code == 200
    again = client.post("/api/v1/auth/refresh", json=old)
    assert again.status_code == 401
    third = client.post("/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"],
                                                      "device_id": "replay-device"})
    assert third.status_code == 200                                          # the new token carries on


def test_changing_a_password_ends_every_session_of_that_user(client, sec) -> None:  # type: ignore[no-untyped-def]
    user = sec["users"]["pwreset"]
    refresh = sign_in(client, WS, "pwreset@sec-co.test", "pwreset-pass-1", device_id="laptop")
    assert me(client, refresh.headers).status_code == 200
    r = client.post(f"/api/v1/users/{user['id']}/password", headers=sec["owner"].headers,
                    json={"password": "a-brand-new-pass-9"})
    assert r.status_code == 204
    assert me(client, refresh.headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh.refresh_token,
                                                     "device_id": "laptop"}).status_code == 401
    assert client.post("/api/v1/auth/sign-in", json={"workspace": WS, "login": "pwreset@sec-co.test",
                                                     "password": "pwreset-pass-1", "device_id": "x"}).status_code == 401
    assert sign_in(client, WS, "pwreset@sec-co.test", "a-brand-new-pass-9").headers


def test_a_user_changing_their_own_password_needs_the_current_one(client, sec) -> None:  # type: ignore[no-untyped-def]
    s = sign_in(client, WS, "pwchange@sec-co.test", "pwchange-pass-1", device_id="pw")
    wrong = client.post("/api/v1/auth/password", headers=s.headers,
                        json={"current_password": "not-the-password", "new_password": "newer-pass-123"})
    assert wrong.status_code in (401, 403, 422)
    ok = client.post("/api/v1/auth/password", headers=s.headers,
                     json={"current_password": "pwchange-pass-1", "new_password": "newer-pass-123"})
    assert ok.status_code == 204
    assert sign_in(client, WS, "pwchange@sec-co.test", "newer-pass-123").headers


# --------------------------------------------------------------------------- hostile credentials
def sign_in_raw(client, workspace, login, password):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/sign-in", json={"workspace": workspace, "login": login, "password": password,
                                                     "device_id": "d"})


def test_the_reply_does_not_reveal_whether_the_workspace_or_user_exists(client, sec) -> None:  # type: ignore[no-untyped-def]
    replies = {(r.status_code, r.text) for r in (
        sign_in_raw(client, "no-such-workspace", OWNER, OWNER_PASSWORD),
        sign_in_raw(client, WS, "nobody@sec-co.test", OWNER_PASSWORD),
        sign_in_raw(client, WS, OWNER, "wrong-password-1"))}
    assert len(replies) == 1 and next(iter(replies))[0] == 401


@pytest.mark.parametrize("attack", ["' or '1'='1", "'; drop table kernel.app_user; --", "admin'--", "%", "_",
                                    "\x00", "owner@sec-co.test\x00", " " + OWNER, "OWNER@SEC-CO.TEST ", "💥",
                                    "a" * 5000])
def test_injection_style_logins_do_not_get_in(client, sec, attack: str) -> None:  # type: ignore[no-untyped-def]
    r = sign_in_raw(client, WS, attack, "anything-at-all")
    assert r.status_code in (401, 422)
    r = sign_in_raw(client, attack, OWNER, OWNER_PASSWORD)
    assert r.status_code in (401, 422)
    assert sign_in(client, WS, OWNER).headers                                # and the table is still there


def test_the_email_login_is_case_insensitive_but_exact(client, sec) -> None:  # type: ignore[no-untyped-def]
    assert sign_in_raw(client, WS, OWNER.upper(), OWNER_PASSWORD).status_code == 200
    assert sign_in_raw(client, WS.upper(), OWNER, OWNER_PASSWORD).status_code == 200      # workspace codes too
    assert sign_in_raw(client, WS, OWNER + "x", OWNER_PASSWORD).status_code == 401
    assert sign_in_raw(client, WS, "%", OWNER_PASSWORD).status_code == 401                # no wildcards


def test_a_huge_password_is_not_a_way_to_exhaust_the_server(client, sec) -> None:  # type: ignore[no-untyped-def]
    started = time.monotonic()
    r = sign_in_raw(client, WS, OWNER, "x" * 1_000_000)
    assert r.status_code in (401, 422) and time.monotonic() - started < 5
    r = client.post("/api/v1/users", headers=sec["owner"].headers,
                    json={"full_name": "Big", "email": "big@sec-co.test", "password": "y" * 1_000_000})
    assert r.status_code == 422


# --------------------------------------------------------------------------- API keys
def make_key(client, sec, scopes, **extra):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/api-keys", headers=sec["owner"].headers, json={"name": "k", "scopes": scopes, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_api_key_lifecycle_and_garbage(client, sec) -> None:  # type: ignore[no-untyped-def]
    key = make_key(client, sec, ["products.view"])
    headers = {"X-API-Key": key["key"]}
    assert client.get("/api/v1/products/products", headers=headers).status_code == 200
    assert client.post("/api/v1/products/uoms", headers=headers, json={"code": "X", "name": "x"}).status_code == 403
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    for garbage in ("", "zk_", "zk_x_y", "x" * 5000, key["key"][:-1], key["key"] + "x", "zr_" + key["key"][3:]):
        r = client.get("/api/v1/products/products", headers={"X-API-Key": garbage})
        assert r.status_code in (401, 403), (garbage[:30], r.status_code)
    assert client.delete(f"/api/v1/api-keys/{key['id']}", headers=sec["owner"].headers).status_code == 204
    assert client.get("/api/v1/products/products", headers=headers).status_code == 401


def test_expired_api_keys_stop_working(client, sec) -> None:  # type: ignore[no-untyped-def]
    key = make_key(client, sec, ["products.view"], expires_at="2020-01-01T00:00:00Z")
    assert client.get("/api/v1/products/products", headers={"X-API-Key": key["key"]}).status_code == 401


def test_a_key_cannot_be_moved_to_another_tenant(client, sec) -> None:  # type: ignore[no-untyped-def]
    key = make_key(client, sec, ["products.view"])["key"]
    other_hex = sec["other"]["tenant_id"].hex
    moved = "zk_" + other_hex + "_" + key.split("_", 2)[2]
    assert client.get("/api/v1/products/products", headers={"X-API-Key": moved}).status_code == 401


def test_a_key_cannot_carry_more_than_its_creator_has(client, sec) -> None:  # type: ignore[no-untyped-def]
    # A tenant-wide user manager who is not the owner cannot mint a key with powers they lack
    sec_manager = sec["users"]["manager"]["headers"]
    r = client.post("/api/v1/api-keys", headers=sec_manager, json={"name": "k", "scopes": ["products.view"]})
    assert r.status_code == 403                                           # branch managers do not manage keys
    r = client.post("/api/v1/api-keys", headers=sec["owner"].headers, json={"name": "k", "scopes": ["no.such"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- escalation and lock-out
def test_the_owner_role_cannot_be_weakened_or_deleted(client, sec) -> None:  # type: ignore[no-untyped-def]
    r = client.put(f"/api/v1/roles/{sec['roles']['Owner']}/permissions", headers=sec["owner"].headers,
                   json={"permissions": ["products.view"]})
    assert r.status_code in (403, 422)


def test_you_cannot_disable_yourself(client, sec) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"/api/v1/users/{sec['owner_id']}/status", headers=sec["owner"].headers, json={"active": False})
    assert r.status_code == 422


def test_ordinary_roles_cannot_use_admin_endpoints(client, sec) -> None:  # type: ignore[no-untyped-def]
    calls = [("GET", "/api/v1/users", None), ("POST", "/api/v1/users", {"full_name": "x", "email": "x@y.z"}),
             ("GET", "/api/v1/roles", None), ("POST", "/api/v1/roles", {"name": "r", "permissions": []}),
             ("GET", "/api/v1/permissions", None), ("GET", "/api/v1/api-keys", None),
             ("GET", "/api/v1/settings/document-series", None),
             ("POST", "/api/v1/settings/reason-codes",
              {"category": "void", "code": "X", "label": "x"}),
             ("GET", f"/api/v1/companies/{sec['company_id']}/settings", None)]
    for who in ("cashier", "keeper"):
        for method, path, body in calls:
            r = client.request(method, path, headers=sec["users"][who]["headers"], json=body)
            assert r.status_code == 403, (who, method, path, r.status_code)


def test_ids_from_another_tenant_are_never_found_or_accepted(client, sec) -> None:  # type: ignore[no-untyped-def]
    other = sec["other"]
    other_owner = sign_in(client, "sec-other", "owner@sec-other.test").headers
    foreign_role = next(r["id"] for r in client.get("/api/v1/roles", headers=other_owner).json()
                        if r["name"] == "Cashier")
    foreign_user = client.post("/api/v1/users", headers=other_owner, json={
        "full_name": "F", "email": "f@sec-other.test", "password": "foreign-pass-1"}).json()["id"]
    mine = sec["users"]["cashier"]["id"]
    owner = sec["owner"].headers
    # my administrator uses their ids
    assert client.post(f"/api/v1/users/{mine}/roles", headers=owner, json={
        "role_id": foreign_role, "scope": "tenant"}).status_code in (404, 422)
    assert client.post(f"/api/v1/users/{mine}/roles", headers=owner, json={
        "role_id": sec["roles"]["Cashier"], "scope": "company", "company_id": str(other["company_id"])
    }).status_code in (404, 422)
    assert client.get(f"/api/v1/users/{foreign_user}/roles", headers=owner).json() == []
    assert client.post(f"/api/v1/users/{foreign_user}/status", headers=owner, json={"active": False}).status_code == 404
    assert client.post(f"/api/v1/users/{foreign_user}/password", headers=owner,
                       json={"password": "hijack-attempt-1"}).status_code == 404
    assert client.get(f"/api/v1/companies/{other['company_id']}/settings", headers=owner).status_code in (403, 404)
    assert client.patch(f"/api/v1/companies/{other['company_id']}/settings", headers=owner,
                        json={"negative_stock_allowed": True}).status_code in (403, 404)
    # and theirs did not change
    assert sign_in(client, "sec-other", "f@sec-other.test", "foreign-pass-1").headers
