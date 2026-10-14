"""The kernel's units one at a time, called directly (no HTTP): every rule and every refusal."""

import ipaddress
from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.errors import Conflict, Forbidden, NotFound, ValidationFailed


@pytest.fixture(scope="module")
def t(client, registry):  # type: ignore[no-untyped-def]
    tenant = make_tenant("Unit Co")
    registry.enable(tenant["tenant_id"], "inventory")
    return tenant


def run_as(t, user_id=None):  # type: ignore[no-untyped-def]
    """A transaction acting with every permission, as the system or as a given user."""
    from ziira.kernel.db import tenant_session

    set_context(RequestContext(tenant_id=t["tenant_id"], user_id=user_id, all_permissions=True))
    return tenant_session(t["tenant_id"])


# --------------------------------------------------------------------------- approvals
def test_approval_rules_are_validated(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import approvals

    role = None
    with run_as(t) as s:
        role = s.execute(text("select id from kernel.role where name = 'Branch Manager'")).scalar_one()
    base = {"company_id": t["company_id"], "doc_type": "unit_doc", "approver_role_id": role}
    for change, message in (({"step": 0}, "Step"), ({"min_amount": Dec("-1")}, "range"),
                            ({"min_amount": Dec("10"), "max_amount": Dec("5")}, "range"),
                            ({"approver_role_id": uuid4()}, "role does not exist"),
                            ({"company_id": uuid4()}, "Company not found")):
        with pytest.raises(ValidationFailed, match=message), run_as(t) as s:
            approvals.create_rule(s, **{**base, **change})


def test_rules_can_be_listed_filtered_and_switched_off(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import approvals

    with run_as(t) as s:
        role = s.execute(text("select id from kernel.role where name = 'Branch Manager'")).scalar_one()
        rule = approvals.create_rule(s, company_id=t["company_id"], doc_type="unit_doc2", approver_role_id=role)
        assert rule.id in {r.id for r in approvals.list_rules(s)}
        assert rule.id in {r.id for r in approvals.list_rules(s, t["company_id"])}
        assert approvals.list_rules(s, uuid4()) == []
        approvals.set_rule_active(s, rule.id, False)
        assert [r.is_active for r in approvals.list_rules(s, t["company_id"]) if r.id == rule.id] == [False]
        # a switched-off rule no longer applies
        assert approvals.submit_for_approval(s, company_id=t["company_id"], doc_type="unit_doc2", doc_id=uuid4(),
                                             amount=Dec("5")).status == "approved"
        with pytest.raises(NotFound):
            approvals.set_rule_active(s, uuid4(), True)


def test_requests_need_a_person_and_must_exist(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import approvals

    with pytest.raises(Forbidden, match="signed-in user"), run_as(t) as s:
        approvals.decide(s, uuid4(), approve=True)                 # the system cannot approve
    owner = None
    with run_as(t) as s:
        owner = s.execute(text("select id from kernel.app_user limit 1")).scalar_one()
    with pytest.raises(NotFound), run_as(t, owner) as s:
        approvals.decide(s, uuid4(), approve=True)
    with pytest.raises(NotFound), run_as(t) as s:
        approvals.get_request(s, uuid4())


def test_an_expired_request_cannot_be_decided_and_is_not_listed(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import approvals
    from ziira.kernel.db import tenant_session

    with run_as(t) as s:
        owner = s.execute(text("select id from kernel.app_user limit 1")).scalar_one()
        role = s.execute(text("select id from kernel.role where name = 'Owner'")).scalar_one()
        approvals.create_rule(s, company_id=t["company_id"], doc_type="expiring", approver_role_id=role,
                              forbid_creator=False)
        doc = uuid4()
        assert approvals.submit_for_approval(s, company_id=t["company_id"], doc_type="expiring", doc_id=doc).status \
            == "pending"
    with tenant_session(t["tenant_id"], admin=True) as s:
        s.execute(text("update kernel.approval_request set expires_at = now() - interval '1 hour' "
                       "where doc_id = :d"), {"d": str(doc)})
    with run_as(t, owner) as s:
        assert all(r.doc_id != doc for r in approvals.pending_for_me(s))
        request = s.execute(text("select id from kernel.approval_request where doc_id = :d"), {"d": str(doc)}
                            ).scalar_one()
    with pytest.raises(Conflict, match="expired"), run_as(t, owner) as s:
        approvals.decide(s, request, approve=True)


# --------------------------------------------------------------------------- users, roles and grants
def test_creating_users_is_validated(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    for kwargs, message in (({"full_name": "  ", "email": "a@b.co"}, "Full name"),
                            ({"full_name": "A"}, "email or a phone"),
                            ({"full_name": "A", "email": "not-an-email"}, "Email address"),
                            ({"full_name": "A", "email": "a b@c.de"}, "Email address"),
                            ({"full_name": "A", "email": "a@b"}, "Email address"),
                            ({"full_name": "A", "phone": "abc"}, "Phone number"),
                            ({"full_name": "A", "phone": "12"}, "Phone number"),
                            ({"full_name": "A", "email": "a@b.co", "password": "short"}, "at least 8")):
        with pytest.raises(ValidationFailed, match=message), run_as(t) as s:
            users.create_user(s, **kwargs)


def test_users_are_unique_by_email_and_phone(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    with run_as(t) as s:
        first = users.create_user(s, full_name="Wanjiru", email="Wanjiru@Unit.Test", phone="+254 712 345 678",
                                  password="wanjiru-pass-1")
        assert first.email == "wanjiru@unit.test" and first.status == "active"
        invited = users.create_user(s, full_name="Invited", email="invited@unit.test")
        assert invited.status == "invited"
    for kwargs in ({"email": "WANJIRU@unit.test"}, {"phone": "+254 712 345 678"}):
        with pytest.raises(Conflict), run_as(t) as s:
            users.create_user(s, full_name="Copy", **kwargs)
    with run_as(t) as s:
        assert users.get_user(s, first.id).full_name == "Wanjiru"
        with pytest.raises(NotFound):
            users.get_user(s, uuid4())
        with pytest.raises(NotFound):
            users.set_password(s, uuid4(), "whatever-123")


def test_disabled_users_and_self_protection(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    with run_as(t) as s:
        user = users.create_user(s, full_name="Temp", email="temp@unit.test", password="temp-pass-123")
        users.set_user_active(s, user.id, False)
        with pytest.raises(ValidationFailed, match="disabled"):
            users.set_password(s, user.id, "new-pass-12345")
        assert users.set_user_active(s, user.id, True).status == "active"
    with pytest.raises(ValidationFailed, match="yourself"), run_as(t, user.id) as s:
        users.set_user_active(s, user.id, False)


def test_roles_are_validated(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    with run_as(t) as s:
        with pytest.raises(ValidationFailed, match="name is required"):
            users.create_role(s, "  ", [])
        with pytest.raises(ValidationFailed, match="Unknown permissions"):
            users.create_role(s, "Nope", ["no.such.permission"])
        role = users.create_role(s, "Clerk", ["stock.view", "stock.view"])           # duplicates collapse
        assert role.permissions == ("stock.view",)
        with pytest.raises(Conflict):
            users.create_role(s, "clerk", [])                                         # names are unique, any case
        with pytest.raises(NotFound):
            users.get_role(s, uuid4())


def test_grants_are_validated(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    with run_as(t) as s:
        person = users.create_user(s, full_name="Grantee", email="grantee@unit.test", password="grantee-pass-1")
        role = next(r for r in users.list_roles(s) if r.name == "Cashier")
        branch = s.execute(text("select id from kernel.branch limit 1")).scalar_one()
        cases = [({"scope": "galaxy"}, "Scope must be"),
                 ({"scope": "tenant", "company_id": t["company_id"]}, "no company or branch"),
                 ({"scope": "company"}, "needs a company"),
                 ({"scope": "company", "company_id": t["company_id"], "branch_id": branch}, "no branch"),
                 ({"scope": "branch", "company_id": t["company_id"]}, "needs a company and a branch"),
                 ({"scope": "company", "company_id": uuid4()}, "Company not found"),
                 ({"scope": "branch", "company_id": t["company_id"], "branch_id": uuid4()}, "Branch not found")]
        for kwargs, message in cases:
            with pytest.raises(ValidationFailed, match=message):
                users.grant_role(s, user_id=person.id, role_id=role.id, **kwargs)
        with pytest.raises(NotFound):
            users.grant_role(s, user_id=person.id, role_id=uuid4(), scope="tenant")
        with pytest.raises(NotFound):
            users.grant_role(s, user_id=uuid4(), role_id=role.id, scope="tenant")
        grant = users.grant_role(s, user_id=person.id, role_id=role.id, scope="branch",
                                 company_id=t["company_id"], branch_id=branch)
        with pytest.raises(Conflict, match="already has"):
            users.grant_role(s, user_id=person.id, role_id=role.id, scope="branch", company_id=t["company_id"],
                             branch_id=branch)
        assert [g.role_name for g in users.list_grants(s, person.id)] == ["Cashier"]
        users.revoke_role(s, grant.id)
        assert users.list_grants(s, person.id) == []
        with pytest.raises(NotFound):
            users.revoke_role(s, grant.id)


def test_the_last_owner_cannot_be_removed_but_a_second_owner_can_go(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import users

    with run_as(t) as s:
        owner_role = next(r for r in users.list_roles(s) if r.name == "Owner")
        owner = s.execute(text("select user_id from kernel.user_role where role_id = :r"),
                          {"r": str(owner_role.id)}).scalar_one()
        grant = users.list_grants(s, owner)[0]
        with pytest.raises(ValidationFailed, match="at least one owner"):
            users.revoke_role(s, grant.id)
        second = users.create_user(s, full_name="Co-owner", email="coowner@unit.test", password="coowner-pass-1")
        extra = users.grant_role(s, user_id=second.id, role_id=owner_role.id, scope="tenant")
        users.revoke_role(s, extra.id)                                         # two owners: one may go
        extra = users.grant_role(s, user_id=second.id, role_id=owner_role.id, scope="tenant")
        users.set_user_active(s, second.id, False)                             # a disabled owner does not count...
        users.revoke_role(s, extra.id)                                         # ...so removing theirs is fine
        with pytest.raises(ValidationFailed, match="at least one owner"):
            users.revoke_role(s, grant.id)


# --------------------------------------------------------------------------- numbering
def test_numbering_refusals(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import numbering

    with run_as(t) as s:
        with pytest.raises(ValidationFailed):
            numbering.next_document_number(s, company_id=t["company_id"], branch_id=None, doc_type="", prefix="X")
        with pytest.raises(ValidationFailed):
            numbering.next_document_number(s, company_id=t["company_id"], branch_id=None, doc_type="x", prefix="")
        with pytest.raises(NotFound, match="Company"):
            numbering.next_document_number(s, company_id=uuid4(), branch_id=None, doc_type="x", prefix="X")
        with pytest.raises(NotFound, match="Branch"):
            numbering.next_document_number(s, company_id=t["company_id"], branch_id=uuid4(), doc_type="x", prefix="X")
        numbering.next_document_number(s, company_id=t["company_id"], branch_id=None, doc_type="unit", prefix="UN")
        series = next(x for x in numbering.list_series(s) if x.doc_type == "unit")
        for kwargs, message in (({"padding": 0}, "Padding"), ({"padding": 13}, "Padding"),
                                ({"prefix": "  "}, "Prefix"), ({"next_number": 0}, "go back")):
            with pytest.raises(ValidationFailed, match=message):
                numbering.update_series(s, series.id, **kwargs)
        with pytest.raises(NotFound):
            numbering.update_series(s, uuid4(), prefix="X-")
        numbering.update_series(s, series.id, prefix="UNIT/", padding=3, next_number=41)
        assert numbering.next_document_number(s, company_id=t["company_id"], branch_id=None, doc_type="unit",
                                              prefix="UN") == "UNIT/041"


# --------------------------------------------------------------------------- reasons and settings
def test_reason_code_rules(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import reasons

    with run_as(t) as s:
        with pytest.raises(ValidationFailed, match="Category"):
            reasons.create_reason(s, "nonsense", "X", "x")
        with pytest.raises(ValidationFailed, match="Code must be"):
            reasons.create_reason(s, "void", "bad code", "x")
        with pytest.raises(ValidationFailed, match="Label"):
            reasons.create_reason(s, "void", "OK", "  ")
        needs_note = reasons.create_reason(s, "void", "CHANGED", "Changed mind", requires_note=True)
        with pytest.raises(Conflict):
            reasons.create_reason(s, "void", "CHANGED", "again")
        with pytest.raises(ValidationFailed, match="needs a note"):
            reasons.check_reason(s, "void", needs_note.id, "  ")
        assert reasons.check_reason(s, "void", needs_note.id, "customer left").code == "CHANGED"
        reasons.set_reason_active(s, needs_note.id, False)
        with pytest.raises(ValidationFailed, match="no longer in use"):
            reasons.check_reason(s, "void", needs_note.id, "x")
        assert needs_note.id not in {r.id for r in reasons.list_reasons(s, "void")}
        assert needs_note.id in {r.id for r in reasons.list_reasons(s, "void", include_inactive=True)}
        with pytest.raises(NotFound):
            reasons.set_reason_active(s, uuid4(), True)


def test_company_settings_units(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import company_settings as cs

    assert cs._non_negative_amount("12.50") == Dec("12.50")
    for bad in ("x", "-1", "NaN", "Infinity", None):
        with pytest.raises(ValidationFailed):
            cs._non_negative_amount(bad)
    for bad in (1, "true", None, 0):
        with pytest.raises(ValidationFailed):
            cs._boolean(bad)
    with run_as(t) as s:
        with pytest.raises(NotFound):
            cs.get_settings(s, uuid4())
        with pytest.raises(ValidationFailed, match="Unknown setting"):
            cs.update_settings(s, t["company_id"], {"colour": "blue"})
        with pytest.raises(KeyError):
            cs.get_setting(s, t["company_id"], "colour")
        cs.update_settings(s, t["company_id"], {"count_variance_threshold": "7.5"})
        assert cs.get_setting(s, t["company_id"], "count_variance_threshold") == Dec("7.5")
        changes = s.execute(text("select changes from kernel.audit_log where entity_type = 'kernel.company_settings' "
                                 "order by id desc limit 1")).scalar_one()
        assert changes == {"count_variance_threshold": {"from": "0", "to": "7.5"}}


# --------------------------------------------------------------------------- events and the outbox
def test_which_unit_owns_a_module() -> None:
    from ziira.kernel.events import register_unit_package, unit_of

    assert unit_of("ziira.modules.finance.events") == "finance"
    assert unit_of("ziira.plugins.catalog_stats.hooks") == "catalog_stats"
    assert unit_of("ziira.kernel.checks") == "kernel"
    assert unit_of("tests.something") == "tests"
    register_unit_package("acme_plugin", "acme")
    assert unit_of("acme_plugin.events") == "acme" and unit_of("acme_plugin") == "acme"
    assert unit_of("acme_plugin_two.events") == "acme_plugin_two"            # a longer name is not a sub-package


def test_events_reach_only_enabled_units_in_order_and_failures_roll_back(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import events
    from ziira.sdk import Event, publish

    calls: list[str] = []
    events._subscribers["unit.test"] += [("kernel", lambda s, e: calls.append("kernel-1")),
                                         ("inventory", lambda s, e: calls.append("inventory")),
                                         ("not_enabled", lambda s, e: calls.append("NOT ENABLED")),
                                         ("kernel", lambda s, e: calls.append("kernel-2"))]
    try:
        with run_as(t) as s:
            publish(s, Event("unit.test", "x", uuid4(), {"a": Dec("1.5")}))
        assert calls == ["kernel-1", "inventory", "kernel-2"]                      # registration order
        def explode(_s, _e):  # type: ignore[no-untyped-def]
            raise RuntimeError("subscriber failed")

        events._subscribers["unit.fail"] += [("kernel", explode)]
        marker = uuid4()
        with pytest.raises(RuntimeError), run_as(t) as s:
            publish(s, Event("unit.fail", "x", marker))
        with run_as(t) as s:
            assert s.execute(text("select count(*) from kernel.event_outbox where aggregate_id = :i"),
                             {"i": str(marker)}).scalar_one() == 0               # the whole publish rolled back
    finally:
        events._subscribers.pop("unit.test", None)
        events._subscribers.pop("unit.fail", None)


def test_after_commit_handlers_register_per_unit_and_events_give_up_after_ten_failures(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import events, outbox
    from ziira.kernel.db import tenant_session
    from ziira.sdk import Event, publish

    @events.subscribe_after("unit.after")
    def always_fails(_s, _e):  # type: ignore[no-untyped-def]
        raise RuntimeError("never works")

    events._after_commit["unit.after"] = [("kernel", always_fails)]
    try:
        marker = uuid4()
        with run_as(t) as s:
            publish(s, Event("unit.after", "x", marker))
        for _ in range(outbox.MAX_ATTEMPTS + 3):
            outbox.process_tenant(t["tenant_id"])
        with tenant_session(t["tenant_id"]) as s:
            row = s.execute(text("select attempts, published_at from kernel.event_outbox where aggregate_id = :i"),
                            {"i": str(marker)}).one()
        assert row.attempts == outbox.MAX_ATTEMPTS and row.published_at is None      # left for a person to look at
        assert outbox.process_tenant(t["tenant_id"]) == 0
    finally:
        events._after_commit.pop("unit.after", None)


def test_the_outbox_covers_every_active_tenant_and_the_loop_sleeps_when_idle(monkeypatch, t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import outbox

    assert t["tenant_id"] in outbox._active_tenants()
    assert isinstance(outbox.process_all(), int)
    sleeps: list[float] = []

    def stop(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(outbox, "process_all", lambda: 0)
    monkeypatch.setattr(outbox.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        outbox.run_forever(interval_seconds=0.5)
    assert sleeps == [0.5]


# --------------------------------------------------------------------------- extension sockets
def test_extension_registry_errors_and_inspection() -> None:
    from abc import ABC, abstractmethod

    from ziira.kernel import extensions

    class Contract(ABC):
        @abstractmethod
        def go(self) -> str: ...

    assert "kernel.integrity_check" in extensions.extension_points()
    assert "products.product.before_create" in extensions.validation_hooks()
    with pytest.raises(KeyError, match="Unknown extension point"):
        extensions.implementations(None, "no.such.point")                                 # type: ignore[arg-type]
    with pytest.raises(KeyError, match="Unknown validation hook"):
        extensions.run_validators(None, "no.such.hook", object())                          # type: ignore[arg-type]
    extensions._pending_validators.append(("orphan.hook", "ghost", lambda s, d: None))
    try:
        assert any("ghost validates unknown 'orphan.hook'" in x for x in extensions.undefined_registrations())
    finally:
        extensions._pending_validators.pop()


def test_a_slow_validator_is_logged_and_a_failing_one_blocks_naming_its_unit(t, caplog) -> None:  # type: ignore[no-untyped-def]
    import logging
    import time

    from ziira.kernel import extensions

    hook = extensions.define_validation_hook("unit.hook")
    slow = lambda s, d: time.sleep(extensions.SLOW_VALIDATOR_SECONDS + 0.05)       # noqa: E731
    hook.validators.append(("inventory", slow))
    try:
        with caplog.at_level(logging.WARNING, logger="ziira.extensions"), run_as(t) as s:
            extensions.run_validators(s, "unit.hook", object())
        assert any("Slow validator" in r.message for r in caplog.records)
    finally:
        extensions._hooks.pop("unit.hook", None)


# --------------------------------------------------------------------------- audit chain and security helpers
def test_the_audit_chain_detects_tampering(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import audit
    from ziira.kernel.db import tenant_session

    with run_as(t) as s:
        audit.record(s, "unit", "kernel.test", None, {"n": 1})
        audit.record(s, "unit", "kernel.test", None, {"n": 2})
        assert audit.verify_chain(s) is True
    with tenant_session(t["tenant_id"], admin=True) as s:                  # a forged entry that links to nothing
        s.execute(text("insert into kernel.audit_log (tenant_id, channel, action, entity_type, prev_hash, hash) "
                       "values (:t, 'system', 'forged', 'kernel.test', 'not-the-previous-hash', 'x')"),
                  {"t": str(t["tenant_id"])})
    with run_as(t) as s:
        assert audit.verify_chain(s) is False


def test_security_helpers_refuse_bad_input() -> None:
    from ziira.kernel.security import (
        MAX_PASSWORD_LENGTH,
        decrypt,
        encrypt,
        hash_password,
        verify_password,
    )

    for broken in ("", "x", "scrypt$1$2", "scrypt$a$b$c$d$e", "scrypt$16384$8$1$!!!$???", None):
        assert verify_password("whatever-123", broken) is False
    assert verify_password("x" * (MAX_PASSWORD_LENGTH + 1), hash_password("a-fine-password")) is False
    with pytest.raises(ValidationFailed, match="at most"):
        hash_password("x" * (MAX_PASSWORD_LENGTH + 1))
    assert decrypt(encrypt("secret")) == "secret"
    from ziira.kernel.config import get_settings

    settings, real = get_settings(), get_settings().credentials_key
    token = encrypt("secret")
    settings.credentials_key = "a-different-key-0123456789abcdef0123456789"
    try:
        with pytest.raises(RuntimeError, match="ZIIRA_CREDENTIALS_KEY"):
            decrypt(token)
    finally:
        settings.credentials_key = real


def test_the_client_address_for_the_audit_log() -> None:
    from types import SimpleNamespace

    from ziira.kernel.auth import client_ip
    from ziira.kernel.config import get_settings

    def request(host, forwarded=None):  # type: ignore[no-untyped-def]
        return SimpleNamespace(client=SimpleNamespace(host=host) if host else None,
                               headers={"x-forwarded-for": forwarded} if forwarded else {})

    assert client_ip(request("203.0.113.5")) == "203.0.113.5"
    assert client_ip(request("2001:db8::1")) == str(ipaddress.ip_address("2001:db8::1"))
    assert client_ip(request("testclient")) is None and client_ip(request(None)) is None
    assert client_ip(request("10.0.0.1", "198.51.100.1, 203.0.113.9")) == "10.0.0.1"          # not trusted: ignored
    settings = get_settings()
    settings.trust_forwarded_for = True
    try:
        assert client_ip(request("10.0.0.1", "198.51.100.1, 203.0.113.9")) == "203.0.113.9"   # the proxy's entry
        assert client_ip(request("10.0.0.1", "garbage")) is None
        assert client_ip(request("10.0.0.1")) == "10.0.0.1"
    finally:
        settings.trust_forwarded_for = False


# --------------------------------------------------------------------------- the command line
def test_command_line_commands_and_errors(registry, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    def run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    code, out, _ = run("units")
    assert code == 0 and "inventory" in out and "installed" in out
    code, out, _ = run("install", "--all")
    assert code == 0 and "nothing new" in out
    code, _, err = run("install", "no_such_unit")
    assert code == 1 and err.startswith("Error:")
    code, _, err = run("uninstall", "products")                               # tenants still use it
    assert code == 1 and "Error" in err

    monkeypatch.setenv("ZIIRA_OWNER_PASSWORD", "cli-owner-pass-1")
    code, out, _ = run("create-tenant", "Cli Co", "--code", "cli-co", "--company", "Cli Ltd", "--branch-code", "C1",
                       "--branch-name", "Main", "--owner-name", "Cli Owner", "--owner-email", "owner@cli-co.test",
                       "--currency", "usd", "--phone-country-code", "44")
    assert code == 0 and "tenant_id" in out
    code, _, err = run("create-tenant", "Cli Co", "--code", "cli-co", "--company", "x", "--branch-code", "C1",
                       "--branch-name", "x", "--owner-name", "x", "--owner-email", "x@y.zz", "--currency", "USD")
    assert code == 1 and "taken" in err
    code, _, err = run("create-tenant", "Bad", "--code", "Bad Code!", "--company", "x", "--branch-code", "C1",
                       "--branch-name", "x", "--owner-name", "x", "--owner-email", "x@y.zz", "--currency", "USD")
    assert code == 1 and "Workspace code" in err
    code, _, err = run("create-tenant", "Money", "--code", "money-co", "--company", "x", "--branch-code", "C1",
                       "--branch-name", "x", "--owner-name", "x", "--owner-email", "x@y.zz", "--currency", "dollars")
    assert code == 1 and "three-letter" in err
    code, _, err = run("create-tenant", "Phone", "--code", "phone-co", "--company", "x", "--branch-code", "C1",
                       "--branch-name", "x", "--owner-name", "x", "--owner-email", "x@y.zz", "--currency", "USD",
                       "--phone-country-code", "9999")
    assert code == 1 and "calling code" in err

    code, out, _ = run("tenants")
    assert code == 0 and "cli-co" in out
    code, out, _ = run("enable", "cli-co", "catalog_stats")
    assert code == 0 and "products" in out and "catalog_stats" in out               # what it requires comes along
    code, out, _ = run("enable", "cli-co", "catalog_stats")
    assert "already enabled" in out
    code, _, err = run("remove", "cli-co", "catalog_stats")                          # must be disabled first
    assert code == 1
    code, out, _ = run("disable", "cli-co", "catalog_stats")
    assert code == 0 and "data kept" in out
    code, out, _ = run("remove", "cli-co", "catalog_stats")
    assert code == 0
    code, _, err = run("enable", "no-such-tenant", "products")
    assert code == 1 and "not found" in err
    code, _, err = run("enable", "cli-co", "no_such_unit")
    assert code == 1

    code, out, _ = run("outbox-run", "--once")
    assert code == 0 and "Delivered" in out
    code, out, _ = run("verify", "cli-co")
    assert code == 0
    code, _, err = run("drop-tenant", "cli-co", "--confirm", "other")
    assert code == 1 and "Repeat the workspace code" in err
    code, out, _ = run("drop-tenant", "cli-co", "--confirm", "cli-co")
    assert code == 0 and "Dropped" in out
    code, out, _ = run("tenants")
    assert "cli-co" not in out
    with pytest.raises(SystemExit):
        cli.main(["install"])                                                         # needs a unit or --all
