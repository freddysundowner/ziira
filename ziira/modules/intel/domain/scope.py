"""Which branches of a company a user may see, for ask tools to filter their rows by."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from ziira.sdk import Forbidden, RequestContext, ValidationFailed


@dataclass(frozen=True)
class BranchScope:
    """Where a user may read: the whole company (`everything`), or only these branches. Company-wide records (no
    branch) are visible only with `everything`."""

    everything: bool
    branches: frozenset[UUID] = frozenset()

    @property
    def nothing(self) -> bool:
        return not self.everything and not self.branches

    def allows(self, branch_id: UUID | None) -> bool:
        if self.everything:
            return True
        return branch_id is not None and branch_id in self.branches

    def sql(self, column: str = "branch_id", key: str = "scope_branches") -> tuple[str, dict[str, Any]]:
        """A SQL condition on `column` and its parameters."""
        if self.everything:
            return "true", {}
        if not self.branches:
            return "false", {}
        return f"{column} = any(:{key})", {key: [str(b) for b in sorted(self.branches, key=str)]}


def scope_from_pairs(scopes: Iterable[tuple[UUID | None, UUID | None]] | None, company_id: UUID) -> BranchScope:
    """A BranchScope from `(company, branch)` pairs as `RequestContext.scopes_with` returns them (None: everywhere)."""
    if scopes is None:
        return BranchScope(True)
    branches: set[UUID] = set()
    for company, branch in scopes:
        if company is not None and company != company_id:
            continue
        if branch is None:
            return BranchScope(True)
        branches.add(branch)
    return BranchScope(False, frozenset(branches))


def branch_scope(context: RequestContext, permissions: Iterable[str], company_id: UUID) -> BranchScope:
    """The branches of `company_id` where the user holds any of `permissions`."""
    branches: set[UUID] = set()
    for permission in permissions:
        scope = scope_from_pairs(context.scopes_with(permission), company_id)
        if scope.everything:
            return scope
        branches |= scope.branches
    return BranchScope(False, frozenset(branches))


def company_visible(context: RequestContext, permission: str, company_id: UUID) -> bool:
    """True if the user holds `permission` at any level in the company (for records that belong to the company)."""
    companies = context.companies_with(permission)
    return companies is None or company_id in companies


def date_range(params: dict[str, Any], *, max_days: int = 370) -> tuple[date, date]:
    """`date_from` and `date_to` of a tool's parameters, checked to be in order and not longer than `max_days`."""
    start, end = date.fromisoformat(params["date_from"]), date.fromisoformat(params["date_to"])
    if end < start:
        raise ValidationFailed("date_to is before date_from")
    if (end - start).days >= max_days:
        raise ValidationFailed(f"Ask for a period of at most {max_days} days")
    return start, end


def requested_branch(scope: BranchScope, params: dict[str, Any]) -> UUID | None:
    """The branch the model asked about, refused unless the person may see it."""
    if not params.get("branch_id"):
        return None
    branch = UUID(params["branch_id"])
    if not scope.allows(branch):
        raise Forbidden("You do not have access to that branch")
    return branch
