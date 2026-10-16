"""Operator console: platform staff manage units and businesses from the web (docs/security.md, "Operator console").

Covers: who can reach it (tenant tokens cannot; operator tokens cannot reach business data); install, upgrade and uninstall
with their refusals; the fresh second-factor rule; the audit trail (operator log and the business's own log); switching a
business's units with a reason; upgrading businesses; the health reading; and that no response carries a secret.
"""

import base64
import json
import os
import shutil
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from tests.operator_mode import operator_mode
from tests.test_support_access import API, code_for, give_access, new_operator, open_session, operator_token, owner_of
from ziira.kernel import mfa
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session

_second_factor = operator_mode("totp")        # these tests are about the authenticator-app sign-in

PLUGIN = "scratchop"


def write_plugin(root: Path, version: str, migrations: dict[str, str]) -> None:
    folder = root / PLUGIN
    shutil.rmtree(folder / "migrations", ignore_errors=True)
    (folder / "migrations").mkdir(parents=True, exist_ok=True)
    (folder / "manifest.toml").write_text(textwrap.dedent(f"""\
        [unit]
        name = "{PLUGIN}"
        title = "Scratch plugin"
        description = "Used by the operator console tests only."
        category = "example"
        kind = "plugin"
        version = "{version}"
        sdk = ">=1.0,<2.0"
        requires = ["products"]
        """))
    for name, sql in migrations.items():
        (folder / "migrations" / name).write_text(sql)


FIRST = {"0001_init.up.sql": "create schema if not exists plg_scratchop;\ncreate table plg_scratchop.note (id int);\n",
         "0001_init.down.sql": "drop schema if exists plg_scratchop cascade;\n"}
SECOND = {**FIRST, "0002_more.up.sql": "alter table plg_scratchop.note add column body text;\n"}


@pytest.fixture(scope="module")
def scratch(registry, tmp_path_factory):  # type: ignore[no-untyped-def]
    """A throwaway plugin in an extra folder, loaded for this module only."""
    root = tmp_path_factory.mktemp("extra-plugins")
    write_plugin(root, "1.0.0", FIRST)
    os.environ["ZIIRA_EXTRA_UNIT_PATHS"] = str(root)
    get_settings.cache_clear()
    yield root
    os.environ.pop("ZIIRA_EXTRA_UNIT_PATHS", None)
    get_settings.cache_clear()
    with master_session() as m:
        m.execute(text("delete from master.unit where name = :n"), {"n": PLUGIN})


@pytest.fixture(scope="module")
def staff(client, scratch):  # type: ignore[no-untyped-def]
    """A signed-in operator, plus the secret to produce fresh codes."""
    email, secret = new_operator()
    return {"email": email, "secret": secret, "headers": operator_token(client, email, secret)}


@pytest.fixture(scope="module")
def shops(registry, scratch):  # type: ignore[no-untyped-def]
    a, b = make_tenant("Console A"), make_tenant("Console B")
    registry.enable(a["tenant_id"], "products")
    return {"A": a, "B": b}


def confirm(client, staff, code: str | None = None):  # type: ignore[no-untyped-def]
    """Send a fresh code to /operator/mfa/confirm (a time step nobody has used)."""
    value, moment = code_for(staff["secret"])
    with patch.object(mfa, "_now", lambda: moment):
        return client.post(f"{API}/operator/mfa/confirm", headers=staff["headers"], json={"code": code or value})


def age_confirmation(staff, minutes: int) -> None:
    with master_session() as m:
        m.execute(text("update master.operator_session set mfa_verified_at = now() - make_interval(mins => :n) "
                       "where operator_id = (select id from master.operator where lower(email) = :e)"),
                  {"n": minutes, "e": staff["email"]})


def trail(action: str | None = None) -> list[dict]:  # type: ignore[type-arg]
    with master_session() as m:
        rows = m.execute(text("select action, target, outcome, reason, detail from master.operator_action_log "
                              "where (cast(:a as text) is null or action = :a) order by id"), {"a": action})
        return [dict(r._mapping) for r in rows]


def unit_row(client, staff, name: str) -> dict:  # type: ignore[type-arg]
    r = client.get(f"{API}/operator/units", headers=staff["headers"])
    assert r.status_code == 200, r.text
    return next(u for u in r.json() if u["name"] == name)


