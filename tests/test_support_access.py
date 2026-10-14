"""Support access: a business lets platform staff in for a limited time; staff are operators with a second factor.

Covers: no grant -> no session; read-only and full limits; expiry and revocation on the very next request; token kinds
kept apart; operators' second factor and throttling; both logs; isolation between businesses; the owner's view.
"""

import base64
import time
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from ziira.kernel import mfa, operators
from ziira.kernel.db import master_session, tenant_session

API = "/api/v1"
OP_PASSWORD = "operator-pass-987"
_steps = iter(range(1, 10_000))          # each sign-in uses a later time step: a code works only once


@pytest.fixture(scope="module")
def biz(registry):  # type: ignore[no-untyped-def]
    a, b = make_tenant("Support A"), make_tenant("Support B")
    registry.enable(a["tenant_id"], "products")
    return {"A": a, "B": b}


def letters() -> str:
    """A unit code (letters only) that has not been used."""
    return "".join(chr(ord("a") + int(c, 16)) for c in uuid4().hex[:6])


def owner_of(client, code: str):  # type: ignore[no-untyped-def]
    return sign_in(client, code, f"owner@{code}.test", device_id=f"d-{uuid4().hex[:6]}")


def new_operator() -> tuple[str, str]:
    email = f"staff-{uuid4().hex[:8]}@ziira.test"
    _, secret, _ = operators.create_operator("Sam Support", email, OP_PASSWORD)
    return email, secret


def code_for(secret: str) -> tuple[str, float]:
    """A code for a time step nobody has used yet, and the moment to pretend it is."""
    moment = time.time() + 60 * next(_steps) + 3600
    raw = base64.b32decode(secret + "=" * (-len(secret) % 8))
    return mfa.totp(raw, moment), moment


def operator_token(client, email: str, secret: str) -> dict[str, str]:
    r = client.post(f"{API}/operator/sign-in", json={"email": email, "password": OP_PASSWORD})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"challenge"}                      # a password alone never gives access
    code, moment = code_for(secret)
    with patch.object(mfa, "_now", lambda: moment):
        v = client.post(f"{API}/operator/mfa/verify", json={"challenge": r.json()["challenge"], "code": code})
    assert v.status_code == 200, v.text
    return {"Authorization": f"Bearer {v.json()['access_token']}"}


def give_access(client, owner, level: str = "read", hours: int = 24) -> dict:  # type: ignore[type-arg,no-untyped-def]
    r = client.post(f"{API}/support/grants", headers=owner.headers,
                    json={"reason": "Help with a stock count", "level": level, "hours": hours})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def open_session(client, op, code: str):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/operator/businesses/{code}/support-session", headers=op)


