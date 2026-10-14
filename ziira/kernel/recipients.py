"""Who should be told about something: the active users who hold a permission, with the scope they hold it in.

Used for alerts and briefs: a branch manager is told about their branch, the owner about everything.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.auth import load_assignments
from ziira.kernel.context import RequestContext, get_context


@dataclass(frozen=True)
class Recipient:
    """An active user who holds the permission, with how to reach them and the context to filter what they may see."""

    user_id: UUID
    full_name: str
    email: str | None
    phone: str | None
    context: RequestContext

    def covers(self, permission: str, company_id: UUID | None, branch_id: UUID | None) -> bool:
        """True if this person holds the permission where the company/branch is."""
        return self.context.can(permission, company_id=company_id, branch_id=branch_id)


def recipients_with_permission(session: Session, permission: str) -> list[Recipient]:
    """Active users holding `permission` in some scope. The session must be scoped to the tenant."""
    tenant_id = get_context().tenant_id
    rows = session.execute(text(
        "select u.id, u.full_name, u.email, u.phone from kernel.app_user u where u.status = 'active' "
        "and exists (select 1 from kernel.user_role ur join kernel.role_permission rp on rp.role_id = ur.role_id "
        "where ur.user_id = u.id and rp.permission_code = :p) order by u.full_name"), {"p": permission}).all()
    found: list[Recipient] = []
    for r in rows:
        assignments = load_assignments(session, r.id)
        context = RequestContext(tenant_id=tenant_id, user_id=r.id, channel="system", assignments=assignments)
        found.append(Recipient(r.id, r.full_name, r.email, r.phone, context))
    return found