# --------------------------------------------------------------------------- who can reach it
def test_only_operators_reach_the_console(client, shops, staff) -> None:  # type: ignore[no-untyped-def]
    owner = owner_of(client, "console-a")
    paths = ["/operator/units", "/operator/units/products/plan?action=install", "/operator/businesses/overview",
             "/operator/businesses/console-a", "/operator/health", "/operator/operators", "/operator/actions",
             "/operator/me"]
    for path in paths:
        assert client.get(API + path).status_code == 401, path                                   # nobody
        assert client.get(API + path, headers=owner.headers).status_code == 401, path            # a business owner
    for path, body in [("/operator/units/products/install", None), ("/operator/mfa/confirm", {"code": "123456"}),
                       ("/operator/businesses/upgrade", {}),
                       ("/operator/businesses/console-a/units/products/disable", {"reason": "testing it"})]:
        assert client.post(API + path, headers=owner.headers, json=body).status_code == 401, path


def test_an_operator_token_does_not_open_business_data(client, shops, staff) -> None:  # type: ignore[no-untyped-def]
    for path in ["/auth/me", "/units/catalog", "/users", "/settings/security", "/products/products"]:
        r = client.get(API + path, headers={**staff["headers"], "X-Tenant-ID": str(shops["A"]["tenant_id"])})
        assert r.status_code in (401, 403), (path, r.status_code)


# --------------------------------------------------------------------------- the list of units
def test_units_are_listed_with_their_state(client, staff, shops) -> None:  # type: ignore[no-untyped-def]
    kernel = unit_row(client, staff, "kernel")
    assert kernel["kind"] == "kernel" and kernel["status"] == "installed" and kernel["required_by"] == []
    products = unit_row(client, staff, "products")
    assert products["kind"] == "module" and products["status"] == "installed"
    assert products["businesses_enabled"] >= 1 and products["businesses_holding"] >= products["businesses_enabled"]
    assert PLUGIN not in products["required_by"] and products["required_by"]          # installed units that need it
    extra = unit_row(client, staff, PLUGIN)
    assert extra["status"] == "available" and extra["source"] == "extra folder" and extra["version_installed"] is None
    assert extra["requires"] == ["products"] and extra["version_on_disk"] == "1.0.0"


# --------------------------------------------------------------------------- install, upgrade, uninstall
def test_install_upgrade_uninstall_a_plugin(client, staff, shops, scratch) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    plan = client.get(f"{API}/operator/units/{PLUGIN}/plan", params={"action": "install"}, headers=h).json()
    assert plan["blocked"] == [] and [u["name"] for u in plan["will_install"]] == [PLUGIN]       # products is there
    assert client.get(f"{API}/operator/units/{PLUGIN}/plan", params={"action": "upgrade"}, headers=h) \
        .json()["blocked"] == ["It is not installed: use Install."]

    done = client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h)
    assert done.status_code == 200 and done.json()["installed"] == [PLUGIN]
    assert unit_row(client, staff, PLUGIN)["status"] == "installed"
    assert trail("unit.install")[-1] == {"action": "unit.install", "target": PLUGIN, "outcome": "ok", "reason": None,
                                         "detail": {"installed": [PLUGIN]}}
    assert client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h).status_code == 409       # already there
    assert client.post(f"{API}/operator/units/{PLUGIN}/upgrade", headers=h).status_code == 409       # nothing to do

    # A business switches it on, then the code on disk moves on: the unit needs an upgrade.
    on = client.post(f"{API}/operator/businesses/console-a/units/{PLUGIN}/enable", headers=h,
                     json={"reason": "Pilot of the scratch plugin"})
    assert on.status_code == 200 and on.json()["enabled"] is True
    write_plugin(scratch, "1.1.0", SECOND)
    row = unit_row(client, staff, PLUGIN)
    assert row["status"] == "needs_upgrade" and row["version_installed"] == "1.0.0" and row["businesses_behind"] == 1
    plan = client.get(f"{API}/operator/units/{PLUGIN}/plan", params={"action": "upgrade"}, headers=h).json()
    assert plan["blocked"] == [] and plan["upgrades"] == [{
        "name": PLUGIN, "title": "Scratch plugin", "from_version": "1.0.0", "to_version": "1.1.0",
        "businesses": [{"code": "console-a", "migrations": ["0002_more.up.sql"]}]}]
    health = client.get(f"{API}/operator/health", headers=h).json()
    assert {b["code"]: b["behind"] for b in health["businesses_behind"]}["console-a"] == {PLUGIN: ["0002_more.up.sql"]}

    # Uninstalling is refused while a business has it: both when it is on and when it only holds the data.
    refused = client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h, json={"confirm": PLUGIN})
    assert refused.status_code == 409 and refused.json()["holders"] == [
        {"code": "console-a", "name": "Console A", "enabled": True}]
    assert trail("unit.uninstall")[-1]["outcome"] == "refused"

    up = client.post(f"{API}/operator/units/{PLUGIN}/upgrade", headers=h)
    assert up.status_code == 200 and up.json()["upgraded"] == [
        {"name": PLUGIN, "from": "1.0.0", "to": "1.1.0", "businesses": 1}]
    with tenant_session(shops["A"]["tenant_id"], admin=True) as s:        # the migration really ran
        assert s.execute(text("select count(*) from information_schema.columns where table_schema = 'plg_scratchop' "
                              "and column_name = 'body'")).scalar() == 1
    assert unit_row(client, staff, PLUGIN)["status"] == "installed"
    assert client.get(f"{API}/operator/health", headers=h).json()["businesses_behind"] == []

    off = client.post(f"{API}/operator/businesses/console-a/units/{PLUGIN}/disable", headers=h,
                      json={"reason": "Pilot ended"})
    assert off.status_code == 200
    still = client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h, json={"confirm": PLUGIN})
    assert still.status_code == 409 and still.json()["holders"][0]["enabled"] is False     # the data is still there
    from ziira.kernel.registry import Registry, discover
    Registry(discover()).remove_from_tenant(shops["A"]["tenant_id"], PLUGIN)               # the business's data goes

    assert client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h, json={"confirm": "wrong"}).status_code == 422
    gone = client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h, json={"confirm": PLUGIN})
    assert gone.status_code == 200 and gone.json()["uninstalled"] == PLUGIN
    assert unit_row(client, staff, PLUGIN)["status"] == "available"
    assert [t["outcome"] for t in trail("unit.uninstall")][-1] == "ok"
    write_plugin(scratch, "1.0.0", FIRST)


