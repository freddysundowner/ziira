"""Sign-in protection: password policy, throttling, the second factor (TOTP), who must use it, forgotten passwords."""

import base64
import time
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text

from tests.conftest import OWNER_PASSWORD, make_tenant, sign_in
from ziira.kernel import auth, mfa, passwords, throttle
from ziira.kernel.db import master_session
from ziira.kernel.errors import TooManyRequests, Unauthorized, ValidationFailed

API = "/api/v1"
RFC_SECRET = b"12345678901234567890"          # the shared secret of RFC 6238's test vectors


# --------------------------------------------------------------------------- the algorithm (RFC 6238 appendix B)
@pytest.mark.parametrize("moment, expected", [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"),
    (2000000000, "69279037"), (20000000000, "65353130")])
def test_totp_matches_the_rfc_test_vectors(moment: int, expected: str) -> None:
    assert mfa.totp(RFC_SECRET, moment, digits=8) == expected
    assert mfa.totp(RFC_SECRET, moment) == expected[-6:]                     # the 6-digit code is the last 6 digits


def test_a_code_is_valid_for_a_little_drift_and_only_once() -> None:
    now = 1_700_000_000.0
    code = mfa.totp(RFC_SECRET, now)
    counter = mfa.counter_at(now)
    assert mfa.match(RFC_SECRET, code, now) == counter
    assert mfa.match(RFC_SECRET, code, now + 30) == counter                 # a step later: still accepted
    assert mfa.match(RFC_SECRET, code, now - 30) == counter
    assert mfa.match(RFC_SECRET, code, now + 90) is None                    # three steps away: no
    assert mfa.match(RFC_SECRET, code, now, after_counter=counter) is None   # already used
    assert mfa.match(RFC_SECRET, " " + code[:3] + " " + code[3:] + " ", now) == counter   # typed with spaces
    for bad in ("", "12345", "1234567", "abcdef", "12345a"):
        assert mfa.match(RFC_SECRET, bad, now) is None


@given(st.binary(min_size=10, max_size=40), st.integers(min_value=60, max_value=4_000_000_000))
def test_a_generated_code_always_verifies_at_its_own_moment(secret: bytes, moment: int) -> None:
    code = mfa.totp(secret, float(moment))
    assert len(code) == 6 and code.isdigit() and mfa.match(secret, code, float(moment)) == mfa.counter_at(moment)


def test_new_secrets_and_backup_codes() -> None:
    secret = mfa.new_secret()
    assert len(base64.b32decode(secret + "=" * (-len(secret) % 8))) == 20 and mfa.new_secret() != secret
    codes = mfa.new_backup_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    uri = mfa.otpauth_uri(secret, "a b@example.test")
    assert uri.startswith("otpauth://totp/Ziira:a%20b%40example.test?secret=" + secret) and "digits=6" in uri


