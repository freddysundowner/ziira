"""Registration never fails because of an optional step; a broken unit is isolated; core failures leave nothing behind;
the onboarding answers are stored."""

import importlib
from uuid import uuid4

import pytest
from sqlalchemy import text

from ziira.kernel import editions, packs, registration
from ziira.kernel import registry as registry_module
from ziira.kernel.api.ops_routes import readiness_problems
from ziira.kernel.db import master_session
from ziira.kernel.platform import subscriptions
from ziira.kernel.registry import discover, load_event_handlers

REGISTER, VERIFY = "/api/v1/register", "/api/v1/register/verify"


@pytest.fixture(autouse=True)
def clean(registry):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    registry_module.broken_units.clear()
    yield
    registry_module.broken_units.clear()
    registry_module.strict_by_default = True


def body(name=None, **kw):  # type: ignore[no-untyped-def]
    return {"business_name": name or f"Resilient {uuid4().hex[:6]}", "owner_name": "Jane Doe",
            "email": f"jane-{uuid4().hex[:8]}@acme.test", "password": "a-good-password-1", "currency": "kes",
            "phone_country_code": "254", "country": "ke", **kw}


def register(client, **kw):  # type: ignore[no-untyped-def]
    asked = client.post(REGISTER, json=body(**kw))
    assert asked.status_code == 202, asked.text
    return asked.json()["dev_token"]


def verify(client, token):  # type: ignore[no-untyped-def]
    return client.post(VERIFY, json={"token": token, "device_id": "dev-1"})


def repairs(workspace_id: str):  # type: ignore[no-untyped-def]
    with master_session() as s:
        return s.execute(text("select step, resolved_at, attempts from master.registration_repair "
                              "where tenant_id = :t order by step"), {"t": workspace_id}).all()


