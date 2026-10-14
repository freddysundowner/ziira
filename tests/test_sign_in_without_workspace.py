"""Signing in with only a login and a password: the platform finds the business from the login directory."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import OWNER_PASSWORD, make_tenant, sign_in
from tests.stock_helpers import system
from ziira.kernel import directory
from ziira.kernel.db import master_session

SIGN_IN = "/api/v1/auth/sign-in"


def attempt(client, login, password, workspace=None):  # type: ignore[no-untyped-def]
    body = {"login": login, "password": password, "device_id": "dev-1"}
    if workspace:
        body["workspace"] = workspace
    return client.post(SIGN_IN, json=body)


@pytest.fixture(scope="module")
def two_businesses(client, registry):  # type: ignore[no-untyped-def]
    a, b = make_tenant("Alpha Traders"), make_tenant("Bravo Stores")
    return a, b


def add_user(client, owner, name, email=None, phone=None, password="user-pass-12"):  # type: ignore[no-untyped-def]
    body = {"full_name": name, "password": password}
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    r = client.post("/api/v1/users", headers=owner, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_the_owner_signs_in_with_just_an_email_and_password(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    r = attempt(client, "owner@alpha-traders.test", OWNER_PASSWORD)
    assert r.status_code == 200, r.text
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["user_id"] == r.json()["user_id"] and me["tenant_id"] == str(two_businesses[0]["tenant_id"])
    assert attempt(client, "OWNER@Alpha-Traders.TEST", OWNER_PASSWORD).status_code == 200      # case never matters
    other = attempt(client, "owner@bravo-stores.test", OWNER_PASSWORD)
    assert other.status_code == 200 and other.json()["tenant_id"] != r.json()["tenant_id"]       # each to its own business


def test_a_user_added_later_signs_in_by_email_or_by_phone(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, "alpha-traders", "owner@alpha-traders.test").headers
    add_user(client, owner, "Late Joiner", email="late@alpha-traders.test", phone="+447700900123")
    by_email = attempt(client, "late@alpha-traders.test", "user-pass-12")
    by_phone = attempt(client, "+447700900123", "user-pass-12")
    assert by_email.status_code == 200 and by_phone.status_code == 200
    assert by_email.json()["user_id"] == by_phone.json()["user_id"]


def test_wrong_logins_and_passwords_get_one_answer(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    wrong_pass = attempt(client, "owner@alpha-traders.test", "not-the-password")
    unknown = attempt(client, f"nobody-{uuid4().hex[:6]}@nowhere.test", "whatever-pass")
    assert wrong_pass.status_code == unknown.status_code == 401
    assert wrong_pass.json() == unknown.json() == {"error": "unauthorized", "message": "Wrong login or password"}
    bad_workspace = attempt(client, "owner@alpha-traders.test", OWNER_PASSWORD, workspace="no-such-workspace")
    assert bad_workspace.status_code == 401
    with system(two_businesses[0]) as s:                                                       # the refusal is audited
        assert s.execute(text("select count(*) from kernel.audit_log where action = 'login_failed'")).scalar_one() >= 1


def test_a_disabled_user_cannot_sign_in(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, "alpha-traders", "owner@alpha-traders.test").headers
    gone = add_user(client, owner, "Leaver", email="leaver@alpha-traders.test")
    assert attempt(client, "leaver@alpha-traders.test", "user-pass-12").status_code == 200
    assert client.post(f"/api/v1/users/{gone['id']}/status", headers=owner, json={"active": False}).status_code == 200
    assert attempt(client, "leaver@alpha-traders.test", "user-pass-12").status_code == 401


def test_the_same_person_in_two_businesses_is_asked_which_one(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    owner_a = sign_in(client, "alpha-traders", "owner@alpha-traders.test").headers
    owner_b = sign_in(client, "bravo-stores", "owner@bravo-stores.test").headers
    add_user(client, owner_a, "Shared Person", email="shared@example.test", password="same-password-1")
    add_user(client, owner_b, "Shared Person", email="shared@example.test", password="same-password-1")
    asked = attempt(client, "shared@example.test", "same-password-1")
    assert asked.status_code == 409 and asked.json()["error"] == "choose_business"
    assert asked.json()["businesses"] == [{"workspace": "alpha-traders", "name": "Alpha Traders"},
                                          {"workspace": "bravo-stores", "name": "Bravo Stores"}]
    chosen = attempt(client, "shared@example.test", "same-password-1", workspace="bravo-stores")
    assert chosen.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {chosen.json()['access_token']}"}).json()
    assert me["tenant_id"] == str(two_businesses[1]["tenant_id"])                              # Bravo, as chosen
    # a wrong password reveals nothing about which businesses exist
    wrong = attempt(client, "shared@example.test", "wrong-password")
    assert wrong.status_code == 401 and "businesses" not in wrong.text


def test_different_passwords_in_two_businesses_sign_in_to_the_matching_one(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    owner_a = sign_in(client, "alpha-traders", "owner@alpha-traders.test").headers
    owner_b = sign_in(client, "bravo-stores", "owner@bravo-stores.test").headers
    add_user(client, owner_a, "Two Hats", email="hats@example.test", password="alpha-password-1")
    add_user(client, owner_b, "Two Hats", email="hats@example.test", password="bravo-password-1")
    a = attempt(client, "hats@example.test", "alpha-password-1")
    b = attempt(client, "hats@example.test", "bravo-password-1")
    assert a.status_code == b.status_code == 200 and a.json()["tenant_id"] != b.json()["tenant_id"]


def test_the_directory_holds_hashes_not_logins_and_follows_the_tenant(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Charlie Goods")
    login = "owner@charlie-goods.test"
    with master_session() as s:
        rows = s.execute(text("select identifier_hash from master.login_directory where tenant_id = :t"),
                         {"t": str(t["tenant_id"])}).scalars().all()
    assert rows == [directory.hash_login(login)] and login not in rows[0] and len(rows[0]) == 64
    assert directory.hash_login(" OWNER@charlie-goods.test ") == directory.hash_login(login)
    assert directory.tenants_for(login) == [t["tenant_id"]]
    from ziira.kernel.tenants import drop_tenant

    drop_tenant(t["tenant_id"])
    assert directory.tenants_for(login) == []                                                  # gone with the business
    assert attempt(client, login, OWNER_PASSWORD).status_code == 401


def test_the_directory_can_be_rebuilt_from_the_businesses_own_users(client, two_businesses) -> None:  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.login_directory"))
    assert attempt(client, "owner@alpha-traders.test", OWNER_PASSWORD).status_code == 401      # nothing to point at
    done = directory.rebuild()
    assert done >= 4
    assert attempt(client, "owner@alpha-traders.test", OWNER_PASSWORD).status_code == 200
    from ziira.kernel import cli

    assert cli.main(["index-logins", "bravo-stores"]) == 0