def test_uninstall_refusals(client, staff, shops) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    kernel = client.post(f"{API}/operator/units/kernel/uninstall", headers=h, json={"confirm": "kernel"})
    assert kernel.status_code == 409 and "kernel" in kernel.json()["message"].lower()
    products = client.post(f"{API}/operator/units/products/uninstall", headers=h, json={"confirm": "products"})
    assert products.status_code == 409 and products.json()["dependants"]                 # other units need it
    assert client.post(f"{API}/operator/units/nothing-here/uninstall", headers=h,
                       json={"confirm": "nothing-here"}).status_code == 404
    assert client.get(f"{API}/operator/units/products/plan", params={"action": "bogus"}, headers=h).status_code == 422


# --------------------------------------------------------------------------- a fresh second factor
def test_changes_need_a_recent_second_factor(client, staff, shops, scratch) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    me = client.get(f"{API}/operator/me", headers=h).json()
    assert me["step_up_needed"] is False and me["mfa_max_age_minutes"] == 10

    age_confirmation(staff, 11)
    assert client.get(f"{API}/operator/me", headers=h).json()["step_up_needed"] is True
    stale = client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h)
    assert stale.status_code == 403 and stale.json()["error"] == "mfa_step_up_required"
    assert unit_row(client, staff, PLUGIN)["status"] == "available"                       # nothing was done
    line = trail("unit.install")[-1]
    assert line["outcome"] == "refused" and "second factor" in line["detail"]["why"]
    assert client.get(f"{API}/operator/units", headers=h).status_code == 200            # reading never asks

    assert confirm(client, staff, "000000").status_code == 401                            # a wrong code confirms nothing
    assert client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h).status_code == 403
    ok = confirm(client, staff)
    assert ok.status_code == 200 and ok.json()["valid_minutes"] == 10
    assert client.get(f"{API}/operator/me", headers=h).json()["step_up_needed"] is False
    assert client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h).status_code == 200
    h2 = {"Authorization": h["Authorization"]}
    assert client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h2, json={"confirm": PLUGIN}).status_code == 200


