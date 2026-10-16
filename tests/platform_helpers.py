"""Shared set-up for the Super Admin platform tests: operators of each role, plans, and subscribed businesses."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from tests.test_support_access import OP_PASSWORD, code_for, operator_token
from ziira.kernel import operators
from ziira.kernel.platform import plans

API = "/api/v1"
T0 = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)          # a frozen "now" for billing tests (far from the real clock)


def staff(client, role: str = "superadmin") -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """A signed-in operator of `role`: {"email", "secret", "headers", "id"}."""
    email = f"{role}-{uuid4().hex[:8]}@ziira.test"
    operator_id, secret, _ = operators.create_operator(f"Test {role}", email, OP_PASSWORD, role)
    return {"email": email, "secret": secret, "headers": operator_token(client, email, secret), "id": operator_id}


def make_plan(code: str, *, units: list[str] | None = None, edition: str | None = None, public: bool = True,
              trial_days: int = 14, prices: dict[tuple[str, str], str] | None = None, tax_inclusive: bool = False,
              **limits: Any) -> dict[str, Any]:
    """A plan with prices {(currency, interval): amount}, straight through the services."""
    plan = plans.create_plan({"code": code, "name": code.title(), "units": units if units is not None else
                              ["products"], "edition": edition, "is_public": public, "trial_days": trial_days,
                              "intervals": ["month", "year", "one_time"], **limits})
    for (currency, interval), amount in (prices or {}).items():
        plans.set_price("plan", plan["id"], currency=currency, interval=interval, amount=amount,
                        tax_inclusive=tax_inclusive)           # in force from the real now, so a frozen 2030 sees it
    return plans.get_plan(code)


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


__all__ = ["API", "T0", "code_for", "dec", "make_plan", "staff"]
