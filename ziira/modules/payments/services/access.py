"""Who may see which payments (company and branch scope)."""

from uuid import UUID

from ziira.modules.payments.permissions import PAYMENTS_VIEW
from ziira.sdk import current_context


def view_scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    """(company, branch) pairs the user may view payments for; None means everywhere."""
    return current_context().scopes_with(PAYMENTS_VIEW)


def can_view(company_id: UUID, branch_id: UUID | None) -> bool:
    return current_context().can(PAYMENTS_VIEW, company_id=company_id, branch_id=branch_id)