def support_headers(r) -> dict[str, str]:  # type: ignore[no-untyped-def]
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --------------------------------------------------------------------------- consent
def test_no_grant_no_session_and_a_grant_opens_one(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    assert open_session(client, op, "support-a").status_code == 403           # nobody has agreed to anything
    owner = owner_of(client, "support-a")
    grant = give_access(client, owner)
    assert grant["status"] == "active" and grant["level"] == "read" and grant["sessions"] == []
    opened = open_session(client, op, "support-a")
    assert opened.status_code == 201 and opened.json()["level"] == "read"
    headers = support_headers(opened)
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["channel"] == "support" and me["support_session"]["operator"] == "Sam Support"
    assert me["user_id"] is None
    # The business sees the banner flag too.
    assert client.get(f"{API}/auth/me", headers=owner.headers).json()["support_session"]["level"] == "read"
    assert open_session(client, op, "no-such-business").status_code == 404


def test_only_a_person_with_the_permission_can_give_access(client, biz) -> None:  # type: ignore[no-untyped-def]
    assert client.post(f"{API}/support/grants", json={"reason": "x"}).status_code == 401
    owner = owner_of(client, "support-a")
    for body in ({"reason": "", "level": "read"}, {"reason": "x", "level": "root"}, {"reason": "x", "hours": 169},
                 {"reason": "x", "hours": 0}):
        assert client.post(f"{API}/support/grants", headers=owner.headers, json=body).status_code == 422
    default = client.post(f"{API}/support/grants", headers=owner.headers, json={"reason": "Default length"}).json()
    assert default["level"] == "read"
    hours = (time.mktime(time.strptime(default["expires_at"][:19], "%Y-%m-%dT%H:%M:%S"))
             - time.mktime(time.strptime(default["created_at"][:19], "%Y-%m-%dT%H:%M:%S"))) / 3600
    assert 23.9 < hours < 24.1


def test_one_businesss_grant_gives_nothing_in_another(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    give_access(client, owner_of(client, "support-b"), hours=1)
    only_b = open_session(client, op, "support-b")
    headers = support_headers(only_b)
    assert client.get(f"{API}/auth/me", headers=headers).json()["tenant_id"] == str(biz["B"]["tenant_id"])
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 404   # products is not enabled in B


# --------------------------------------------------------------------------- limits
def test_read_only_allows_reads_and_refuses_every_write(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    give_access(client, owner, "read")
    headers = support_headers(open_session(client, op, "support-a"))
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 200
    for method, path in (("post", "/products/uoms"), ("post", "/auth/password"), ("delete", "/auth/sessions/" + str(uuid4())),
                         ("patch", "/companies/" + str(biz["A"]["company_id"]) + "/settings")):
        r = client.request(method.upper(), f"{API}{path}", headers=headers, json={"code": "X", "name": "x"})
        assert r.status_code == 403, (method, path, r.text)
    # A read-only session holds view permissions only: no payroll pay, no cost, no management.
    perms = {p for a in client.get(f"{API}/auth/me", headers=headers).json()["roles"] for p in a["permissions"]}
    assert perms and all(p.endswith(".view") for p in perms) and "payroll.view" not in perms
    assert client.get(f"{API}/users", headers=headers).status_code == 403


def test_full_access_can_work_but_not_keep_or_hide_its_access(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    give_access(client, owner, "full")
    headers = support_headers(open_session(client, op, "support-a"))
    made = client.post(f"{API}/products/uoms", headers=headers, json={"code": letters(), "name": "Made by support"})
    assert made.status_code == 201, made.text
    someone = owner.user_id
    forbidden = [("post", "/auth/password"), ("post", "/auth/mfa/setup"), ("post", "/auth/mfa/disable"),
                 ("post", f"/users/{someone}/password"), ("post", f"/users/{someone}/roles"),
                 ("post", f"/users/{someone}/status"), ("post", f"/users/{someone}/mfa/reset"),
                 ("post", "/users"), ("post", "/roles"), ("post", "/api-keys"), ("patch", "/settings/security"),
                 ("post", "/support/grants"), ("post", f"/support/grants/{uuid4()}/revoke"),
                 ("delete", f"/auth/sessions/{uuid4()}"), ("post", "/auth/sign-out")]
    for method, path in forbidden:
        r = client.request(method.upper(), f"{API}{path}", headers=headers, json={})
        assert r.status_code in (401, 403), (method, path, r.status_code)
    with master_session() as m:     # the platform log names the route, never the real id
        routes = set(m.execute(text("select route from master.support_access_log where tenant_id = :t and status = 403"),
                               {"t": str(biz["A"]["tenant_id"])}).scalars())
    assert "/api/v1/users/{user_id}/password" in routes and not any(str(someone) in r for r in routes)
    perms = {p for a in client.get(f"{API}/auth/me", headers=headers).json()["roles"] for p in a["permissions"]}
    assert "products.manage" in perms and not perms & {"users.manage", "roles.manage", "api_keys.manage", "support.grant"}
    assert client.get(f"{API}/support/grants", headers=headers).status_code == 403
    # The owner's password still works: nothing above changed it.
    owner_of(client, "support-a")


def revoke_all(client, owner) -> None:  # type: ignore[no-untyped-def]
    for g in client.get(f"{API}/support/grants?limit=200", headers=owner.headers).json():
        if g["status"] == "active":
            assert client.post(f"{API}/support/grants/{g['id']}/revoke", headers=owner.headers).status_code == 200


# --------------------------------------------------------------------------- expiry and revocation
def test_expiry_applies_to_a_session_that_is_already_open(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    grant = give_access(client, owner, hours=1)
    headers = support_headers(open_session(client, op, "support-a"))
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 200
    with tenant_session(biz["A"]["tenant_id"]) as s:
        s.execute(text("update kernel.support_grant set expires_at = now() - interval '1 second' where id = :i"),
                  {"i": grant["id"]})
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 401
    assert open_session(client, op, "support-a").status_code == 403           # and no new session
    listed = client.get(f"{API}/support/grants", headers=owner.headers).json()
    assert next(g for g in listed if g["id"] == grant["id"])["status"] == "expired"


def test_revoking_ends_every_open_session_at_once(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    grant = give_access(client, owner)
    first = support_headers(open_session(client, op, "support-a"))
    second = support_headers(open_session(client, op, "support-a"))
    assert client.get(f"{API}/products/uoms", headers=first).status_code == 200
    revoked = client.post(f"{API}/support/grants/{grant['id']}/revoke", headers=owner.headers)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert all(s["ended_at"] for s in revoked.json()["sessions"]) and len(revoked.json()["sessions"]) == 2
    assert client.get(f"{API}/products/uoms", headers=first).status_code == 401
    assert client.get(f"{API}/products/uoms", headers=second).status_code == 401
    assert client.get(f"{API}/auth/me", headers=owner.headers).json()["support_session"] is None
    assert open_session(client, op, "support-a").status_code == 403
    with master_session() as m:
        events = m.execute(text("select count(*) from master.support_access_log where grant_id = :g "
                                "and event = 'revoked'"), {"g": grant["id"]}).scalar()
    assert events == 2


def test_a_disabled_operator_loses_open_sessions_and_sign_in(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    give_access(client, owner)
    headers = support_headers(open_session(client, op, "support-a"))
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 200
    operators.set_status(email, "disabled")
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 401
    assert client.get(f"{API}/operator/businesses", headers=op).status_code == 401
    assert client.post(f"{API}/operator/sign-in", json={"email": email, "password": OP_PASSWORD}).status_code == 401
    operators.set_status(email, "active")
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 200


# --------------------------------------------------------------------------- operators
def test_token_kinds_cannot_be_swapped(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    assert client.get(f"{API}/operator/businesses", headers=owner.headers).status_code == 401   # tenant token
    assert client.get(f"{API}/operator/businesses", headers={"X-Tenant-ID": str(biz["A"]["tenant_id"])}).status_code == 401
    assert client.get(f"{API}/auth/me", headers=op).status_code == 401                          # operator token
    assert client.get(f"{API}/operator/businesses", headers=op).status_code == 200
    challenge = client.post(f"{API}/operator/sign-in", json={"email": email, "password": OP_PASSWORD}).json()["challenge"]
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401
    assert client.get(f"{API}/operator/businesses", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401
    revoke_all(client, owner)
    give_access(client, owner)
    support = support_headers(open_session(client, op, "support-a"))
    assert client.get(f"{API}/operator/businesses", headers=support).status_code == 401         # support token
    names = client.get(f"{API}/operator/businesses", headers=op).json()
    assert {"code": "support-a", "name": "Support A"} in names and all(set(n) == {"code", "name"} for n in names)


def test_operators_need_the_second_factor_and_are_throttled(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    r = client.post(f"{API}/operator/sign-in", json={"email": email, "password": OP_PASSWORD}).json()
    for _ in range(5):
        wrong = client.post(f"{API}/operator/mfa/verify", json={"challenge": r["challenge"], "code": "000000"})
        assert wrong.status_code == 401
    code, moment = code_for(secret)
    with patch.object(mfa, "_now", lambda: moment):
        locked = client.post(f"{API}/operator/mfa/verify", json={"challenge": r["challenge"], "code": code})
    assert locked.status_code == 429 and "Retry-After" in locked.headers            # even the right code, now
    other, _ = new_operator()
    for _ in range(5):
        assert client.post(f"{API}/operator/sign-in", json={"email": other, "password": "wrong-pass-123"}).status_code == 401
    assert client.post(f"{API}/operator/sign-in", json={"email": other, "password": OP_PASSWORD}).status_code == 429
    assert client.post(f"{API}/operator/sign-in", json={"email": "nobody@ziira.test", "password": "x"}).status_code == 401
    # A challenge is not a token, and a code works only once.
    email2, secret2 = new_operator()
    ok = operator_token(client, email2, secret2)
    assert client.get(f"{API}/operator/businesses", headers=ok).status_code == 200
    ch = client.post(f"{API}/operator/sign-in", json={"email": email2, "password": OP_PASSWORD}).json()["challenge"]
    code2, moment2 = code_for(secret2)
    with patch.object(mfa, "_now", lambda: moment2):
        assert client.post(f"{API}/operator/mfa/verify", json={"challenge": ch, "code": code2}).status_code == 200
        assert client.post(f"{API}/operator/mfa/verify", json={"challenge": ch, "code": code2}).status_code == 401


def test_operator_sign_out_and_cli_management(client, biz, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    email, secret = new_operator()
    op = operator_token(client, email, secret)
    assert client.post(f"{API}/operator/sign-out", headers=op).status_code == 204
    assert client.get(f"{API}/operator/businesses", headers=op).status_code == 401
    monkeypatch.setenv("ZIIRA_OPERATOR_PASSWORD", OP_PASSWORD)
    cli_email = f"cli-{uuid4().hex[:6]}@ziira.test"
    assert cli.main(["operator", "create", "Cli Person", cli_email]) == 0
    assert "secret:" in capsys.readouterr().out
    assert cli.main(["operator", "create", "Again", cli_email]) == 1                  # duplicate email
    assert cli.main(["operator", "disable", cli_email]) == 0
    assert cli.main(["operator", "list"]) == 0
    assert f"{cli_email}" in capsys.readouterr().out
    assert cli.main(["operator", "reset-mfa", cli_email]) == 0


# --------------------------------------------------------------------------- logs, notice, owner's view
def test_every_request_lands_in_both_logs_and_the_owner_sees_it(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    grant = give_access(client, owner, "full")
    opened = open_session(client, op, "support-a")
    headers = support_headers(opened)
    session_id = opened.json()["session_id"]
    uom = client.post(f"{API}/products/uoms", headers=headers, json={"code": letters(), "name": "Logged"})
    assert uom.status_code == 201, uom.text
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 200
    assert client.post(f"{API}/auth/password", headers=headers, json={}).status_code == 403

    with master_session() as m:
        rows = m.execute(text("select event, method, route, status, operator_id from master.support_access_log "
                              "where support_session_id = :s order by id"), {"s": session_id}).all()
    assert [r.event for r in rows] == ["start", "request", "request", "refused"]
    assert [(r.method, r.route, r.status) for r in rows[1:]] == [
        ("POST", "/api/v1/products/uoms", 201), ("GET", "/api/v1/products/uoms", 200),
        ("POST", "/api/v1/auth/password", 403)]
    assert all(str(r.operator_id) == str(rows[0].operator_id) for r in rows)

    log = client.get(f"{API}/support/access-log", headers=owner.headers)
    assert log.status_code == 200
    mine = [e for e in log.json() if e["entity_id"] == session_id or e["detail"].get("grant_id") == grant["id"]]
    actions = [e["action"] for e in mine]
    assert actions.count("support_request") == 3 and "support_session_started" in actions
    assert {e["operator"] for e in mine} == {"Sam Support"}
    # The write itself is in the normal audit log, channel support, naming the operator.
    with tenant_session(biz["A"]["tenant_id"]) as s:
        wrote = s.execute(text("select channel, user_id, changes->>'support_operator' as who from kernel.audit_log "
                               "where action = 'create' and changes->>'support_operator_id' is not null "
                               "order by id desc limit 1")).first()
    assert wrote is not None and wrote.channel == "support" and wrote.user_id is None and wrote.who == "Sam Support"
    grants = client.get(f"{API}/support/grants", headers=owner.headers).json()
    sessions = next(g for g in grants if g["id"] == grant["id"])["sessions"]
    assert [s["id"] for s in sessions] == [session_id] and sessions[0]["requests"] == 3
    # Another business sees none of it, and staff cannot read the log.
    assert client.get(f"{API}/support/access-log", headers=owner_of(client, "support-b").headers).json() == [] or all(
        e["entity_id"] != session_id for e in client.get(f"{API}/support/access-log",
                                                         headers=owner_of(client, "support-b").headers).json())
    assert client.get(f"{API}/support/access-log", headers=headers).status_code == 403
    # Ending the session closes it in both places.
    assert client.post(f"{API}/operator/sessions/{session_id}/end", headers=op).status_code == 204
    assert client.get(f"{API}/products/uoms", headers=headers).status_code == 401
    listed = client.get(f"{API}/operator/sessions", headers=op).json()
    assert listed[0]["id"] == session_id and listed[0]["ended_at"] and listed[0]["business"] == "support-a"


def test_the_person_who_gave_access_is_emailed_when_it_is_used(client, biz) -> None:  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    op = operator_token(client, email, secret)
    owner = owner_of(client, "support-a")
    revoke_all(client, owner)
    give_access(client, owner)
    assert open_session(client, op, "support-a").status_code == 201
    with tenant_session(biz["A"]["tenant_id"]) as s:
        row = s.execute(text("select recipient, subject, body from kernel.notification where ref_type = 'support_session' "
                             "order by created_at desc limit 1")).first()
    assert row is not None and row.recipient == "owner@support-a.test" and "support" in row.subject.lower()
    assert "Sam Support" in row.body


def test_the_database_keeps_the_platform_log_and_isolates_grants(biz) -> None:  # type: ignore[no-untyped-def]
    with master_session() as m, pytest.raises(Exception, match="cannot be changed"):
        m.execute(text("update master.support_access_log set status = 200"))
    with tenant_session(biz["B"]["tenant_id"]) as s:
        rows = s.execute(text("select tenant_id from kernel.support_grant")).scalars().all()
    assert all(UUID(str(r)) == biz["B"]["tenant_id"] for r in rows)