# --------------------------------------------------------------------------- passwords
@pytest.mark.parametrize("bad", ["short", "password", "Password1", "12345678", "aaaaaaaaaa", "abababab", "qwertyui"])
def test_weak_passwords_are_refused(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        passwords.check(bad)


def test_a_password_cannot_be_the_login() -> None:
    with pytest.raises(ValidationFailed, match="login"):
        passwords.check("pat.example", login="pat.example@example.test")
    with pytest.raises(ValidationFailed, match="login"):
        passwords.check("pat.example@example.test", login="pat.example@example.test")
    passwords.check("a-sensible-passphrase-7", login="pat.example@example.test")


# --------------------------------------------------------------------------- throttling
def test_repeated_wrong_passwords_lock_the_login_from_that_address_only(client, tenants) -> None:  # type: ignore[no-untyped-def]
    login = f"owner@{tenants['A'] and 'tenant-a'}.test"
    kw = dict(device_id="d", channel="web")
    for _ in range(5):
        with pytest.raises(Unauthorized):
            auth.sign_in(None, login, "wrong-password-1", ip_address="203.0.113.10", **kw)    # type: ignore[arg-type]
    with pytest.raises(TooManyRequests) as locked:                           # even the right password is refused now
        auth.sign_in(None, login, OWNER_PASSWORD, ip_address="203.0.113.10", **kw)           # type: ignore[arg-type]
    assert locked.value.status == 429 and locked.value.details and locked.value.details["retry_after"] > 60
    ok = auth.sign_in(None, login, OWNER_PASSWORD, ip_address="203.0.113.11", **kw)         # type: ignore[arg-type]
    assert ok.access_token                                                   # the real owner, elsewhere, is not locked out
    with pytest.raises(TooManyRequests):                                     # the guessing address stays locked
        auth.sign_in(None, login, "wrong-password-1", ip_address="203.0.113.10", **kw)       # type: ignore[arg-type]
    with pytest.raises(Unauthorized):                                        # a good sign-in cleared the login counter
        auth.sign_in(None, login, "wrong-password-1", ip_address="203.0.113.12", **kw)       # type: ignore[arg-type]


def test_the_api_answers_429_with_how_long_to_wait(client) -> None:  # type: ignore[no-untyped-def]
    login = f"ghost-{uuid4().hex[:8]}@example.test"                          # a login nobody has: guessing counts all the same
    body = {"login": login, "password": "wrong-password-1", "device_id": "d"}
    for _ in range(20):
        assert client.post(f"{API}/auth/sign-in", json=body).status_code == 401
    r = client.post(f"{API}/auth/sign-in", json=body)
    assert r.status_code == 429 and r.json()["error"] == "too_many_requests" and int(r.headers["Retry-After"]) > 60


def test_counters_expire_and_old_rows_are_purged() -> None:
    counters = [throttle.Counter("test:" + uuid4().hex, 2)]
    throttle.failed(counters)
    throttle.guard(counters)                                                 # one failure: fine
    throttle.failed(counters)
    with pytest.raises(TooManyRequests):
        throttle.guard(counters)
    with master_session() as s:                                              # the lock has run out and the row is old
        s.execute(text("update master.auth_throttle set locked_until = now() - interval '1 minute', "
                       "updated_at = now() - interval '3 days' where key = :k"), {"k": counters[0].key})
    throttle.guard(counters)
    assert throttle.purge(days=2) >= 1
    with master_session() as s:
        assert s.execute(text("select count(*) from master.auth_throttle where key = :k"),
                         {"k": counters[0].key}).scalar_one() == 0


# --------------------------------------------------------------------------- the second factor
def password_sign_in(client, workspace: str, login: str, password: str = OWNER_PASSWORD, device: str = "dev-1"):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/auth/sign-in", json={"workspace": workspace, "login": login, "password": password,
                                                    "device_id": device})


def forget_attempts() -> None:
    """Start a test with no failed attempts on record (an earlier test may have made some on purpose)."""
    with master_session() as s:
        s.execute(text("delete from master.auth_throttle where key like 'mfa%' or key like 'login:%' "
                       "or key like 'pair:%' or key like 'reset%'"))


CLOCK = {"now": time.time()}


@pytest.fixture(autouse=True)
def _fake_clock(monkeypatch):  # type: ignore[no-untyped-def]
    """Codes work once, so a test that needs several must let time move: the second factor reads this clock."""
    monkeypatch.setattr(mfa, "_now", lambda: CLOCK["now"])


def code_for(secret: str, offset_steps: int = 0) -> str:
    """The code the app shows now. Each call moves the clock on by a step (a fresh code), unless an offset is given."""
    if offset_steps == 0:
        CLOCK["now"] += 90                    # beyond the drift window of anything used before: always a new code
    return mfa.totp(base64.b32decode(secret + "=" * (-len(secret) % 8)), CLOCK["now"] + offset_steps * 30)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Factor Co")
    code = "factor-co"
    owner = sign_in(client, code, f"owner@{code}.test").headers
    cashier_role = next(r["id"] for r in client.get(f"{API}/roles", headers=owner).json() if r["name"] == "Cashier")
    cashier = client.post(f"{API}/users", headers=owner, json={
        "full_name": "Casey", "email": f"casey@{code}.test", "password": "casey-password-1"}).json()
    assert client.post(f"{API}/users/{cashier['id']}/roles", headers=owner, json={
        "role_id": cashier_role, "scope": "tenant"}).status_code == 201
    return {**t, "code": code, "owner": owner, "cashier_id": cashier["id"], "cashier_login": f"casey@{code}.test"}