# --------------------------------------------------------------------------- businesses
def test_businesses_overview_and_detail(client, staff, shops) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    rows = client.get(f"{API}/operator/businesses/overview", headers=h).json()
    mine = {r["code"]: r for r in rows}
    assert {"console-a", "console-b"} <= set(mine)
    a = mine["console-a"]
    assert a["name"] == "Console A" and a["status"] == "active" and a["users"] == 1 and "products" in a["enabled_units"]
    assert a["country"] is None or len(a["country"]) == 2
    assert [r["code"] for r in client.get(f"{API}/operator/businesses/overview", params={"search": "console-b"},
                                          headers=h).json()] == ["console-b"]
    assert client.get(f"{API}/operator/businesses/overview", params={"search": "Console"}, headers=h) \
        .json().__len__() >= 2

    detail = client.get(f"{API}/operator/businesses/console-a", headers=h).json()
    products = next(u for u in detail["units"] if u["name"] == "products")
    assert products["enabled"] is True and detail["grants"] == [] and detail["sessions"] == []
    assert client.get(f"{API}/operator/businesses/no-such-shop", headers=h).status_code == 404


def test_support_entry_follows_the_business_grant(client, staff, shops) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    assert open_session(client, h, "console-b").status_code == 403           # no grant: no way in, however you ask
    owner = owner_of(client, "console-b")
    grant = give_access(client, owner, "read")
    detail = client.get(f"{API}/operator/businesses/console-b", headers=h).json()
    assert [g["id"] for g in detail["grants"]] == [grant["id"]] and detail["grants"][0]["level"] == "read"
    opened = open_session(client, h, "console-b")
    assert opened.status_code == 201
    detail = client.get(f"{API}/operator/businesses/console-b", headers=h).json()
    assert len(detail["sessions"]) == 1 and detail["sessions"][0]["mine"] is True
    assert "operator_id" not in detail["sessions"][0]
    sid = detail["sessions"][0]["id"]
    assert client.post(f"{API}/operator/sessions/{sid}/end", headers=h).status_code == 204
    assert client.get(f"{API}/operator/businesses/console-b", headers=h).json()["sessions"] == []


def test_switching_a_business_unit_needs_a_reason_and_is_logged_twice(client, staff, shops) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    url = f"{API}/operator/businesses/console-b/units"
    assert client.post(f"{url}/pos/enable", headers=h, json={"reason": ""}).status_code == 422
    assert client.post(f"{url}/pos/enable", headers=h, json={"reason": "  hi "}).status_code == 422
    assert client.post(f"{url}/pos/enable", headers=h, json={}).status_code == 422
    assert "pos" not in next(r for r in client.get(f"{API}/operator/businesses/overview", headers=h).json()
                             if r["code"] == "console-b")["enabled_units"]

    on = client.post(f"{url}/pos/enable", headers=h, json={"reason": "Opening their first till"})
    assert on.status_code == 200 and "pos" in on.json()["also_enabled"]
    row = next(r for r in client.get(f"{API}/operator/businesses/overview", headers=h).json() if r["code"] == "console-b")
    assert "pos" in row["enabled_units"]
    line = [t for t in trail("business.unit_enable") if t["target"] == "console-b:pos"][-1]
    assert line["reason"] == "Opening their first till" and line["outcome"] == "ok"
    with tenant_session(shops["B"]["tenant_id"]) as s:                       # the business's own log names the operator
        entry = s.execute(text("select channel, changes from kernel.audit_log where action = 'operator_unit_change' "
                               "order by id desc limit 1")).one()
    assert entry.channel == "support" and entry.changes["reason"] == "Opening their first till"
    assert entry.changes["support_operator"] == "Sam Support" and entry.changes["enabled"] is True

    # Switching off something others need is refused and recorded as refused.
    blocked = client.post(f"{url}/products/disable", headers=h, json={"reason": "Trying to remove products"})
    assert blocked.status_code == 409
    assert trail("business.unit_disable")[-1]["outcome"] == "refused"
    off = client.post(f"{url}/pos/disable", headers=h, json={"reason": "Till not needed after all"})
    assert off.status_code == 200
    assert client.post(f"{API}/operator/businesses/nope/units/pos/enable", headers=h,
                       json={"reason": "nothing there"}).status_code == 404


