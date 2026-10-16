"""Operator roles and permissions: every operator route names a permission, each role can use exactly what it should (a
matrix over the real routes), operators are managed in the console, and every change is in the operator trail."""

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.operator_mode import operator_mode
from tests.platform_helpers import API, code_for, staff
from tests.test_operator_console import age_confirmation, trail
from tests.test_support_access import OP_PASSWORD
from ziira.kernel import mfa, operators
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import permissions

_second_factor = operator_mode("totp")        # the operator-management tests here use the authenticator-app sign-in

OPEN_ROUTES = {"/api/v1/operator/sign-in", "/api/v1/operator/mfa/verify", "/api/v1/operator/sign-out",
               "/api/v1/operator/me", "/api/v1/operator/mfa/confirm", "/api/v1/operator/confirm",
               "/api/v1/operator/password", "/api/v1/operator/sign-out-all"}
ROLES = list(permissions.ROLES)


@pytest.fixture(scope="module")
def operator_routes(registry):  # type: ignore[no-untyped-def]
    """Every route of the operator API with the permission it declares (None if it declares none)."""
    found = []
    from ziira.kernel.api import operator_routes, operator_unit_routes, platform_routes

    all_routes = [*operator_routes.router.routes, *operator_unit_routes.router.routes, *platform_routes.router.routes]
    for route in all_routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1/operator") or path in OPEN_ROUTES:
            continue
        needed = {getattr(d.call, "platform_permission", None) for d in route.dependant.dependencies}  # type: ignore[attr-defined]
        needed.discard(None)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):  # type: ignore[attr-defined]
            found.append((method, path, needed.pop() if len(needed) == 1 else None))
    return found


@pytest.fixture(scope="module")
def by_role(client, registry):  # type: ignore[no-untyped-def]
    return {role: staff(client, role) for role in ROLES}


def concrete(path: str) -> str:
    """A path with every parameter filled by something that matches nothing."""
    out = path
    for part in path.split("/"):
        if part.startswith("{"):
            out = out.replace(part, str(UUID(int=0)) if part.endswith("_id}") else "nothing")
    return out


def test_every_operator_route_declares_a_known_permission(operator_routes) -> None:  # type: ignore[no-untyped-def]
    assert len(operator_routes) > 60                                                      # the whole console is covered
    missing = [(m, p) for m, p, perm in operator_routes if perm is None]
    assert missing == [], f"routes without a permission: {missing}"
    assert {perm for _, _, perm in operator_routes} <= set(permissions.PERMISSIONS)


def test_each_role_is_refused_what_it_may_not_do_on_every_route(client, operator_routes, by_role) -> None:  # type: ignore[no-untyped-def]
    checked = 0
    for method, path, needed in operator_routes:
        for role in ROLES:
            if needed in permissions.permissions_of(role):
                if method == "GET" and "{" not in path:
                    r = client.get(f"{path}", headers=by_role[role]["headers"])
                    assert r.status_code != 403, (role, path, r.text)
                continue                                    # an allowed change is not made here: the tests of each area do that
            r = client.request(method, concrete(path), headers=by_role[role]["headers"], json={} if method != "GET" else None)
            assert r.status_code == 403, (role, method, path, r.status_code, r.text)
            assert needed in r.json()["message"]
            checked += 1
    assert checked > 120


def test_nobody_without_an_operator_token_reaches_any_route(client, operator_routes, registry) -> None:  # type: ignore[no-untyped-def]
    for method, path, _ in operator_routes:
        r = client.request(method, concrete(path), json={} if method != "GET" else None)
        assert r.status_code == 401, (method, path)


def test_me_tells_the_screen_what_the_role_allows(client, by_role) -> None:  # type: ignore[no-untyped-def]
    for role in ROLES:
        me = client.get(f"{API}/operator/me", headers=by_role[role]["headers"]).json()
        assert me["role"] == role and set(me["permissions"]) == permissions.permissions_of(role)


def test_roles_are_listed_for_the_screens(client, by_role) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/operator/roles", headers=by_role["readonly"]["headers"]).json()
    assert [x["role"] for x in r["roles"]] == ROLES and "platform.licences" in r["permissions"]


# --------------------------------------------------------------------------- managing operators
def test_a_superadmin_adds_an_operator_who_can_sign_in_with_the_second_factor(client, by_role) -> None:  # type: ignore[no-untyped-def]
    boss = by_role["superadmin"]["headers"]
    email = f"new-{uuid4().hex[:6]}@ziira.test"
    r = client.post(f"{API}/operator/operators", headers=boss, json={
        "name": "Bea Billing", "email": email, "password": OP_PASSWORD, "role": "billing"})
    assert r.status_code == 201, r.text
    secret = r.json()["mfa_secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://")
    # the new person signs in: a password alone gives nothing
    signed = client.post(f"{API}/operator/sign-in", json={"email": email, "password": OP_PASSWORD})
    code, moment = code_for(secret)
    with patch.object(mfa, "_now", lambda: moment):
        token = client.post(f"{API}/operator/mfa/verify", json={"challenge": signed.json()["challenge"], "code": code})
    assert token.status_code == 200
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    assert client.get(f"{API}/operator/me", headers=headers).json()["role"] == "billing"
    blocked = client.get(f"{API}/operator/operators", headers=headers)                          # a console-made account
    assert blocked.status_code == 403 and blocked.json()["error"] == "password_change_required"
    assert client.post(f"{API}/operator/password", headers=headers, json={
        "current_password": OP_PASSWORD, "new_password": "billing-chose-this-9"}).status_code == 204
    assert client.get(f"{API}/operator/operators", headers=headers).status_code == 403          # not for billing
    # the secret is never written to the trail
    lines = trail("operator.create")
    assert any(x["target"] == email for x in lines)
    assert all(secret not in str(x) for x in lines)
    # a weak password is refused, and so is a repeated email
    weak = client.post(f"{API}/operator/operators", headers=boss, json={
        "name": "Weak One", "email": f"w-{uuid4().hex[:5]}@ziira.test", "password": "short", "role": "readonly"})
    assert weak.status_code == 422
    twice = client.post(f"{API}/operator/operators", headers=boss, json={
        "name": "Bea Again", "email": email, "password": OP_PASSWORD, "role": "billing"})
    assert twice.status_code == 422


