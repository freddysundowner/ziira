"""The nightly stock check: balances and cost figures against the movements, and rebuilding them."""

from decimal import Decimal as Dec

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Verify Co")
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"}]})
    assert r.status_code == 201, r.text
    return s


def verify(shop, *, fix: bool = False) -> list[str]:  # type: ignore[no-untyped-def]
    from ziira.kernel.checks import run_integrity_checks

    problems = []
    for result in run_integrity_checks(shop["tenant_id"], fix=fix):
        assert result.unit == "inventory" and result.check == "stock ledger"
        problems += result.problems
    return problems


def damage(shop, sql: str) -> None:  # type: ignore[no-untyped-def]
    """Change a derived table behind the application's back (as a bug or a manual edit would)."""
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text(sql))


def test_a_healthy_ledger_has_no_problems(shop) -> None:  # type: ignore[no-untyped-def]
    assert verify(shop) == []


def test_a_wrong_balance_is_found_and_rebuilt(shop) -> None:  # type: ignore[no-untyped-def]
    damage(shop, "update inventory.stock_balance set quantity = 99")
    problems = verify(shop)
    assert len(problems) == 1 and "CEM at MAIN is 99 but its movements add up to 100" in problems[0]
    assert len(verify(shop, fix=True)) == 1                     # reports what it found, then rebuilds
    assert verify(shop) == []
    with system(shop) as s:
        assert s.execute(text("select quantity from inventory.stock_balance")).scalar_one() == 100


def test_a_missing_balance_row_is_found_and_rebuilt(shop) -> None:  # type: ignore[no-untyped-def]
    damage(shop, "delete from inventory.stock_balance")
    assert "is 0 but its movements add up to 100" in verify(shop)[0]
    verify(shop, fix=True)
    assert verify(shop) == []


def test_a_wrong_cost_figure_is_found_and_rebuilt(shop) -> None:  # type: ignore[no-untyped-def]
    damage(shop, "update inventory.product_cost set value = 12345, average_cost = 1")
    problems = verify(shop)
    assert len(problems) == 1 and "worth 12345" in problems[0] and "10000.00" in problems[0]
    verify(shop, fix=True)
    assert verify(shop) == []
    with system(shop) as s:
        row = s.execute(text("select quantity, value, average_cost from inventory.product_cost")).one()
    assert (row.quantity, row.value, row.average_cost) == (100, Dec("10000.00"), Dec("100"))


def test_the_command_line_reports_and_exits_nonzero(shop, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    assert cli.main(["stock-verify", str(shop["tenant_id"])]) == 0
    damage(shop, "update inventory.stock_balance set quantity = 1")
    assert cli.main(["stock-verify", str(shop["tenant_id"])]) == 1
    assert "but its movements add up to 100" in capsys.readouterr().out
    assert cli.main(["verify", str(shop["tenant_id"]), "--unit", "inventory", "--fix"]) == 0
    assert cli.main(["verify", str(shop["tenant_id"])]) == 0


def test_tenants_without_inventory_are_skipped(registry) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import make_tenant
    from ziira.kernel.checks import run_integrity_checks

    plain = make_tenant("Plain Verify")
    assert run_integrity_checks(plain["tenant_id"]) == []
