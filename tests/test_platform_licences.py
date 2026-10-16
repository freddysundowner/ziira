"""Licences for outright purchase and self-hosted copies: issue (vendor), install and check (customer), tamper, wrong
key, instance binding, expiry with grace, revocation, a clock moved back, the never-destroy rule, and the command line.

The vendor's private key is made here for the test and given to the 'vendor' only through a key file; the 'customer'
side is configured with the public key alone, as a real copy would be."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, T0
from ziira.kernel import cli
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import entitlements, licences

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def vendor(tmp_path_factory, registry):  # type: ignore[no-untyped-def]
    """A key pair; this process acts as a self-hosted copy that knows only the public key."""
    private, public = licences.generate_keypair()
    key_file = tmp_path_factory.mktemp("vendor") / "signing.key"
    key_file.write_text(private)
    env = {"ZIIRA_DEPLOYMENT_MODE": "selfhosted", "ZIIRA_LICENCE_PUBLIC_KEY": public,
           "ZIIRA_LICENCE_SIGNING_KEY_FILE": str(key_file)}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    get_settings.cache_clear()
    entitlements.invalidate()
    yield {"private": private, "public": public, "key_file": key_file, "dir": key_file.parent}
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    with master_session() as m:
        for table in ("master.installed_licence", "master.licence_revocation"):
            m.execute(text(f"delete from {table}"))
        m.execute(text("delete from master.platform_setting where key = 'clock.last_seen'"))
    entitlements.invalidate()


@pytest.fixture(autouse=True)
def clean_slate(vendor):  # type: ignore[no-untyped-def]
    with master_session() as m:
        m.execute(text("delete from master.installed_licence"))
        m.execute(text("delete from master.licence_revocation"))
        m.execute(text("delete from master.platform_setting where key = 'clock.last_seen'"))
    entitlements.invalidate()
    yield


def issue(**kw):  # type: ignore[no-untyped-def]
    return licences.issue(customer="Acme Hardware", units=["products"], max_users=kw.pop("max_users", 2), now=kw.pop("now", NOW),
                          valid_until=kw.pop("valid_until", NOW + timedelta(days=365)), **kw)


def business(registry, name: str):  # type: ignore[no-untyped-def]
    t = make_tenant(name)
    registry.enable(t["tenant_id"], "products")
    return t["tenant_id"], f"owner@{name.lower().replace(' ', '-')}.test", name.lower().replace(" ", "-")


# --------------------------------------------------------------------------- issuing and installing
def test_a_vendor_issues_and_a_copy_installs_and_reads_the_licence(vendor) -> None:  # type: ignore[no-untyped-def]
    row = issue(contact_email="it@acme.test", notes="first sale")
    assert row["licence_no"].startswith("LIC-") and row["status"] == "active" and row["token"]
    assert licences.verify(row["token"], vendor["public"])["customer"] == "Acme Hardware"
    info = licences.install(row["token"], by="Ann")
    assert (info["status"], info["access"], info["customer"]) == ("valid", "full", "Acme Hardware")
    assert info["entitlements"]["units"] == ["products"] and info["entitlements"]["max_users"] == 2
    assert info["days_left"] in (364, 365) and info["instance_id"]


def test_licence_numbers_run_in_order(vendor) -> None:  # type: ignore[no-untyped-def]
    a, b = issue(), issue()
    assert int(b["licence_no"][4:]) == int(a["licence_no"][4:]) + 1


def test_a_plan_can_be_the_starting_point_of_a_licence(vendor) -> None:  # type: ignore[no-untyped-def]
    from tests.platform_helpers import make_plan

    make_plan("lic-plan", units=["products", "inventory"], prices={("USD", "one_time"): "5000.00"}, max_users=9,
              max_branches=4)
    row = licences.issue(customer="Plan Buyer", plan_code="lic-plan", max_users=20, now=NOW)
    assert row["entitlements"]["units"] == ["inventory", "products"] and row["valid_until"] is None   # perpetual
    assert (row["entitlements"]["max_users"], row["entitlements"]["max_branches"]) == (20, 4)         # an override wins


def test_a_licence_must_end_in_the_future_and_name_something(vendor) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed, match="future"):
        licences.issue(customer="Late Co", units=["products"], now=NOW, valid_until=NOW - timedelta(days=1))
    with pytest.raises(ValidationFailed, match="edition or some units"):
        licences.issue(customer="Empty Co", now=NOW)
    with pytest.raises(ValidationFailed, match="Unknown unit"):
        licences.issue(customer="Ghost Co", units=["nothing_here"], now=NOW)


# --------------------------------------------------------------------------- what a copy refuses
def test_an_edited_licence_is_refused(vendor) -> None:  # type: ignore[no-untyped-def]
    row = issue()
    with pytest.raises(ValidationFailed, match="signature"):
        licences.install(row["token"].replace('"max_users": 2', '"max_users": 200'))
    assert licences.describe()["installed"] is False


def test_a_licence_from_another_vendor_is_refused(vendor) -> None:  # type: ignore[no-untyped-def]
    other_private, _ = licences.generate_keypair()
    row = issue(private_key=other_private)
    with pytest.raises(ValidationFailed, match="signature"):
        licences.install(row["token"])


def test_a_licence_bound_to_another_installation_is_refused(vendor) -> None:  # type: ignore[no-untyped-def]
    elsewhere = issue(instance_id="some-other-box")
    with pytest.raises(ValidationFailed, match="some-other-box"):
        licences.install(elsewhere["token"])
    here = issue(instance_id=licences.instance_id())
    assert licences.install(here["token"])["status"] == "valid"


def test_the_instance_id_is_stable(vendor) -> None:  # type: ignore[no-untyped-def]
    assert licences.instance_id() == licences.instance_id() and len(licences.instance_id()) == 16


def test_a_copy_without_the_public_key_cannot_check_anything(vendor) -> None:  # type: ignore[no-untyped-def]
    row = issue()
    os.environ["ZIIRA_LICENCE_PUBLIC_KEY"] = ""
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationFailed, match="no vendor public key"):
            licences.install(row["token"])
    finally:
        os.environ["ZIIRA_LICENCE_PUBLIC_KEY"] = vendor["public"]
        get_settings.cache_clear()


def test_a_copy_has_no_signing_key_so_it_cannot_issue(vendor) -> None:  # type: ignore[no-untyped-def]
    os.environ["ZIIRA_LICENCE_SIGNING_KEY_FILE"] = ""
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationFailed, match="signing key"):
            licences.issue(customer="Pirate Co", units=["products"], now=NOW)
    finally:
        os.environ["ZIIRA_LICENCE_SIGNING_KEY_FILE"] = str(vendor["key_file"])
        get_settings.cache_clear()


# --------------------------------------------------------------------------- enforcement over HTTP
def test_the_licences_units_and_limits_are_enforced(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Enforce")
    owner = sign_in(client, code, login).headers
    licences.install(issue()["token"])
    entitlements.invalidate()
    assert client.post(f"{API}/units/inventory/enable", headers=owner).json()["error"] == "not_in_plan"
    ok = client.post(f"{API}/users", headers=owner, json={"full_name": "Second", "email": f"s-{uuid4().hex[:5]}@x.test"})
    assert ok.status_code == 201
    over = client.post(f"{API}/users", headers=owner, json={"full_name": "Third", "email": f"t-{uuid4().hex[:5]}@x.test"})
    assert over.status_code == 402 and over.json()["error"] == "plan_limit_reached" and over.json()["limit"] == 2
    info = client.get(f"{API}/billing/licence", headers=owner).json()
    assert info["mode"] == "selfhosted" and info["status"] == "valid"
    assert info["usage"]["users"] == {"used": 2, "limit": 2}


def test_an_expired_licence_graces_then_goes_read_only_and_never_deletes(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Expiry")
    owner = sign_in(client, code, login).headers
    # ended 10 days ago with 30 days of grace: still works, with a warning
    row = licences.issue(customer="Lapsed Co", units=["products"], now=NOW - timedelta(days=100),
                         valid_until=NOW - timedelta(days=10), grace_days=30)
    licences.install(row["token"])
    entitlements.invalidate()
    info = licences.describe()
    assert (info["status"], info["access"]) == ("grace", "warning") and info["days_left"] == -11
    assert client.post(f"{API}/users", headers=owner, json={"full_name": "Grace", "email": "g@x.test"}).status_code == 201
    assert client.get(f"{API}/billing/status", headers=owner).json()["banner"]["level"] == "warning"
    # ended 40 days ago: read-only; the data is all still there
    old = licences.issue(customer="Lapsed Co", units=["products"], now=NOW - timedelta(days=100),
                         valid_until=NOW - timedelta(days=40), grace_days=30)
    licences.install(old["token"])
    entitlements.invalidate()
    assert licences.describe()["status"] == "expired"
    users = client.get(f"{API}/users", headers=owner)
    assert users.status_code == 200 and len(users.json()) == 2
    refused = client.post(f"{API}/users", headers=owner, json={"full_name": "Late", "email": "l@x.test"})
    assert refused.status_code == 402 and refused.json()["error"] == "subscription_ended"
    assert "read-only" in refused.json()["message"] and "data is safe" in refused.json()["message"]
    # a renewed licence puts it right
    licences.install(issue()["token"])
    entitlements.invalidate()
    assert client.post(f"{API}/users", headers=owner, json={"full_name": "Back", "email": "b@x.test"}).status_code in (201, 402)
    assert licences.describe()["status"] == "valid"


def test_with_a_frozen_clock_the_stages_follow_the_dates(registry, vendor) -> None:  # type: ignore[no-untyped-def]
    row = licences.issue(customer="Clock Co", units=["products"], now=T0, valid_until=T0 + timedelta(days=60),
                         grace_days=10)
    licences.install(row["token"])
    tid = make_tenant("Lic Clock")["tenant_id"]
    seen = {days: entitlements.for_tenant(tid, now=T0 + timedelta(days=days)) for days in (10, 40, 65, 71)}
    assert [(seen[d].status, seen[d].access) for d in (10, 40, 65, 71)] == [
        ("valid", "full"), ("valid", "warning"), ("grace", "warning"), ("expired", "read_only")]


def test_no_licence_is_fine_until_one_is_required(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Required")
    owner = sign_in(client, code, login).headers
    assert client.post(f"{API}/users", headers=owner, json={"full_name": "A", "email": "a@x.test"}).status_code == 201
    os.environ["ZIIRA_LICENCE_REQUIRED"] = "true"
    get_settings.cache_clear()
    entitlements.invalidate()
    try:
        refused = client.post(f"{API}/users", headers=owner, json={"full_name": "B", "email": "b@x.test"})
        assert refused.status_code == 402 and "No licence is installed" in refused.json()["message"]
        assert client.get(f"{API}/users", headers=owner).status_code == 200                       # still readable
        # the owner installs the licence file from the screen
        installed = client.post(f"{API}/billing/licence", headers=owner, json={"file": issue(max_users=10)["token"]})
        assert installed.status_code == 200 and installed.json()["status"] == "valid"
        assert client.post(f"{API}/users", headers=owner, json={"full_name": "C", "email": "c@x.test"}).status_code == 201
        bad = client.post(f"{API}/billing/licence", headers=owner, json={"file": "this is not a licence file"})
        assert bad.status_code == 422
    finally:
        os.environ.pop("ZIIRA_LICENCE_REQUIRED", None)
        get_settings.cache_clear()
        entitlements.invalidate()


# --------------------------------------------------------------------------- revocation
def test_a_revoked_licence_stops_working_once_the_copy_learns_of_it(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Revoked")
    owner = sign_in(client, code, login).headers
    row = issue()
    licences.install(row["token"])
    entitlements.invalidate()
    assert client.get(f"{API}/billing/licence", headers=owner).json()["status"] == "valid"
    revoked = licences.revoke(row["id"], "payment bounced")                    # on the vendor's side
    assert revoked["status"] == "revoked" and revoked["revoked_reason"] == "payment bounced"
    assert licences.describe()["status"] == "valid"                            # the copy does not know yet
    assert licences.install_revocations(licences.revocation_list()) >= 1       # the signed list reaches it
    entitlements.invalidate()
    info = client.get(f"{API}/billing/licence", headers=owner).json()
    assert (info["status"], info["access"]) == ("revoked", "read_only")
    assert client.get(f"{API}/users", headers=owner).status_code == 200
    assert client.post(f"{API}/users", headers=owner, json={"full_name": "N", "email": "n@x.test"}).status_code == 402
    with pytest.raises(ValidationFailed, match="active licence"):
        licences.revoke(row["id"], "again for the second time")


def test_a_forged_revocation_list_is_refused(vendor) -> None:  # type: ignore[no-untyped-def]
    other_private, _ = licences.generate_keypair()
    forged = licences.sign({"kind": "revocation", "issued_at": NOW.isoformat(), "licence_nos": ["LIC-000001"]}, other_private)
    with pytest.raises(ValidationFailed, match="signature"):
        licences.install_revocations(forged)
    not_a_list = issue()["token"]
    with pytest.raises(ValidationFailed, match="not a revocation list"):
        licences.install_revocations(not_a_list)


# --------------------------------------------------------------------------- the clock
def test_a_clock_moved_back_is_noticed_but_small_drift_is_not(registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tolerance = get_settings().licence_clock_tolerance_hours
    assert licences.clock_rolled_back(NOW) is False                           # first sight: remembered
    assert licences.clock_rolled_back(NOW + timedelta(days=3)) is False       # forward is fine, and remembered
    assert licences.clock_rolled_back(NOW + timedelta(days=3) - timedelta(hours=tolerance - 1)) is False
    assert licences.clock_rolled_back(NOW + timedelta(days=3) - timedelta(hours=tolerance + 1)) is True
    assert licences.clock_rolled_back(NOW + timedelta(days=3, minutes=5)) is False          # back to normal: still fine


def test_a_rolled_back_clock_makes_a_valid_licence_read_only(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Rollback")
    owner = sign_in(client, code, login).headers
    licences.install(issue()["token"])
    licences.clock_rolled_back(NOW + timedelta(days=30))                       # the instance has seen a later date
    entitlements.invalidate()
    info = client.get(f"{API}/billing/licence", headers=owner).json()
    assert (info["status"], info["access"]) == ("clock_rollback", "read_only")
    assert "clock" in info["message"]
    assert client.get(f"{API}/users", headers=owner).status_code == 200


# --------------------------------------------------------------------------- the command line
def test_the_command_line_makes_keys_licences_and_installs_them(vendor, capsys) -> None:  # type: ignore[no-untyped-def]
    out = vendor["dir"] / "cli"
    assert cli.main(["licence", "keygen", "--out", str(out)]) == 0
    key_file = out / "licence-signing.key"
    assert key_file.exists() and (key_file.stat().st_mode & 0o077) == 0       # readable by the owner only
    public = capsys.readouterr().out.strip().splitlines()[-1]
    licence_file = vendor["dir"] / "cli.ziira-licence"
    until = (NOW + timedelta(days=200)).strftime("%Y-%m-%d")
    assert cli.main(["licence", "issue", "--customer", "Cli Customer", "--units", "products", "--max-users", "4",
                     "--valid-until", until, "--key", str(key_file), "--out", str(licence_file)]) == 0
    os.environ["ZIIRA_LICENCE_PUBLIC_KEY"] = public                            # this copy trusts the CLI-made key
    get_settings.cache_clear()
    try:
        assert cli.main(["licence", "verify", str(licence_file)]) == 0
        assert cli.main(["licence", "install", str(licence_file)]) == 0
        assert cli.main(["licence", "status"]) == 0
        assert "Cli Customer" in capsys.readouterr().out
        assert cli.main(["licence", "instance-id"]) == 0
    finally:
        os.environ["ZIIRA_LICENCE_PUBLIC_KEY"] = vendor["public"]
        get_settings.cache_clear()


def test_the_licence_screen_data_is_only_for_self_hosted_and_the_subscription_screen_only_for_saas(client, registry, vendor) -> None:  # type: ignore[no-untyped-def]
    tid, login, code = business(registry, "Lic Modes")
    owner = sign_in(client, code, login).headers
    assert client.post(f"{API}/billing/change-request", headers=owner, json={"plan_code": "x"}).status_code == 409
    assert client.post(f"{API}/billing/cancel", headers=owner, json={}).status_code == 409
    os.environ["ZIIRA_DEPLOYMENT_MODE"] = "saas"
    get_settings.cache_clear()
    try:
        assert client.post(f"{API}/billing/licence", headers=owner, json={"file": "x" * 20}).status_code == 409
    finally:
        os.environ["ZIIRA_DEPLOYMENT_MODE"] = "selfhosted"
        get_settings.cache_clear()