def test_a_person_sets_up_a_second_factor_and_then_needs_it_to_sign_in(client, shop) -> None:  # type: ignore[no-untyped-def]
    h, login, code = shop["owner"], f"owner@{shop['code']}.test", shop["code"]
    assert client.get(f"{API}/auth/mfa", headers=h).json() == {
        "enabled": False, "backup_codes_left": 0, "policy": "off", "required": False}
    assert client.post(f"{API}/auth/mfa/enable", headers=h, json={"code": "123456"}).status_code == 422   # not started
    setup = client.post(f"{API}/auth/mfa/setup", headers=h).json()
    secret = setup["secret"]
    assert setup["otpauth_uri"].startswith("otpauth://totp/Ziira:") and secret in setup["otpauth_uri"]
    assert client.post(f"{API}/auth/mfa/enable", headers=h, json={"code": "000000"}).status_code == 422
    enabled = client.post(f"{API}/auth/mfa/enable", headers=h, json={"code": code_for(secret)})
    assert enabled.status_code == 200 and len(enabled.json()["backup_codes"]) == 10
    backup = enabled.json()["backup_codes"]
    assert client.get(f"{API}/auth/mfa", headers=h).json()["backup_codes_left"] == 10
    assert client.post(f"{API}/auth/mfa/setup", headers=h).status_code == 422          # already on

    first = password_sign_in(client, code, login)                                       # the password alone is not enough
    assert first.status_code == 401 and first.json()["error"] == "mfa_required"
    challenge = first.json()["challenge"]
    wrong = client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": "000000"})
    assert wrong.status_code == 401 and wrong.json()["error"] == "unauthorized"
    setup_code = mfa.totp(base64.b32decode(secret + "=" * (-len(secret) % 8)), CLOCK["now"])
    reused = client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": setup_code})
    assert reused.status_code == 401                                                    # the code that enabled it is used up
    good = code_for(secret)
    ok = client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": good})
    assert ok.status_code == 200
    tokens = ok.json()
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 200
    replay = client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": good})
    assert replay.status_code == 401                                                    # a code works once

    again = password_sign_in(client, code, login, device="dev-2").json()["challenge"]   # a backup code works once
    assert client.post(f"{API}/auth/mfa/verify", json={"challenge": again, "code": backup[0]}).status_code == 200
    third = password_sign_in(client, code, login, device="dev-3").json()["challenge"]
    assert client.post(f"{API}/auth/mfa/verify", json={"challenge": third, "code": backup[0]}).status_code == 401
    assert client.get(f"{API}/auth/mfa", headers=h).json()["backup_codes_left"] == 9
    shop["secret"], shop["backup"] = secret, backup


