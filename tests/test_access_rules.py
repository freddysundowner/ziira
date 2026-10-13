"""Pure rules of access control, tokens, passwords and manifests (no database)."""

from pathlib import Path
from uuid import uuid4

import pytest

from ziira.kernel.context import Assignment, RequestContext
from ziira.kernel.errors import Forbidden, Unauthorized
from ziira.kernel.manifest import load_manifest, sdk_compatible
from ziira.kernel.security import hash_password, read_token, sign_token, verify_password

TENANT, CO1, CO2, BR1, BR2, ME = (uuid4() for _ in range(6))


def ctx(*assignments: Assignment) -> RequestContext:
    return RequestContext(tenant_id=TENANT, user_id=ME, assignments=assignments)


def grant(scope: str, company=None, branch=None, perms=("stock.adjust",)) -> Assignment:  # type: ignore[no-untyped-def]
    return Assignment(role_id=uuid4(), role_name="r", scope=scope, company_id=company, branch_id=branch,
                      permissions=frozenset(perms))


def test_tenant_grant_covers_everything() -> None:
    c = ctx(grant("tenant"))
    assert c.can("stock.adjust")
    assert c.can("stock.adjust", company_id=CO1, branch_id=BR1)
    assert not c.can("stock.view")


def test_company_grant_covers_its_company_and_branches_only() -> None:
    c = ctx(grant("company", CO1))
    assert c.can("stock.adjust", company_id=CO1)
    assert c.can("stock.adjust", company_id=CO1, branch_id=BR1)
    assert not c.can("stock.adjust", company_id=CO2)
    assert not c.can("stock.adjust")                      # tenant-level action


def test_branch_grant_does_not_reach_company_level() -> None:
    c = ctx(grant("branch", CO1, BR1))
    assert c.can("stock.adjust", company_id=CO1, branch_id=BR1)
    assert not c.can("stock.adjust", company_id=CO1, branch_id=BR2)
    assert not c.can("stock.adjust", company_id=CO1)      # affects the whole company
    assert c.companies_with("stock.adjust") == {CO1}      # but may read the company's records
    with pytest.raises(Forbidden):
        c.require("stock.adjust", company_id=CO1)


def test_own_grant_needs_ownership() -> None:
    c = ctx(grant("own"))
    assert c.can("stock.adjust", owner_id=ME)
    assert not c.can("stock.adjust", owner_id=uuid4())
    assert not c.can("stock.adjust")


def test_companies_with() -> None:
    assert ctx(grant("tenant")).companies_with("stock.adjust") is None
    assert ctx(grant("company", CO1), grant("company", CO2)).companies_with("stock.adjust") == {CO1, CO2}
    assert ctx(grant("company", CO1)).companies_with("stock.view") == set()


def test_sdk_compatibility() -> None:
    assert sdk_compatible(">=1.0,<2.0", "1.0")
    assert sdk_compatible(">=1.0,<2.0", "1.9.3")
    assert not sdk_compatible(">=1.0,<2.0", "2.0")
    assert not sdk_compatible(">=1.1", "1.0")
    assert sdk_compatible("", "1.0")
    with pytest.raises(ValueError):
        sdk_compatible("~1.0", "1.0")


def test_manifest_roles_must_use_declared_permissions(tmp_path: Path) -> None:
    f = tmp_path / "manifest.toml"
    f.write_text('[unit]\nname = "x"\nversion = "1.0.0"\n[permissions]\n"x.view" = "View"\n'
                 '[roles]\n"Cashier" = ["x.view", "x.delete"]\n')
    with pytest.raises(ValueError, match="x.delete"):
        load_manifest(f, "x")


def test_password_hash_and_verify() -> None:
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)
    assert not verify_password("anything", None)
    assert hash_password("correct horse") != stored        # salted


def test_tokens_are_signed_and_expire() -> None:
    token = sign_token({"t": "x"}, minutes=5)
    assert read_token(token)["t"] == "x"
    body, signature = token.split(".")
    with pytest.raises(Unauthorized):
        read_token(f"{body}x.{signature}")
    with pytest.raises(Unauthorized, match="expired"):
        read_token(sign_token({"t": "x"}, minutes=-1))
    with pytest.raises(Unauthorized):
        read_token("not-a-token")
