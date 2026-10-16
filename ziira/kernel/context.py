"""Request context: which tenant and user the current work is for, and what they may do."""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ziira.kernel.errors import Forbidden
from ziira.kernel.observability import bind_tenant


@dataclass(frozen=True)
class Assignment:
    """A role granted to the user, with the permissions it carries and where it applies.

    scope: 'tenant' (everything), 'company' (one company), 'branch' (one branch),
    or 'own' (only records the user created). A null company_id or branch_id means "all".
    """

    role_id: UUID | None
    role_name: str
    scope: str
    company_id: UUID | None
    branch_id: UUID | None
    permissions: frozenset[str]

    def covers(self, company_id: UUID | None, branch_id: UUID | None, owner_id: UUID | None,
               user_id: UUID | None) -> bool:
        """True if this assignment reaches the given company, branch and record owner.

        A company-level action (no branch) needs an assignment for the whole company;
        a tenant-level action (no company) needs a tenant-wide assignment.
        """
        if self.scope == "own":
            return owner_id is not None and owner_id == user_id
        if self.company_id is not None and self.company_id != company_id:
            return False
        return self.branch_id is None or self.branch_id == branch_id


@dataclass(frozen=True)
class RequestContext:
    """Who is acting, for which tenant, through which channel, with which roles.

    all_permissions is for system jobs, scripts and the development tenant header only.
    """

    tenant_id: UUID
    user_id: UUID | None = None
    channel: str = "api"
    session_id: UUID | None = None
    assignments: tuple[Assignment, ...] = ()
    all_permissions: bool = False
    # Where the request came from, for the audit log.
    device_id: str | None = None
    ip_address: str | None = None
    # The business requires a second factor of this person and it is not set up: only the setup calls may be made.
    mfa_setup_required: bool = False
    # Platform staff working in the business under a support grant (channel 'support'; there is no user then).
    support_operator_id: UUID | None = None
    support_operator_name: str | None = None
    support_grant_id: UUID | None = None
    support_session_id: UUID | None = None
    support_level: str | None = None         # 'read' or 'full'
    support_until: datetime | None = None
    # Set when the caller is an API key (kernel/api_keys.py): which key, and whether it may only read.
    api_key_id: UUID | None = None
    api_key_read_only: bool = False

    def can(self, permission: str, *, company_id: UUID | None = None, branch_id: UUID | None = None,
            owner_id: UUID | None = None) -> bool:
        """True if the actor holds `permission` with a scope covering the target."""
        if self.all_permissions:
            return True
        return any(permission in a.permissions and a.covers(company_id, branch_id, owner_id, self.user_id)
                   for a in self.assignments)

    def require(self, permission: str, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                owner_id: UUID | None = None) -> None:
        """Raise Forbidden unless `can(...)`."""
        if not self.can(permission, company_id=company_id, branch_id=branch_id, owner_id=owner_id):
            raise Forbidden(f"You do not have permission '{permission}' here")

    def has_anywhere(self, permission: str) -> bool:
        """True if the actor holds `permission` in at least one scope (used for endpoint access)."""
        return self.all_permissions or any(permission in a.permissions for a in self.assignments)

    def companies_with(self, permission: str) -> set[UUID] | None:
        """Companies where the actor holds `permission` at any level; None means all companies.

        Use it to filter lists: a branch-level grant still lets the user read company records.
        """
        if self.all_permissions:
            return None
        found: set[UUID] = set()
        for a in self.assignments:
            if permission not in a.permissions:
                continue
            if a.company_id is None:
                return None
            found.add(a.company_id)
        return found

    def scopes_with(self, permission: str) -> list[tuple[UUID | None, UUID | None]] | None:
        """Where the actor holds `permission`, as (company_id, branch_id) pairs; None means everywhere.

        A null company means every company; a null branch means every branch of the company.
        Use it to filter lists of branch-level records (stock, till sessions). "Own" grants reach
        only records the user created, so they are left out.
        """
        if self.all_permissions:
            return None
        found: list[tuple[UUID | None, UUID | None]] = []
        for a in self.assignments:
            if permission not in a.permissions or a.scope == "own":
                continue
            if a.company_id is None:
                return None
            found.append((a.company_id, a.branch_id))
        return found

    def has_role(self, role_id: UUID, *, company_id: UUID | None = None,
                 branch_id: UUID | None = None) -> bool:
        """True if the actor holds this role with a scope covering the company or branch."""
        return any(a.role_id == role_id and a.covers(company_id, branch_id, None, self.user_id)
                   for a in self.assignments)


_current: ContextVar[RequestContext | None] = ContextVar("ziira_request_context", default=None)


def set_context(ctx: RequestContext) -> None:
    """Set the context for the current task or request."""
    _current.set(ctx)
    bind_tenant(ctx.tenant_id)             # the access log line names the business


def get_context() -> RequestContext:
    """Return the current context, or raise if none is set."""
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("No tenant context is set for this operation")
    return ctx


def system_context(tenant_id: UUID) -> RequestContext:
    """Context for jobs, scripts and the CLI: acts as the system with every permission."""
    ctx = RequestContext(tenant_id=tenant_id, channel="system", all_permissions=True)
    set_context(ctx)
    return ctx