def test_a_backup_code_signs_in_in_a_request_with_no_earlier_context(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Found by the browser journey: the audit entry for a used backup code needs a context, and a real request starts
    with none (the test client reuses its worker's, which hid the 500)."""
    import contextvars

    forget_attempts()
    challenge = password_sign_in(client, shop["code"], f"owner@{shop['code']}.test", device="dev-b").json()["challenge"]
    tokens = contextvars.Context().run(auth.complete_mfa, challenge, shop["backup"][7])
    assert tokens.access_token
    wrong = password_sign_in(client, shop["code"], f"owner@{shop['code']}.test", device="dev-c").json()["challenge"]
    with pytest.raises(Unauthorized):
        contextvars.Context().run(auth.complete_mfa, wrong, "zzzzz-zzzzz")             # a failed attempt is audited too


def test_a_challenge_is_not_a_session_and_a_wrong_code_locks_after_a_few_tries(client, shop) -> None:  # type: ignore[no-untyped-def]
    forget_attempts()
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    challenge = password_sign_in(client, shop["code"], f"owner@{shop['code']}.test", device="dev-4").json()["challenge"]
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401
    codes = [client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": f"00000{i}"}).status_code
             for i in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429                                   # guessing the code is stopped
    forget_attempts()                                                                   # let the next tests sign in again


def new_owner_tokens(client, shop) -> dict[str, str]:  # type: ignore[no-untyped-def]
    forget_attempts()
    ch = password_sign_in(client, shop["code"], f"owner@{shop['code']}.test", device=f"dev-{uuid4().hex[:6]}")
    r = client.post(f"{API}/auth/mfa/verify", json={"challenge": ch.json()["challenge"],
                                                    "code": code_for(shop["secret"])})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_the_business_can_require_it_of_powerful_roles(client, shop) -> None:  # type: ignore[no-untyped-def]
    h = new_owner_tokens(client, shop)
    assert client.get(f"{API}/settings/security", headers=h).json() == {"mfa_policy": "off"}
    assert client.patch(f"{API}/settings/security", headers=h, json={"mfa_policy": "sometimes"}).status_code == 422
    assert client.patch(f"{API}/settings/security", headers=h, json={"mfa_policy": "privileged"}).json() == {
        "mfa_policy": "privileged"}
    casey = sign_in(client, shop["code"], shop["cashier_login"], "casey-password-1").headers
    assert client.get(f"{API}/users", headers=casey).status_code == 403                 # a cashier is not affected
    assert client.get(f"{API}/auth/mfa", headers=casey).json()["required"] is False
    # someone powerful who has not set it up gets a session that can only do the setup
    r = client.post(f"{API}/users", headers=h, json={"full_name": "Pat Admin", "email": f"pat@{shop['code']}.test",
                                                      "password": "pat-password-123"})
    roles = {x["name"]: x["id"] for x in client.get(f"{API}/roles", headers=h).json()}
    client.post(f"{API}/users/{r.json()['id']}/roles", headers=h, json={"role_id": roles["Owner"], "scope": "tenant"})
    pat = sign_in(client, shop["code"], f"pat@{shop['code']}.test", "pat-password-123").headers
    blocked = client.get(f"{API}/users", headers=pat)
    assert blocked.status_code == 403 and blocked.json()["error"] == "mfa_setup_required"
    assert client.get(f"{API}/companies", headers=pat).status_code == 403
    assert client.get(f"{API}/auth/me", headers=pat).status_code == 200                 # the setup calls work
    assert client.get(f"{API}/auth/mfa", headers=pat).json()["required"] is True
    secret = client.post(f"{API}/auth/mfa/setup", headers=pat).json()["secret"]
    assert client.post(f"{API}/auth/mfa/enable", headers=pat, json={"code": code_for(secret)}).status_code == 200
    assert client.post(f"{API}/auth/mfa/disable", headers=pat,                          # and cannot switch it off again
                       json={"password": "pat-password-123", "code": code_for(secret)}).status_code == 422
    ch = password_sign_in(client, shop["code"], f"pat@{shop['code']}.test", "pat-password-123", device="pat-2")
    ok = client.post(f"{API}/auth/mfa/verify", json={"challenge": ch.json()["challenge"], "code": code_for(secret)})
    assert ok.status_code == 200
    full = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get(f"{API}/users", headers=full).status_code == 200                  # now fully signed in
    shop["pat"], shop["pat_secret"] = r.json()["id"], secret
    client.patch(f"{API}/settings/security", headers=h, json={"mfa_policy": "off"})


def test_an_administrator_resets_a_lost_device_and_the_person_is_signed_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    h = new_owner_tokens(client, shop)
    pat = shop["pat"]
    ch = password_sign_in(client, shop["code"], f"pat@{shop['code']}.test", "pat-password-123", device="pat-3")
    tokens = client.post(f"{API}/auth/mfa/verify", json={"challenge": ch.json()["challenge"],
                                                         "code": code_for(shop["pat_secret"])}).json()
    pat_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=pat_headers).status_code == 200
    assert client.post(f"{API}/users/{pat}/mfa/reset", headers={"Authorization": "Bearer x"}).status_code == 401
    casey = sign_in(client, shop["code"], shop["cashier_login"], "casey-password-1").headers
    assert client.post(f"{API}/users/{pat}/mfa/reset", headers=casey).status_code == 403
    assert client.post(f"{API}/users/{pat}/mfa/reset", headers=h).status_code == 204
    assert client.get(f"{API}/auth/me", headers=pat_headers).status_code == 401         # signed out everywhere
    plain = password_sign_in(client, shop["code"], f"pat@{shop['code']}.test", "pat-password-123", device="pat-4")
    assert plain.status_code == 200                                                     # no second factor any more


def test_switching_it_off_needs_the_password_and_a_code(client, shop) -> None:  # type: ignore[no-untyped-def]
    h = new_owner_tokens(client, shop)
    body = {"password": "not-the-password-1", "code": code_for(shop["secret"])}
    assert client.post(f"{API}/auth/mfa/disable", headers=h, json=body).status_code == 401
    assert client.post(f"{API}/auth/mfa/backup-codes", headers=h,
                       json={"password": OWNER_PASSWORD, "code": "000000"}).status_code == 401
    renewed = client.post(f"{API}/auth/mfa/backup-codes", headers=h,
                          json={"password": OWNER_PASSWORD, "code": shop["backup"][1]})
    assert renewed.status_code == 200 and len(renewed.json()["backup_codes"]) == 10
    assert shop["backup"][2] not in renewed.json()["backup_codes"]
    off = client.post(f"{API}/auth/mfa/disable", headers=h,
                      json={"password": OWNER_PASSWORD, "code": renewed.json()["backup_codes"][0]})
    assert off.status_code == 204
    assert client.get(f"{API}/auth/mfa", headers=h).json()["enabled"] is False
    assert password_sign_in(client, shop["code"], f"owner@{shop['code']}.test", device="dev-z").status_code == 200


# --------------------------------------------------------------------------- forgotten passwords
def test_forgotten_password_end_to_end(client, shop) -> None:  # type: ignore[no-untyped-def]
    login = shop["cashier_login"]
    old = sign_in(client, shop["code"], login, "casey-password-1")
    asked = client.post(f"{API}/auth/password/forgot", json={"login": login})
    assert asked.status_code == 202 and asked.json()["dev_token"].startswith("zp_")
    token = asked.json()["dev_token"]
    unknown = client.post(f"{API}/auth/password/forgot", json={"login": f"nobody-{uuid4().hex[:6]}@example.test"})
    assert unknown.status_code == 202 and unknown.json()["message"] == asked.json()["message"]   # no hint either way
    assert unknown.json()["dev_token"] is None
    weak = client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "password1"})
    assert weak.status_code == 422                                                      # refused, and the link still works
    assert client.post(f"{API}/auth/password/reset", json={"token": "zp_nonsense", "new_password": "casey-new-pass-9"}
                       ).status_code == 401
    done = client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "casey-new-pass-9"})
    assert done.status_code == 204
    assert client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "casey-new-pass-8"}
                       ).status_code == 401                                             # one use only
    assert client.get(f"{API}/auth/me", headers=old.headers).status_code == 401         # signed out everywhere
    assert password_sign_in(client, shop["code"], login, "casey-password-1").status_code == 401
    assert password_sign_in(client, shop["code"], login, "casey-new-pass-9").status_code == 200
    with master_session() as s:
        assert s.execute(text("select count(*) from master.password_reset where used_at is not null")).scalar_one() >= 1


