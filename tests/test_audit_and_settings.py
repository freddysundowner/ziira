"""Audit entries record device and IP; company settings have defaults, validation and permissions."""

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in

WS = "settings-co"
OWNER = "owner@settings-co.test"


@pytest.fixture(scope="module")
def t(client, registry):  # type: ignore[no-untyped-def]
    return make_tenant("Settings Co")


def audit_rows(t, action: str):  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    with tenant_session(t["tenant_id"]) as s:
        return s.execute(text("select device_id, host(ip_address) as ip, user_id from kernel.audit_log "
                              "where action = :a order by id"), {"a": action}).all()


# --------------------------------------------------------------------------- audit device and IP
def test_audit_records_the_device_and_ip(client, t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings

    owner = sign_in(client, WS, OWNER, device_id="laptop-1").headers
    login = audit_rows(t, "login")[-1]
    assert login.device_id == "laptop-1" and login.ip is None       # the test client has no real address

    get_settings().trust_forwarded_for = True
    try:
        r = client.patch(f"/api/v1/companies/{t['company_id']}/settings", headers={
            **owner, "X-Forwarded-For": "198.51.100.7, 203.0.113.9"}, json={"negative_stock_allowed": True})
        assert r.status_code == 200, r.text
    finally:
        get_settings().trust_forwarded_for = False
    changed = audit_rows(t, "update")[-1]
    assert changed.device_id == "laptop-1"
    assert changed.ip == "203.0.113.9"                              # the proxy's entry, not the forgeable one


def test_forwarded_header_is_ignored_unless_trusted(client, t) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER, device_id="laptop-2").headers
    client.patch(f"/api/v1/companies/{t['company_id']}/settings", headers={**owner, "X-Forwarded-For": "203.0.113.50"},
                 json={"negative_stock_allowed": False})
    assert audit_rows(t, "update")[-1].ip is None


# --------------------------------------------------------------------------- company settings
def test_settings_default_then_change(client, t) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER).headers
    url = f"/api/v1/companies/{t['company_id']}/settings"
    assert client.get(url, headers=owner).json() == {"negative_stock_allowed": False,
                                                     "count_variance_threshold": "0",
                                                     "late_posting": "redirect"}
    r = client.patch(url, headers=owner, json={"count_variance_threshold": "5000.50"})
    assert r.status_code == 200
    assert r.json() == {"negative_stock_allowed": False, "count_variance_threshold": "5000.50",
                        "late_posting": "redirect"}
    assert client.patch(url, headers=owner, json={"negative_stock_allowed": True}).json() == {
        "negative_stock_allowed": True, "count_variance_threshold": "5000.50",
        "late_posting": "redirect"}                                                    # the other values are kept


def test_settings_validation(client, t) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER).headers
    url = f"/api/v1/companies/{t['company_id']}/settings"
    assert client.patch(url, headers=owner, json={"count_variance_threshold": "-1"}).status_code == 422
    assert client.patch(url, headers=owner, json={"colour": "blue"}).status_code == 422       # unknown setting
    assert client.patch(url, headers=owner, json={"negative_stock_allowed": "maybe"}).status_code == 422


def test_settings_need_permission_and_a_real_company(client, t) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    owner = sign_in(client, WS, OWNER).headers
    client.post("/api/v1/users", headers=owner, json={"full_name": "Nobody", "email": "nobody@settings-co.test",
                                                      "password": "nobody-pass-1"})
    nobody = sign_in(client, WS, "nobody@settings-co.test", "nobody-pass-1").headers
    url = f"/api/v1/companies/{t['company_id']}/settings"
    assert client.get(url, headers=nobody).status_code == 403
    assert client.patch(url, headers=nobody, json={"negative_stock_allowed": True}).status_code == 403
    assert client.get(f"/api/v1/companies/{uuid4()}/settings", headers=owner).status_code == 404


def test_units_read_settings_through_the_sdk(t) -> None:  # type: ignore[no-untyped-def]
    from decimal import Decimal

    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.sdk import company_setting

    system_context(t["tenant_id"])
    with tenant_session(t["tenant_id"]) as s:
        assert company_setting(s, t["company_id"], "count_variance_threshold") == Decimal("5000.50")
        assert company_setting(s, t["company_id"], "negative_stock_allowed") is True
        with pytest.raises(KeyError):
            company_setting(s, t["company_id"], "nope")