def test_changing_a_role_ends_that_operators_sign_ins(client, by_role) -> None:  # type: ignore[no-untyped-def]
    boss = by_role["superadmin"]["headers"]
    victim = staff(client, "billing")
    assert client.get(f"{API}/operator/me", headers=victim["headers"]).status_code == 200
    r = client.patch(f"{API}/operator/operators/{victim['id']}", headers=boss, json={"role": "readonly"})
    assert r.status_code == 200 and r.json()["role"] == "readonly"
    assert client.get(f"{API}/operator/me", headers=victim["headers"]).status_code == 401      # signs in again to get the new role
    off = client.patch(f"{API}/operator/operators/{victim['id']}", headers=boss, json={"status": "disabled"})
    assert off.json()["status"] == "disabled"
    assert {x["action"] for x in trail() if x["target"] == victim["email"]} >= {"operator.update"}


def test_nobody_changes_their_own_role(client, by_role) -> None:  # type: ignore[no-untyped-def]
    me = by_role["superadmin"]
    r = client.patch(f"{API}/operator/operators/{me['id']}", headers=me["headers"], json={"role": "readonly"})
    assert r.status_code == 422 and "your own" in r.json()["message"]


def test_the_last_superadmin_cannot_be_disabled_or_demoted(registry) -> None:  # type: ignore[no-untyped-def]
    email = f"last-{uuid4().hex[:6]}@ziira.test"
    operators.create_operator("Only One", email, OP_PASSWORD, "superadmin")
    with pytest.raises(ValidationFailed, match="last active superadmin"), master_session() as m:
        m.execute(text("update master.operator set status = 'disabled' where role = 'superadmin' "
                       "and lower(email) <> :e"), {"e": email})                   # rolled back when the error leaves the block
        operators._keep_one_superadmin(m, email)


def test_a_superadmin_resets_a_second_factor(client, by_role) -> None:  # type: ignore[no-untyped-def]
    boss = by_role["superadmin"]["headers"]
    person = staff(client, "support")
    r = client.post(f"{API}/operator/operators/{person['id']}/reset-mfa", headers=boss)
    assert r.status_code == 200 and r.json()["mfa_secret"] != person["secret"]
    assert client.get(f"{API}/operator/me", headers=person["headers"]).status_code == 401       # their sign-in ended
    assert all(r.json()["mfa_secret"] not in str(x) for x in trail("operator.reset_mfa"))


def test_the_command_line_makes_a_superadmin_by_default_and_other_roles_on_request(registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    email = f"cli-{uuid4().hex[:6]}@ziira.test"
    import os
    os.environ["ZIIRA_OPERATOR_PASSWORD"] = OP_PASSWORD
    assert cli.main(["operator", "create", "Cli Boss", email]) == 0
    assert cli.main(["operator", "create", "Cli Billing", "b" + email, "--role", "billing"]) == 0
    roles = {o["email"]: o["role"] for o in operators.list_operators()}
    assert roles[email] == "superadmin" and roles["b" + email] == "billing"
    assert cli.main(["operator", "role", "b" + email, "support"]) == 0
    assert {o["email"]: o["role"] for o in operators.list_operators()}["b" + email] == "support"
    os.environ.pop("ZIIRA_OPERATOR_PASSWORD")


# --------------------------------------------------------------------------- the trail and the second factor
def test_changes_need_a_fresh_code_and_are_in_the_trail_even_when_refused(client, by_role) -> None:  # type: ignore[no-untyped-def]
    boss = staff(client, "superadmin")
    body = {"code": "plan-trail", "name": "Trail plan", "units": ["products"]}
    age_confirmation(boss, 30)
    stale = client.post(f"{API}/operator/plans", headers=boss["headers"], json=body)
    assert stale.status_code == 403 and stale.json()["error"] == "mfa_step_up_required"
    age_confirmation(boss, 1)
    assert client.post(f"{API}/operator/plans", headers=boss["headers"], json=body).status_code == 201
    refused = client.post(f"{API}/operator/plans", headers=boss["headers"], json={**body, "code": "x"})
    assert refused.status_code in (409, 422)
    outcomes = [(x["action"], x["outcome"]) for x in trail() if x["target"] in ("plan-trail", "x")]
    assert ("plan.create", "ok") in outcomes and ("plan.create", "refused") in outcomes
