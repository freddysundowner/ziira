"""Shared setup for the gym tests: the Memberships shop (sales and invoices work) with a desk user, a manager, a gym plan
catalogue and helpers for ageing invoices (the clock is real, so tests move the invoice's date instead)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from tests.memberships_helpers import M, customer, make_member_shop, rows, scalar, sign_up
from tests.stock_helpers import system

__all__ = ["M", "age_invoice", "customer", "gym_plan", "make_gym_shop", "rows", "scalar", "sign_up", "today"]


def today() -> date:
    return date.today()


def make_gym_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """The member shop plus: `desk` (Cashier at HQ: may check people in), `boss` (company-wide manager: may override),
    and the second branch JUJA."""
    shop = make_member_shop(client, registry, name)
    shop["desk"] = shop["user"]("desk", "Cashier", shop["branch_id"])
    return shop


def gym_plan(client, shop, code: str, **extra: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "code": code, "name": extra.pop("name", code.title()),
            "fee": extra.pop("fee", "100.00"), "billing_interval": extra.pop("billing_interval", "month"),
            "service_product_id": shop["delivery"], **extra}
    r = client.post(f"{M}/plans", headers=shop["owner"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def age_invoice(shop, invoice_number: str, days: int) -> None:  # type: ignore[no-untyped-def]
    """Make an invoice `days` days past its due date (tests cannot wait)."""
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("alter table pos.sales_invoice disable trigger sales_invoice_protected"))
        s.execute(text("update pos.sales_invoice set due_date = :d where number = :n"),
                  {"d": date.today() - timedelta(days=days), "n": invoice_number})
        s.execute(text("alter table pos.sales_invoice enable trigger sales_invoice_protected"))
        s.execute(text("update memberships.invoice_run set due_date = :d where invoice_number = :n"),
                  {"d": date.today() - timedelta(days=days), "n": invoice_number})


def refresh(shop) -> int:  # type: ignore[no-untyped-def]
    from ziira.modules.memberships.services import dues

    with system(shop) as s:
        return dues.refresh_runs(s, UUID(str(shop["company_id"])))


def total(value: Any) -> Decimal:
    return Decimal(str(value))