# --------------------------------------------------------------------------- a broken unit is isolated
def _break(monkeypatch, unit: str):  # type: ignore[no-untyped-def]
    package = discover()[unit].package
    real = importlib.import_module

    def fake(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == f"{package}.hooks":
            raise ImportError("cannot import name 'AttemptInfo'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)


def test_a_broken_unit_is_skipped_and_reported_unless_strict(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    unit = next(n for n, m in discover().items() if not m.core and n.startswith("billing_") or n == "messaging")
    _break(monkeypatch, unit)
    with pytest.raises(ImportError):
        load_event_handlers(discover(), strict=True)                    # loud where asked
    load_event_handlers(discover(), strict=False)                       # others keep working
    assert unit in registry_module.broken_units and "AttemptInfo" in registry_module.broken_units[unit]
    assert any(unit in p for p in readiness_problems())
    monkeypatch.undo()
    load_event_handlers(discover(), strict=False)                       # fixed: the report clears
    assert unit not in registry_module.broken_units


def test_registration_succeeds_while_a_unit_is_broken(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    registry_module.strict_by_default = False
    _break(monkeypatch, next(n for n, m in discover().items() if n == "messaging"))
    token = register(client, country="ke")
    done = verify(client, token)
    assert done.status_code == 200, done.text
    headers = {"Authorization": f"Bearer {done.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert "messaging" in registry_module.broken_units


# --------------------------------------------------------------------------- optional steps
def test_a_failed_pack_step_keeps_the_business_flags_it_and_is_repaired(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = packs.enable_country_pack

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("pack plugin exploded")

    monkeypatch.setattr(packs, "enable_country_pack", boom)
    done = verify(client, register(client, country="ke"))
    assert done.status_code == 200, done.text                           # the business exists, the owner is signed in
    tenant = done.json()["tenant_id"]
    assert [r.step for r in repairs(tenant)] == ["pack"] and repairs(tenant)[0].resolved_at is None
    with master_session() as s:
        flagged = s.execute(text("select outcome, detail->>'step' from master.operator_action_log "
                                 "where action = 'registration.setup_step_failed' and target = :w"),
                            {"w": done.json()["workspace"]}).all()
    assert flagged == [("failed", "pack")]

    monkeypatch.setattr(packs, "enable_country_pack", real)
    with master_session() as s:
        s.execute(text("update master.registration_repair set last_attempt_at = now() - interval '1 hour'"))
    assert registration.repair_pending() == 1
    assert repairs(tenant)[0].resolved_at is not None
    assert registration.repair_pending() == 0                           # idempotent: nothing left
    from tests.stock_helpers import system

    with system({"tenant_id": tenant}) as s:
        enabled = set(s.execute(text("select unit_name from kernel.tenant_unit where status = 'enabled'")).scalars())
    assert "pack_ke" in enabled


def test_a_failed_trial_step_is_repaired_and_never_started_twice(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = subscriptions.start_for_registration
    calls: list[str] = []

    def once_broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("x")
        if len(calls) == 1:
            raise RuntimeError("plan table locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(subscriptions, "start_for_registration", once_broken)
    done = verify(client, register(client))
    assert done.status_code == 200
    tenant = done.json()["tenant_id"]
    assert [r.step for r in repairs(tenant)] == ["plan"]
    with master_session() as s:
        s.execute(text("update master.registration_repair set last_attempt_at = now() - interval '1 hour'"))
    assert registration.repair_pending() == 1 and len(calls) == 2
    assert repairs(tenant)[0].resolved_at is not None


# --------------------------------------------------------------------------- core failures
def test_a_core_failure_is_a_clean_503_with_a_code_and_nothing_left_behind(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    token = register(client, name="Half Made Ltd")

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("units would not switch on")

    monkeypatch.setattr(editions, "enable_edition", boom)               # fails AFTER the tenant database was made
    failed = verify(client, token)
    assert failed.status_code == 503
    out = failed.json()
    assert out["error"] == "registration_failed" and "could not be created" in out["message"]
    assert out["registration"]
    with master_session() as s:
        assert s.execute(text("select count(*) from master.tenant where code like 'half-made-ltd%'")).scalar_one() == 0
        assert s.execute(text("select verified_at is null from master.registration")).scalar_one() is True
    monkeypatch.undo()
    assert verify(client, token).status_code == 200                      # the same link works afterwards


# --------------------------------------------------------------------------- onboarding answers
def test_onboarding_answers_are_stored_with_the_registration_and_the_business(client) -> None:  # type: ignore[no-untyped-def]
    token = register(client, phone="0712 345 678", owner_role="accountant", business_size="2-5", staff_size="6-20",
                     business_type="wholesale")
    with master_session() as s:
        row = s.execute(text("select phone, owner_role, business_size, staff_size, business_type "
                             "from master.registration")).one()
    assert tuple(row) == ("254712345678", "accountant", "2-5", "6-20", "wholesale")
    done = verify(client, token)
    with master_session() as s:
        hints = s.execute(text("select onboarding from master.tenant where id = :t"),
                          {"t": done.json()["tenant_id"]}).scalar_one()
    assert hints == {"role": "accountant", "phone": "254712345678", "business_size": "2-5", "staff_size": "6-20",
                     "business_type": "wholesale"}


def test_the_old_form_without_the_new_fields_still_works(client) -> None:  # type: ignore[no-untyped-def]
    assert verify(client, register(client)).status_code == 200


@pytest.mark.parametrize("field,value", [("owner_role", "emperor"), ("business_size", "7"), ("staff_size", "many"),
                                         ("business_type", "piracy"), ("phone", "abc")])
def test_onboarding_answers_are_validated(client, field, value) -> None:  # type: ignore[no-untyped-def]
    assert client.post(REGISTER, json=body(**{field: value})).status_code == 422


# --------------------------------------------------------------------------- the trial the form may promise
def test_the_trial_offer_is_only_given_when_a_default_plan_exists(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import plans

    monkeypatch.setattr(subscriptions, "default_plan_code", lambda edition=None: None)
    assert client.get("/api/v1/register/trial").json() is None
    monkeypatch.setattr(subscriptions, "default_plan_code", lambda edition=None: "starter")
    monkeypatch.setattr(plans, "get_plan", lambda code: {"code": code, "name": "Starter", "status": "active",
                                                          "trial_days": 14})
    assert client.get("/api/v1/register/trial?edition=retail").json() == {
        "plan_code": "starter", "plan_name": "Starter", "trial_days": 14}
    monkeypatch.setattr(plans, "get_plan", lambda code: {"code": code, "name": "Starter", "status": "retired",
                                                          "trial_days": 14})
    assert client.get("/api/v1/register/trial").json() is None
    assert client.get("/api/v1/register/trial?edition=no-such-edition").status_code == 200   # ignored, not an error


def test_an_unknown_plan_in_the_request_is_ignored(client) -> None:  # type: ignore[no-untyped-def]
    token = register(client, plan="no-such-plan")
    with master_session() as s:
        assert s.execute(text("select plan_code from master.registration")).scalar_one() is None
    assert verify(client, token).status_code == 200
