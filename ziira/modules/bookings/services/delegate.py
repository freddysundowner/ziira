"""The front desk's right to bill.

Billing a client means issuing an invoice and taking a payment, which Point of Sale guards with its own permissions
(`invoices.manage`, `receivables.manage`) and the client's record by Customers (`customers.manage`). The Cashier and
Sales Rep roles are the front desk, and the Cashier did not have `invoices.manage`, so a receptionist could finish a
visit but not bill it. Instead of changing another unit's roles, Bookings has its own permission, `bookings.checkout`: a
person who holds it at the branch may issue the invoice and take the payment *for a checkout*, and only there. The
rights are lent for the length of the `with` block, to that one branch.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_CHECKOUT
from ziira.sdk import Assignment, current_context, set_context

LENT = frozenset({"invoices.manage", "receivables.manage", "customers.manage", "bookings.manage"})


@contextmanager
def front_desk_rights(company_id: UUID, branch_id: UUID) -> Iterator[None]:
    """Check the person may check clients out here, then lend them the billing rights until the block ends."""
    ctx = current_context()
    ctx.require(BOOKINGS_CHECKOUT, company_id=company_id, branch_id=branch_id)
    lent = Assignment(role_id=None, role_name="bookings.checkout", scope="branch", company_id=company_id,
                      branch_id=branch_id, permissions=LENT)
    set_context(replace(ctx, assignments=(*ctx.assignments, lent)))
    try:
        yield
    finally:
        set_context(ctx)