def test_upgrading_businesses_reports_each_one(client, staff, shops, scratch) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    assert client.post(f"{API}/operator/units/{PLUGIN}/install", headers=h).status_code == 200
    assert client.post(f"{API}/operator/businesses/console-a/units/{PLUGIN}/enable", headers=h,
                       json={"reason": "Pilot of the scratch plugin"}).status_code == 200
    assert client.post(f"{API}/operator/businesses/upgrade", headers=h, json={}).json() == []     # nobody is behind
    write_plugin(scratch, "1.2.0", {**SECOND, "0003_more.up.sql": "alter table plg_scratchop.note add column n2 int;\n"})
    results = client.post(f"{API}/operator/businesses/upgrade", headers=h, json={}).json()
    assert results == [{"code": "console-a", "name": "Console A", "ok": True, "error": None,
                        "applied": {PLUGIN: ["0002_more.up.sql", "0003_more.up.sql"]}}]
    assert client.post(f"{API}/operator/businesses/upgrade", headers=h, json={"codes": ["console-a"]}).json()[0]["applied"] == {}
    assert client.post(f"{API}/operator/businesses/upgrade", headers=h, json={"codes": ["ghost"]}).status_code == 404
    assert any(t["detail"] and t["detail"].get("results") for t in trail("business.upgrade.results"))
    # tidy up the platform for the other tests
    from ziira.kernel.registry import Registry, discover
    client.post(f"{API}/operator/businesses/console-a/units/{PLUGIN}/disable", headers=h, json={"reason": "Pilot ended"})
    Registry(discover()).remove_from_tenant(shops["A"]["tenant_id"], PLUGIN)
    assert client.post(f"{API}/operator/units/{PLUGIN}/uninstall", headers=h, json={"confirm": PLUGIN}).status_code == 200


# --------------------------------------------------------------------------- health, operators, secrets
def test_health_operators_and_no_secrets(client, staff, shops, tmp_path) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    health = client.get(f"{API}/operator/health", headers=h)
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["businesses_total"] >= 2 and body["master_migrations_pending"] == []
    assert body["backups"] == {"reported": False, "master_taken_at": None, "master_age_hours": None,
                               "tenants_without_backup": []}
    assert body["queues"] is not None and body["queues"]["jobs_failed"] >= 0
    assert body["registrations"]["pending"] >= 0
    assert body["plugins"]["loaded"] == [] or body["plugins"]["loaded"][0]["name"] == PLUGIN

    folder = tmp_path / "backups"
    (folder / "master").mkdir(parents=True)
    (folder / "master" / "master-1.json").write_text(json.dumps({"taken_at": "2026-01-01T00:00:00+00:00",
                                                                 "file": "master-1.dump"}))
    os.environ["ZIIRA_BACKUP_DIR"] = str(folder)
    get_settings.cache_clear()
    try:
        backups = client.get(f"{API}/operator/health", headers=h).json()["backups"]
    finally:
        os.environ.pop("ZIIRA_BACKUP_DIR", None)
        get_settings.cache_clear()
    assert backups["reported"] is True and backups["master_taken_at"].startswith("2026-01-01")
    assert backups["master_age_hours"] > 24 and "console-a" in backups["tenants_without_backup"]

    ops = client.get(f"{API}/operator/operators", headers=h).json()
    me = next(o for o in ops if o["email"] == staff["email"])
    assert me["status"] == "active" and me["mfa_enrolled"] is True and me["open_sessions"] >= 1

    everything = "".join(client.get(f"{API}{p}", headers=h).text for p in [
        "/operator/units", "/operator/health", "/operator/operators", "/operator/actions", "/operator/me",
        "/operator/businesses/overview", "/operator/businesses/console-a", "/operator/units/products/plan?action=uninstall"])
    secret = base64.b32decode(staff["secret"] + "=" * (-len(staff["secret"]) % 8)).hex()
    for forbidden in ("postgresql", "password_hash", "mfa_secret", "app_url", "admin_url", "ztest_", staff["secret"],
                      secret, get_settings().secret_key):
        assert forbidden not in everything, forbidden
    assert "Sam Support" in client.get(f"{API}/operator/actions", headers=h).text


def test_the_action_trail_cannot_be_edited(staff, client) -> None:  # type: ignore[no-untyped-def]
    assert trail()                      # earlier tests left lines
    with pytest.raises(Exception, match="cannot be changed"), master_session() as m:
        m.execute(text("update master.operator_action_log set outcome = 'ok'"))
    with pytest.raises(Exception, match="cannot be changed"), master_session() as m:
        m.execute(text("delete from master.operator_action_log"))
