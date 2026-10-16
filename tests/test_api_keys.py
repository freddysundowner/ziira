"""API keys: scopes (read-only, company), the public API only, rate limits, expiry, rotation, usage, permissions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from ziira.kernel.config import get_settings
from ziira.kernel.context import system_context
from ziira.kernel.db import tenant_session

KEYS = "/api/v1/api-keys"
CUSTOMERS = "/api/v1/crm/customers"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Key Shop")
    registry.enable(t["tenant_id"], "crm")
    registry.enable(t["tenant_id"], "products")
    make_tenant("Key Other")
    owner = sign_in(client, "key-shop", "owner@key-shop.test").headers
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}
    person = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Branch", "email": "branch@key-shop.test", "password": "branch-pass-1"}).json()
    client.post(f"/api/v1/users/{person['id']}/roles", headers=owner, json={
        "role_id": roles["Branch Manager"], "scope": "company", "company_id": str(t["company_id"])})
    second = client.post("/api/v1/companies", headers=owner, json={"name": "Key Shop Two", "currency": "USD"}).json()
    alpha = client.post(CUSTOMERS, headers=owner, json={"company_id": str(t["company_id"]), "name": "Alpha"}).json()
    beta = client.post(CUSTOMERS, headers=owner, json={"company_id": second["id"], "name": "Beta"}).json()
    return {**t, "owner": owner, "manager": sign_in(client, "key-shop", "branch@key-shop.test", "branch-pass-1").headers,
            "second": second["id"], "alpha": alpha["id"], "beta": beta["id"],
            "other_owner": sign_in(client, "key-other", "owner@key-other.test").headers}


def new_key(client, shop, scopes=("customers.view",), **extra):  # type: ignore[no-untyped-def]
    r = client.post(KEYS, headers=shop["owner"], json={"name": "Integration", "scopes": list(scopes), **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"], {"X-API-Key": r.json()["key"]}


def row(client, shop, key_id):  # type: ignore[no-untyped-def]
    return next(k for k in client.get(KEYS, headers=shop["owner"]).json() if k["id"] == key_id)


def sql(shop, statement: str, **params) -> None:  # type: ignore[no-untyped-def]
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        s.execute(text(statement), params)


# --------------------------------------------------------------------------- what a key may call
def test_a_key_reaches_public_endpoints_with_its_permissions_only(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, key = new_key(client, shop, ["customers.view", "users.manage"])
    assert client.get(CUSTOMERS, headers=key).status_code == 200
    me = client.get("/api/v1/auth/me", headers=key).json()
    assert me["channel"] == "api" and me["user_id"] is None
    assert client.get("/api/v1/products/products", headers=key).status_code == 403          # permission it was not given
    refused = client.get("/api/v1/users", headers=key)                                       # it HAS users.manage ...
    assert refused.status_code == 403 and "public API" in refused.json()["message"]          # ... but this is not public
    assert client.post("/api/v1/api-keys", headers=key, json={"name": "x", "scopes": ["users.manage"]}).status_code == 403


def test_a_read_only_key_can_only_read(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, reader = new_key(client, shop, ["customers.view", "customers.manage"], read_only=True)
    _, writer = new_key(client, shop, ["customers.view", "customers.manage"])
    body = {"company_id": str(shop["company_id"]), "name": "Via key"}
    assert client.get(CUSTOMERS, headers=reader).status_code == 200
    blocked = client.post(CUSTOMERS, headers=reader, json=body)
    assert blocked.status_code == 403 and "read-only" in blocked.json()["message"]
    assert client.post(CUSTOMERS, headers=writer, json=body).status_code == 201


def test_a_key_limited_to_one_company_sees_only_that_company(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, everywhere = new_key(client, shop)
    _, second_only = new_key(client, shop, company_id=shop["second"])
    names = lambda headers: {c["name"] for c in client.get(CUSTOMERS, headers=headers).json()}  # noqa: E731
    assert {"Alpha", "Beta"} <= names(everywhere)
    assert "Beta" in names(second_only) and "Alpha" not in names(second_only)
    assert client.get(f"{CUSTOMERS}/{shop['beta']}", headers=second_only).status_code == 200
    assert client.get(f"{CUSTOMERS}/{shop['alpha']}", headers=second_only).status_code in (403, 404)


def test_a_key_is_built_from_checked_inputs(client, shop) -> None:  # type: ignore[no-untyped-def]
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    for bad in ({"scopes": []}, {"scopes": ["no.such"]}, {"name": " "}, {"expires_at": past}, {"rate_limit_per_minute": 0},
                {"rate_limit_per_minute": 1_000_000}, {"company_id": str(uuid4())}, {"branch_id": str(shop["branch_id"])},
                {"company_id": str(shop["company_id"]), "branch_id": str(uuid4())}, {"unknown": 1}):
        r = client.post(KEYS, headers=shop["owner"], json={"name": "k", "scopes": ["customers.view"], **bad})
        assert r.status_code == 422, (bad, r.status_code)


def test_nobody_can_mint_a_key_with_powers_they_lack(client, shop) -> None:  # type: ignore[no-untyped-def]
    # the manager has no api_keys.manage at all; and even a company-wide holder could not exceed their own scope
    assert client.post(KEYS, headers=shop["manager"], json={"name": "k", "scopes": ["customers.view"]}).status_code == 403
    assert client.get(KEYS, headers=shop["manager"]).status_code == 403
    assert client.get(KEYS).status_code == 401


# --------------------------------------------------------------------------- limits, expiry, rotation, usage
def test_the_rate_limit_answers_429_with_retry_after_then_recovers(client, shop) -> None:  # type: ignore[no-untyped-def]
    key_id, key = new_key(client, shop, rate_limit_per_minute=3)
    assert [client.get(CUSTOMERS, headers=key).status_code for _ in range(3)] == [200, 200, 200]
    r = client.get(CUSTOMERS, headers=key)
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 60 and r.json()["error"] == "too_many_requests"
    _, other = new_key(client, shop, rate_limit_per_minute=3)
    assert client.get(CUSTOMERS, headers=other).status_code == 200                      # limits are per key
    sql(shop, "update kernel.api_key set window_started = now() - interval '2 minutes' where id = :i", i=key_id)
    assert client.get(CUSTOMERS, headers=key).status_code == 200                         # a new minute


def test_keys_without_their_own_limit_use_the_platform_default(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "api_key_rate_limit_per_minute", 2)
    _, key = new_key(client, shop)
    assert [client.get(CUSTOMERS, headers=key).status_code for _ in range(3)] == [200, 200, 429]


def test_an_expired_or_revoked_key_stops_working(client, shop) -> None:  # type: ignore[no-untyped-def]
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    key_id, key = new_key(client, shop, expires_at=soon)
    assert client.get(CUSTOMERS, headers=key).status_code == 200
    sql(shop, "update kernel.api_key set expires_at = now() - interval '1 second' where id = :i", i=key_id)
    assert client.get(CUSTOMERS, headers=key).status_code == 401
    revoked_id, revoked = new_key(client, shop)
    assert client.delete(f"{KEYS}/{revoked_id}", headers=shop["owner"]).status_code == 204
    assert client.get(CUSTOMERS, headers=revoked).status_code == 401
    assert client.delete(f"{KEYS}/{revoked_id}", headers=shop["owner"]).status_code == 404


def test_rotation_keeps_the_old_key_for_the_overlap_then_it_ends(client, shop) -> None:  # type: ignore[no-untyped-def]
    old_id, old = new_key(client, shop, ["customers.view"], read_only=True, rate_limit_per_minute=50,
                          company_id=shop["second"])
    made = client.post(f"{KEYS}/{old_id}/rotate", headers=shop["owner"], json={"grace_hours": 2})
    assert made.status_code == 201, made.text
    new = {"X-API-Key": made.json()["key"]}
    assert made.json()["key"] != old["X-API-Key"]
    assert client.get(CUSTOMERS, headers=old).status_code == 200 and client.get(CUSTOMERS, headers=new).status_code == 200
    fresh, aged = row(client, shop, made.json()["id"]), row(client, shop, old_id)
    assert (fresh["read_only"], fresh["rate_limit_per_minute"], fresh["company_id"], fresh["scopes"]) == \
           (True, 50, shop["second"], ["customers.view"]) and fresh["rotated_from"] == old_id
    ends = datetime.fromisoformat(aged["expires_at"])
    assert timedelta(hours=1, minutes=55) < ends - datetime.now(UTC) < timedelta(hours=2, minutes=5)
    cut = client.post(f"{KEYS}/{made.json()['id']}/rotate", headers=shop["owner"], json={"grace_hours": 0}).json()
    assert client.get(CUSTOMERS, headers=new).status_code == 401                          # no overlap: gone at once
    assert client.get(CUSTOMERS, headers={"X-API-Key": cut["key"]}).status_code == 200
    assert client.post(f"{KEYS}/{made.json()['id']}/rotate", headers=shop["owner"], json={}).status_code == 422  # already ended
    assert client.post(f"{KEYS}/{uuid4()}/rotate", headers=shop["owner"], json={}).status_code == 404
    assert client.post(f"{KEYS}/{old_id}/rotate", headers=shop["manager"], json={}).status_code == 403


def test_usage_is_recorded_and_shown(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "trust_forwarded_for", True)
    key_id, key = new_key(client, shop)
    assert row(client, shop, key_id)["last_used_at"] is None and row(client, shop, key_id)["use_count"] == 0
    for _ in range(3):
        client.get(CUSTOMERS, headers={**key, "X-Forwarded-For": "203.0.113.7"})
    used = row(client, shop, key_id)
    assert used["use_count"] == 3 and used["last_ip"] == "203.0.113.7" and used["last_used_at"]
    assert "key" not in used and "key_hash" not in used


def test_keys_are_private_to_their_business_and_audited_without_the_key(client, shop) -> None:  # type: ignore[no-untyped-def]
    key_id, key = new_key(client, shop)
    assert key_id not in {k["id"] for k in client.get(KEYS, headers=shop["other_owner"]).json()}
    assert client.delete(f"{KEYS}/{key_id}", headers=shop["other_owner"]).status_code == 404
    assert client.post(f"{KEYS}/{key_id}/rotate", headers=shop["other_owner"], json={}).status_code == 404
    client.post(f"{KEYS}/{key_id}/rotate", headers=shop["owner"], json={})
    client.delete(f"{KEYS}/{key_id}", headers=shop["owner"])
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        rows = s.execute(text("select action, changes::text as changes from kernel.audit_log "
                              "where entity_type = 'kernel.api_key' and entity_id = :i order by id"), {"i": key_id}).all()
    assert [r.action for r in rows] == ["create", "rotate", "revoke"]
    assert key["X-API-Key"] not in "".join(r.changes or "" for r in rows)
