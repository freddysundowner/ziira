"""Use cases: posting rules (which account a document line goes to). Data, not code (specification section 07)."""

from uuid import UUID

from ziira.modules.finance.domain import recipes
from ziira.modules.finance.permissions import ACCOUNTS_MANAGE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import PostingRule
from ziira.modules.finance.services.access import require_visible
from ziira.modules.finance.services.books import ensure_books
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, current_context


def list_rules(session: Session, company_id: UUID) -> list[PostingRule]:
    """The company's posting rules."""
    require_visible(company_id)
    return finance_repo.list_rules(session, company_id)


def _check(session: Session, company_id: UUID, doc_type: str, role: str, account_id: UUID, side: str,
           conditions: dict[str, str]) -> None:
    if doc_type not in recipes.DOC_ROLES:
        raise ValidationFailed(f"Document type must be one of: {', '.join(recipes.DOC_ROLES)}")
    if role not in recipes.DOC_ROLES[doc_type]:
        raise ValidationFailed(f"A '{doc_type}' has these line roles: {', '.join(recipes.DOC_ROLES[doc_type])}")
    if side not in ("debit", "credit"):
        raise ValidationFailed("Side must be debit or credit")
    allowed = recipes.RULE_CONDITIONS[doc_type]
    for key, value in conditions.items():
        if key not in allowed:
            raise ValidationFailed(f"A '{doc_type}' rule can only be conditional on: {', '.join(allowed) or 'nothing'}")
        if key == "movement_type" and value not in recipes.MOVEMENT_TYPES:
            raise ValidationFailed(f"Movement type must be one of: {', '.join(recipes.MOVEMENT_TYPES)}")
    account = finance_repo.get_account(session, account_id)
    if account is None or account.company_id != company_id:
        raise ValidationFailed("Account not found in this company")
    if not account.is_active:
        raise ValidationFailed("That account is not active")


def create_rule(session: Session, *, company_id: UUID, doc_type: str, line_role: str, account_id: UUID, side: str,
                conditions: dict[str, str] | None = None, priority: int = 100) -> PostingRule:
    """Add a rule. A rule with conditions (for example only for write-offs) wins over one without. Needs
    'accounts.manage' for the company."""
    ctx = current_context()
    ctx.require(ACCOUNTS_MANAGE, company_id=company_id)
    ensure_books(session, company_id)
    conditions = conditions or {}
    _check(session, company_id, doc_type, line_role, account_id, side, conditions)
    if not 1 <= priority <= 1000:
        raise ValidationFailed("Priority must be between 1 and 1000")
    rule = PostingRule(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, doc_type=doc_type,
                       line_role=line_role, account_id=account_id, side=side, conditions=conditions, priority=priority)
    finance_repo.add(session, rule)
    audit_record(session, "create", "finance.posting_rule", rule.id,
                 {"doc_type": doc_type, "role": line_role, "account_id": account_id, "conditions": conditions})
    return rule


def update_rule(session: Session, rule_id: UUID, *, account_id: UUID) -> PostingRule:
    """Point a rule at another account. Needs 'accounts.manage' for the company."""
    rule = finance_repo.get_rule(session, rule_id)
    if rule is None:
        raise NotFound("Posting rule not found")
    current_context().require(ACCOUNTS_MANAGE, company_id=rule.company_id)
    _check(session, rule.company_id, rule.doc_type, rule.line_role, account_id, rule.side, dict(rule.conditions))
    before, rule.account_id = rule.account_id, account_id
    session.flush()
    audit_record(session, "update", "finance.posting_rule", rule.id, {"account_id": {"from": before, "to": account_id}})
    return rule


def delete_rule(session: Session, rule_id: UUID) -> None:
    """Remove a rule. The last rule without conditions for a role cannot go: documents would no longer post."""
    rule = finance_repo.get_rule(session, rule_id)
    if rule is None:
        raise NotFound("Posting rule not found")
    current_context().require(ACCOUNTS_MANAGE, company_id=rule.company_id)
    if not rule.conditions:
        others = [r for r in finance_repo.list_rules(session, rule.company_id)
                  if r.id != rule.id and r.doc_type == rule.doc_type and r.line_role == rule.line_role
                  and not r.conditions]
        if not others:
            raise ValidationFailed("This is the only rule for that line: documents would stop posting without it")
    finance_repo.delete_rule(session, rule)
    audit_record(session, "delete", "finance.posting_rule", rule_id,
                 {"doc_type": rule.doc_type, "role": rule.line_role})