def test_asking_for_resets_over_and_over_is_limited(client, shop) -> None:  # type: ignore[no-untyped-def]
    login = shop["cashier_login"]
    codes = [client.post(f"{API}/auth/password/forgot", json={"login": login}).status_code for _ in range(5)]
    assert codes[-1] == 429 and codes[0] == 202
    with master_session() as s:
        s.execute(text("delete from master.auth_throttle where key like 'reset%'"))


# --------------------------------------------------------------------------- data exports are audited
def test_a_csv_download_is_written_to_the_audit_log(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import system

    registry.enable(shop["tenant_id"], "finance")
    owner = sign_in(client, shop["code"], f"owner@{shop['code']}.test").headers
    r = client.get(f"{API}/finance/exports/journal", headers=owner, params={
        "company_id": str(shop["company_id"]), "date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    with system(shop) as s:
        row = s.execute(text("select user_id, changes from kernel.audit_log where action = 'data_export' "
                             "order by id desc limit 1")).one()
        assert s.execute(text("select count(*) from kernel.audit_log where action = 'data_export'")).scalar_one() == 1
    assert str(row.user_id) == str(shop["owner_id"])
    assert row.changes["path"].endswith("/finance/exports/journal") and row.changes["bytes"] == len(r.content)
    assert "company_id=" in row.changes["query"]
    client.get(f"{API}/companies", headers=owner)                            # an ordinary reply writes nothing
    with system(shop) as s:
        assert s.execute(text("select count(*) from kernel.audit_log where action = 'data_export'")).scalar_one() == 1


def test_a_bad_or_old_challenge_has_its_own_error_code(client, shop) -> None:  # type: ignore[no-untyped-def]
    for challenge in ("nonsense", "a.b", password_sign_in(client, shop["code"], shop["cashier_login"],
                                                          "casey-new-pass-9").json().get("access_token", "x")):
        r = client.post(f"{API}/auth/mfa/verify", json={"challenge": challenge, "code": "123456"})
        assert r.status_code == 401 and r.json()["error"] == "challenge_expired"
