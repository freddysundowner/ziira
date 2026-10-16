"""Platform staff signing in with an email and password alone (ZIIRA_OPERATOR_MFA=off, the default): the sign-in, the
protections that stay (lockout, generic errors, session limits, audit, password rule), the password confirmation
before changes, temporary passwords, the address allow-list, and the production guard.

The authenticator-app mode keeps its own tests (test_support_access.py, test_operator_console.py, test_platform_roles.py)."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.operator_mode import operator_mode
from tests.test_support_access import API, letters
from ziira.kernel import operators
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed

_password_only = operator_mode("off", trust_forwarded_for="true", operator_signin_emails="true")

PW = "a-long-operator-pass-42"


def new_operator(role: str = "superadmin", *, must_change: bool = False) -> str:
    email = f"pw-{uuid4().hex[:8]}@ziira.test"
    operators.create_operator("Pat Password", email, PW, role, must_change_password=must_change)
    return email


def sign_in(client, email: str, password: str = PW, ip: str | None = None):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/operator/sign-in", json={"email": email, "password": password},
                       headers={"X-Forwarded-For": ip} if ip else {})


def token_of(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def staff(client, role: str = "superadmin") -> dict:  # type: ignore[type-arg,no-untyped-def]
    email = new_operator(role)
    return {"email": email, "headers": token_of(sign_in(client, email))}


def trail(action: str, **where: str) -> list[dict]:  # type: ignore[type-arg]
    with master_session() as m:
        rows = m.execute(text(
            "select operator_id, operator_name, target, outcome, detail, ip_address from master.operator_action_log "
            "where action = :a order by id"), {"a": action})
        return [dict(r._mapping) for r in rows]


def session_row(email: str) -> dict:  # type: ignore[type-arg]
    with master_session() as m:
        return dict(m.execute(text(
            "select s.id, s.created_at, s.expires_at, s.last_seen_at, s.revoked_at from master.operator_session s "
            "join master.operator o on o.id = s.operator_id where lower(o.email) = :e order by s.created_at desc "
            "limit 1"), {"e": email}).one()._mapping)


@pytest.fixture
def settings(monkeypatch):  # type: ignore[no-untyped-def]
    """Change a setting for one test (a ZIIRA_* name without the prefix)."""
    def apply(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(f"ZIIRA_{key.upper()}", value)
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


# --------------------------------------------------------------------------- the sign-in
def test_a_password_alone_signs_an_operator_in(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator("billing")
    r = sign_in(client, email.upper())                                   # the email is not case sensitive
    assert r.status_code == 200
    assert set(r.json()) == {"access_token", "expires_in", "must_change_password"}     # no challenge, no code step
    assert r.json()["expires_in"] == 8 * 3600 and r.json()["must_change_password"] is False
    me = client.get(f"{API}/operator/me", headers=token_of(r)).json()
    assert me["role"] == "billing" and me["mfa_mode"] == "off" and me["mfa_off_in_production"] is False
    assert me["must_change_password"] is False and me["step_up_needed"] is False      # signing in counts as confirming
    with master_session() as m:
        stored = m.execute(text("select mfa_secret_enc, last_sign_in_at from master.operator where lower(email) = :e"),
                           {"e": email}).one()
    assert stored.mfa_secret_enc == "" and stored.last_sign_in_at is not None          # no second factor was created


def test_creating_an_operator_makes_no_secret_when_the_second_factor_is_off() -> None:
    _id, secret, uri = operators.create_operator("No Secret", f"ns-{uuid4().hex[:6]}@ziira.test", PW)
    assert (secret, uri) == ("", "")


def test_a_wrong_email_a_wrong_password_and_a_disabled_account_answer_alike(client) -> None:  # type: ignore[no-untyped-def]
    email, off = new_operator(), new_operator()
    operators.set_status(off, "disabled")
    answers = [sign_in(client, email, "not-the-password-1"), sign_in(client, f"nobody-{uuid4().hex[:5]}@ziira.test"),
               sign_in(client, off)]
    assert {a.status_code for a in answers} == {401}
    assert len({(a.json()["error"], a.json()["message"]) for a in answers}) == 1
    assert answers[0].json()["message"] == "Wrong email or password"


def test_guessing_is_counted_and_locks_the_login(client) -> None:  # type: ignore[no-untyped-def]
    email, other = new_operator(), new_operator()
    for _ in range(5):
        assert sign_in(client, email, "wrong-guess-123").status_code == 401
    locked = sign_in(client, email)                                      # even the right password is refused now
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert sign_in(client, other).status_code == 200                      # somebody else is not affected


def test_a_good_sign_in_clears_the_failures_before_it(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    for _ in range(4):
        sign_in(client, email, "wrong-guess-123")
    assert sign_in(client, email).status_code == 200
    for _ in range(4):
        assert sign_in(client, email, "wrong-guess-123").status_code == 401        # the count started again
    assert sign_in(client, email).status_code == 200


def test_one_address_guessing_many_logins_is_locked_out(client) -> None:  # type: ignore[no-untyped-def]
    ip = f"198.51.100.{uuid4().int % 200 + 1}"
    for i in range(30):
        assert sign_in(client, f"guess-{i}-{uuid4().hex[:4]}@ziira.test", "wrong-guess-123", ip=ip).status_code == 401
    assert sign_in(client, new_operator(), ip=ip).status_code == 429


def test_every_sign_in_is_in_the_trail_and_never_with_the_password(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    stranger = f"stranger-{uuid4().hex[:6]}@ziira.test"
    sign_in(client, email, "wrong-guess-123", ip="203.0.113.7")
    sign_in(client, email, ip="203.0.113.8")
    sign_in(client, stranger, "wrong-guess-123", ip="203.0.113.9")
    sign_in(client, "my secret password", "wrong-guess-123")
    lines = trail("auth.sign_in")
    mine = [x for x in lines if x["operator_name"] == "Pat Password"][-2:]
    assert [(x["outcome"], x["ip_address"]) for x in mine] == [("refused", "203.0.113.7"), ("ok", "203.0.113.8")]
    assert mine[0]["detail"]["why"] == "wrong password" and mine[1]["detail"]["second_factor"] == "off"
    unknown = next(x for x in lines if x["target"] == stranger)
    assert unknown["operator_id"] is None and unknown["outcome"] == "refused" and unknown["detail"]["why"] == "unknown login"
    assert any(x["target"] == "(not an email)" for x in lines)            # what was typed in the email box is not kept
    dump = json.dumps(lines, default=str)
    assert PW not in dump and "wrong-guess-123" not in dump and "my secret password" not in dump


def test_sessions_are_short_and_end_when_idle(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    h = token_of(sign_in(client, email))
    row = session_row(email)
    assert timedelta(hours=7, minutes=59) < row["expires_at"] - row["created_at"] <= timedelta(hours=8, seconds=5)
    # a request refreshes the idle clock (written at most every 30 seconds)
    with master_session() as m:
        m.execute(text("update master.operator_session set last_seen_at = now() - interval '10 minutes' where id = :i"),
                  {"i": str(row["id"])})
    assert client.get(f"{API}/operator/me", headers=h).status_code == 200
    assert session_row(email)["last_seen_at"] > row["created_at"]
    # silent for longer than the idle limit: signed out, and it stays ended
    with master_session() as m:
        m.execute(text("update master.operator_session set last_seen_at = now() - interval '31 minutes' where id = :i"),
                  {"i": str(row["id"])})
    gone = client.get(f"{API}/operator/me", headers=h)
    assert gone.status_code == 401 and "inactivity" in gone.json()["message"]
    assert session_row(email)["revoked_at"] is not None
    assert client.get(f"{API}/operator/me", headers=h).status_code == 401


def test_a_sign_in_ends_at_its_absolute_limit(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    h = token_of(sign_in(client, email))
    with master_session() as m:
        m.execute(text("update master.operator_session set expires_at = now() - interval '1 second' where id = :i"),
                  {"i": str(session_row(email)["id"])})
    assert client.get(f"{API}/operator/me", headers=h).status_code == 401


def test_the_session_length_and_idle_limit_are_settings(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings(operator_session_hours="2", operator_idle_minutes="5")
    email = new_operator()
    r = sign_in(client, email)
    assert r.json()["expires_in"] == 2 * 3600
    with master_session() as m:
        m.execute(text("update master.operator_session set last_seen_at = now() - interval '6 minutes' where id = :i"),
                  {"i": str(session_row(email)["id"])})
    assert client.get(f"{API}/operator/me", headers=token_of(r)).status_code == 401


def test_signing_out_and_signing_out_everywhere(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    one, two, three = (token_of(sign_in(client, email)) for _ in range(3))
    assert client.post(f"{API}/operator/sign-out", headers=one).status_code == 204
    assert client.get(f"{API}/operator/me", headers=one).status_code == 401
    assert client.get(f"{API}/operator/me", headers=two).status_code == 200
    assert client.post(f"{API}/operator/sign-out-all", headers=two).status_code == 204
    assert client.get(f"{API}/operator/me", headers=two).status_code == 401
    assert client.get(f"{API}/operator/me", headers=three).status_code == 401
    assert {x["outcome"] for x in trail("auth.sign_out_everywhere")} == {"ok"}


def test_a_business_token_is_not_an_operator_token_and_the_reverse(client) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    assert client.get(f"{API}/auth/me", headers=h).status_code in (401, 403)
    assert client.get(f"{API}/operator/me").status_code == 401


# --------------------------------------------------------------------------- the password rule
@pytest.mark.parametrize("password", ["short-one", "elevenchars", "password1234", "aaaaaaaaaaaaaaaa"])
def test_an_operator_password_must_be_long_and_not_obvious(password: str) -> None:
    with pytest.raises(ValidationFailed):
        operators.create_operator("Weak", f"weak-{uuid4().hex[:6]}@ziira.test", password)


def test_an_operator_password_cannot_be_the_email() -> None:
    email = f"long-address-{uuid4().hex[:6]}@ziira.test"
    with pytest.raises(ValidationFailed, match="login"):
        operators.create_operator("Same", email, email)


def test_changing_your_own_password(client) -> None:  # type: ignore[no-untyped-def]
    me = staff(client)
    email, h = me["email"], me["headers"]
    other = token_of(sign_in(client, email))
    new = "another-long-pass-77"
    url = f"{API}/operator/password"
    assert client.post(url, headers=h, json={"current_password": "not-mine-at-all-1", "new_password": new}).status_code == 401
    assert client.post(url, headers=h, json={"current_password": PW, "new_password": PW}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": PW, "new_password": "short"}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": PW, "new_password": "password1234"}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": PW, "new_password": email}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": PW, "new_password": new}).status_code == 204
    assert client.get(f"{API}/operator/me", headers=h).status_code == 200            # this sign-in carries on
    assert client.get(f"{API}/operator/me", headers=other).status_code == 401        # every other one ended
    assert sign_in(client, email).status_code == 401 and sign_in(client, email, new).status_code == 200
    assert {"ok", "refused"} <= {x["outcome"] for x in trail("auth.password_change")}
    assert new not in json.dumps(trail("auth.password_change"), default=str)


def test_wrong_current_passwords_are_counted_and_lock(client) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    for _ in range(5):
        r = client.post(f"{API}/operator/password", headers=h,
                        json={"current_password": "not-mine-at-all-1", "new_password": "another-long-pass-77"})
        assert r.status_code == 401
    assert client.post(f"{API}/operator/password", headers=h, json={
        "current_password": PW, "new_password": "another-long-pass-77"}).status_code == 429
    assert client.get(f"{API}/operator/me", headers=h).status_code == 200            # a wrong guess does not sign out


# --------------------------------------------------------------------------- confirming again before a change
def make_plan(client, headers):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/operator/plans", headers=headers, json={"code": f"pw-{letters()}", "name": "Test", "units": ["products"]})


def age_confirmation(email: str, minutes: int) -> None:
    with master_session() as m:
        m.execute(text("update master.operator_session set mfa_verified_at = now() - make_interval(mins => :n) "
                       "where operator_id = (select id from master.operator where lower(email) = :e)"),
                  {"n": minutes, "e": email})


def test_a_change_asks_for_the_password_again_when_the_last_confirmation_is_old(client) -> None:  # type: ignore[no-untyped-def]
    me = staff(client)
    h, email = me["headers"], me["email"]
    assert make_plan(client, h).status_code == 201                                  # signing in just confirmed
    age_confirmation(email, 9)
    assert make_plan(client, h).status_code == 201                                  # inside the window
    age_confirmation(email, 11)
    assert client.get(f"{API}/operator/me", headers=h).json()["step_up_needed"] is True
    stale = make_plan(client, h)
    assert stale.status_code == 403 and stale.json()["error"] == "mfa_step_up_required"
    assert stale.json()["message"] == "Confirm your password to make this change"
    refused = [x for x in trail("plan.create") if x["outcome"] == "refused"][-1]
    assert refused["detail"]["why"] == "password not confirmed recently"
    assert client.get(f"{API}/operator/plans", headers=h).status_code == 200        # reading never asks

    wrong = client.post(f"{API}/operator/confirm", headers=h, json={"password": "not-mine-at-all-1"})
    assert wrong.status_code == 401 and wrong.json()["message"] == "That password is not right"
    assert make_plan(client, h).status_code == 403                                  # a wrong password confirms nothing
    assert client.post(f"{API}/operator/confirm", headers=h, json={}).status_code == 422
    assert client.post(f"{API}/operator/confirm", headers=h, json={"code": "123456"}).status_code == 422   # not a code mode
    ok = client.post(f"{API}/operator/confirm", headers=h, json={"password": PW})
    assert ok.status_code == 200 and ok.json()["valid_minutes"] == 10
    assert client.get(f"{API}/operator/me", headers=h).json()["step_up_needed"] is False
    assert make_plan(client, h).status_code == 201
    age_confirmation(email, 30)                                                     # the older path still works
    assert client.post(f"{API}/operator/mfa/confirm", headers=h, json={"password": PW}).status_code == 200
    assert {x["outcome"] for x in trail("auth.confirm")} == {"ok", "refused"}


def test_wrong_confirmation_passwords_lock(client) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    for _ in range(5):
        assert client.post(f"{API}/operator/confirm", headers=h, json={"password": "not-mine-at-all-1"}).status_code == 401
    assert client.post(f"{API}/operator/confirm", headers=h, json={"password": PW}).status_code == 429


def test_the_freshness_window_is_a_setting(client, settings) -> None:  # type: ignore[no-untyped-def]
    me = staff(client)
    settings(operator_mfa_max_age_minutes="2")
    age_confirmation(me["email"], 3)
    assert make_plan(client, me["headers"]).status_code == 403


# --------------------------------------------------------------------------- temporary passwords
def test_an_operator_made_in_the_console_chooses_their_own_password(client) -> None:  # type: ignore[no-untyped-def]
    boss = staff(client)["headers"]
    email = f"new-{uuid4().hex[:6]}@ziira.test"
    made = client.post(f"{API}/operator/operators", headers=boss, json={"name": "Nia New", "email": email, "role": "billing"})
    assert made.status_code == 201, made.text
    temp = made.json()["temporary_password"]
    assert temp and made.json()["mfa_secret"] is None and made.json()["otpauth_uri"] is None
    assert temp not in json.dumps(trail("operator.create"), default=str)

    r = sign_in(client, email, temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    h = token_of(r)
    me = client.get(f"{API}/operator/me", headers=h).json()
    assert me["must_change_password"] is True
    blocked = client.get(f"{API}/operator/plans", headers=h)                        # nothing else until it is changed
    assert blocked.status_code == 403 and blocked.json()["error"] == "password_change_required"
    assert client.get(f"{API}/operator/businesses", headers=h).status_code == 403
    new = "nia-chose-this-pass-9"
    assert client.post(f"{API}/operator/password", headers=h, json={"current_password": temp, "new_password": temp}) \
        .status_code == 422
    assert client.post(f"{API}/operator/password", headers=h, json={"current_password": temp, "new_password": new}) \
        .status_code == 204
    assert client.get(f"{API}/operator/me", headers=h).json()["must_change_password"] is False
    assert client.get(f"{API}/operator/plans", headers=h).status_code == 200
    assert sign_in(client, email, temp).status_code == 401 and sign_in(client, email, new).status_code == 200


def test_a_chosen_password_in_the_console_is_also_changed_at_first_sign_in(client) -> None:  # type: ignore[no-untyped-def]
    boss = staff(client)["headers"]
    email = f"chosen-{uuid4().hex[:6]}@ziira.test"
    made = client.post(f"{API}/operator/operators", headers=boss,
                       json={"name": "Chas Chosen", "email": email, "password": PW, "role": "readonly"})
    assert made.status_code == 201 and made.json()["temporary_password"] is None
    assert sign_in(client, email).json()["must_change_password"] is True
    weak = client.post(f"{API}/operator/operators", headers=boss,
                       json={"name": "Weak Wes", "email": f"w-{uuid4().hex[:5]}@ziira.test", "password": "password1234",
                             "role": "readonly"})
    assert weak.status_code == 422


def test_a_superadmin_resets_a_password(client) -> None:  # type: ignore[no-untyped-def]
    boss = staff(client)
    target = new_operator("support")
    target_id = next(o["id"] for o in operators.list_operators() if o["email"] == target)
    old_session = token_of(sign_in(client, target))
    r = client.post(f"{API}/operator/operators/{target_id}/reset-password", headers=boss["headers"])
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    assert len(temp) >= 16 and temp not in json.dumps(trail("operator.reset_password"), default=str)
    assert client.get(f"{API}/operator/me", headers=old_session).status_code == 401           # their sign-ins ended
    assert sign_in(client, target).status_code == 401
    assert sign_in(client, target, temp).json()["must_change_password"] is True
    # not for yourself, not for a support operator, not without a recent confirmation
    mine = next(o["id"] for o in operators.list_operators() if o["email"] == boss["email"])
    assert client.post(f"{API}/operator/operators/{mine}/reset-password", headers=boss["headers"]).status_code == 422
    assert client.post(f"{API}/operator/operators/{target_id}/reset-password",
                       headers=staff(client, "support")["headers"]).status_code == 403
    age_confirmation(boss["email"], 15)
    assert client.post(f"{API}/operator/operators/{target_id}/reset-password",
                       headers=boss["headers"]).json()["error"] == "mfa_step_up_required"


def test_the_command_line_reset(client) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    h = token_of(sign_in(client, email))
    temp = operators.reset_password(email)                                          # as `ziira operator reset-password`
    assert client.get(f"{API}/operator/me", headers=h).status_code == 401
    assert sign_in(client, email, temp).json()["must_change_password"] is True
    chosen = "chosen-on-the-command-line-5"
    operators.reset_password(email, password=chosen)                                # with ZIIRA_OPERATOR_PASSWORD
    assert sign_in(client, email, chosen).json()["must_change_password"] is False
    with pytest.raises(ValidationFailed):
        operators.reset_password(email, password="short")
    line = [x for x in trail("auth.password_reset") if x["target"] == email][-1]
    assert line["operator_name"] == "(command line)"


# --------------------------------------------------------------------------- the address allow-list
def test_only_listed_networks_reach_the_operator_routes(client, settings) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()
    h = token_of(sign_in(client, email))
    settings(operator_allowed_networks="203.0.113.0/24, 2001:db8::/32")
    inside = {"X-Forwarded-For": "203.0.113.77"}
    assert sign_in(client, email, ip="203.0.113.77").status_code == 200
    assert client.get(f"{API}/operator/me", headers={**h, **inside}).status_code == 200
    assert client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": "2001:db8::5"}).status_code == 200
    for outside in ("198.51.100.4", "203.0.114.1", "2001:db9::1", "10.0.0.1"):
        denied = client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": outside})
        assert denied.status_code == 403 and denied.json()["error"] == "network_not_allowed", outside
        assert sign_in(client, email, ip=outside).status_code == 403
        assert client.get(f"{API}/operator/health", headers={**h, "X-Forwarded-For": outside}).status_code == 403
    assert client.get(f"{API}/operator/me", headers=h).status_code == 403            # no readable address at all
    assert client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": "not an address"}).status_code == 403


def test_a_forged_forwarded_for_entry_does_not_open_the_door(client, settings) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    settings(operator_allowed_networks="203.0.113.0/24")
    # the proxy appends the real address last; whatever the caller put before it is ignored
    forged = client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": "203.0.113.5, 198.51.100.9"})
    assert forged.status_code == 403
    genuine = client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": "198.51.100.9, 203.0.113.5"})
    assert genuine.status_code == 200


def test_the_forwarded_header_is_ignored_unless_a_proxy_is_trusted(client, settings) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    settings(operator_allowed_networks="203.0.113.0/24", trust_forwarded_for="false")
    assert client.get(f"{API}/operator/me", headers={**h, "X-Forwarded-For": "203.0.113.5"}).status_code == 403


def test_the_allow_list_leaves_business_routes_alone(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings(operator_allowed_networks="203.0.113.0/24")
    assert client.get(f"{API}/auth/me", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 401   # not 403
    assert client.get("/health").status_code == 200


def test_an_empty_allow_list_restricts_nothing(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings(operator_allowed_networks="")
    assert sign_in(client, new_operator(), ip="198.51.100.1").status_code == 200
    assert sign_in(client, new_operator()).status_code == 200


# --------------------------------------------------------------------------- a sign-in from a new address
def test_a_sign_in_from_a_new_address_is_emailed(client) -> None:  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeEmail

    email = new_operator()
    FakeEmail.sent.clear()

    def mails() -> list:  # type: ignore[type-arg]
        return [m for m in FakeEmail.sent if m.recipient == email]

    assert sign_in(client, email, ip="203.0.113.21").status_code == 200
    assert len(mails()) == 1 and "203.0.113.21" in mails()[0].body and PW not in mails()[0].body
    assert sign_in(client, email, ip="203.0.113.21").status_code == 200
    assert len(mails()) == 1                                                        # the same address again: quiet
    assert sign_in(client, email, ip="203.0.113.22").status_code == 200
    assert len(mails()) == 2
    FakeEmail.fail_next = 1                                                         # a broken mailer never blocks sign-in
    assert sign_in(client, email, ip="203.0.113.23").status_code == 200


def test_the_new_address_email_is_off_unless_switched_on(client, settings) -> None:  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeEmail

    settings(operator_signin_emails="false")
    email = new_operator()
    FakeEmail.sent.clear()
    assert sign_in(client, email, ip="203.0.113.31").status_code == 200
    assert not [m for m in FakeEmail.sent if m.recipient == email]


# --------------------------------------------------------------------------- warnings and the other mode
def test_the_console_is_told_when_production_has_no_second_factor(client, settings) -> None:  # type: ignore[no-untyped-def]
    h = staff(client)["headers"]
    settings(env="production", operator_mfa_off_acknowledged="true")
    me = client.get(f"{API}/operator/me", headers=h)
    assert me.status_code == 200 and me.json()["mfa_off_in_production"] is True


def test_a_second_factor_operator_cannot_sign_in_again_in_totp_mode_without_one(client, settings) -> None:  # type: ignore[no-untyped-def]
    email = new_operator()                                                          # made while the factor was off
    settings(operator_mfa="totp")
    r = sign_in(client, email)
    assert r.status_code == 401 and "reset-mfa" in r.json()["message"]
    operators.reset_mfa(email)                                                      # now they have a secret
    assert "challenge" in sign_in(client, email).json()


def test_the_built_in_default_is_password_only() -> None:
    from ziira.kernel.config import Settings

    assert Settings.model_fields["operator_mfa"].default == "off"
