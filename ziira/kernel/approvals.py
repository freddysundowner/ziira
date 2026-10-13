"""Approvals: the configurable approval matrix (specification section 13).

A company sets rules per document type: an amount range, a step, and the role that approves.
When a module submits a document, the rules whose range contains the amount apply, in step
order: each step must be approved before the next is requested. With no matching rule the
document needs no approval.

Separation of duties: where a rule says so (the default), the person who requested the
approval cannot approve it.

When the last step is approved, or any step is rejected, the kernel publishes
`approval.decided` (aggregate = the document) in the same transaction, so the module that
owns the document can post or reject it atomically from its @subscribe handler.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.context import get_context
from ziira.kernel.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ziira.kernel.events import Event, publish

APPROVED, PENDING, REJECTED = "approved", "pending", "rejected"


@dataclass(frozen=True)
class ApprovalRule:
    """One row of the approval matrix."""

    id: UUID
    company_id: UUID
    doc_type: str
    min_amount: Decimal
    max_amount: Decimal | None
    step: int
    approver_role_id: UUID
    forbid_creator: bool
    is_active: bool


@dataclass(frozen=True)
class ApprovalRequest:
    """A request for one step of approval of one document."""

    id: UUID
    company_id: UUID | None
    doc_type: str
    doc_id: UUID
    amount: Decimal | None
    step: int
    status: str
    rule_id: UUID | None
    requested_by: UUID | None
    decided_by: UUID | None
    note: str | None


@dataclass(frozen=True)
class Submission:
    """Result of submitting a document: 'approved' (no approval needed) or 'pending'."""

    status: str
    request_id: UUID | None = None


_RULE_COLUMNS = "id, company_id, doc_type, min_amount, max_amount, step, approver_role_id, forbid_creator, is_active"
_REQUEST_COLUMNS = ("id, company_id, doc_type, doc_id, amount, step, status, rule_id, requested_by, decided_by, "
                    "note")


# --------------------------------------------------------------------------- the matrix
def create_rule(s: Session, *, company_id: UUID, doc_type: str, approver_role_id: UUID, step: int = 1,
                min_amount: Decimal = Decimal("0"), max_amount: Decimal | None = None,
                forbid_creator: bool = True) -> ApprovalRule:
    """Add a rule to the approval matrix of a company."""
    if step < 1:
        raise ValidationFailed("Step must be 1 or more")
    if min_amount < 0 or (max_amount is not None and max_amount < min_amount):
        raise ValidationFailed("Amount range is invalid")
    if s.execute(text("select 1 from kernel.role where id = :r"), {"r": str(approver_role_id)}).first() is None:
        raise ValidationFailed("Approver role does not exist")
    if s.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise ValidationFailed("Company not found")
    row = s.execute(text(
        "insert into kernel.approval_rule (tenant_id, created_by, company_id, doc_type, min_amount, max_amount, "
        "step, approver_role_id, forbid_creator) values (kernel.current_tenant(), :u, :c, :d, :mn, :mx, :st, :r, :f) "
        f"returning {_RULE_COLUMNS}"),
        {"u": _user(), "c": str(company_id), "d": doc_type, "mn": min_amount, "mx": max_amount, "st": step,
         "r": str(approver_role_id), "f": forbid_creator}).one()
    rule = ApprovalRule(**row._mapping)
    audit.record(s, "create", "kernel.approval_rule", rule.id,
                 {"doc_type": doc_type, "step": step, "min_amount": min_amount, "max_amount": max_amount,
                  "approver_role_id": approver_role_id})
    return rule


def list_rules(s: Session, company_id: UUID | None = None) -> list[ApprovalRule]:
    """Active and inactive rules, optionally for one company."""
    rows = s.execute(text(
        f"select {_RULE_COLUMNS} from kernel.approval_rule "
        "where cast(:c as uuid) is null or company_id = :c order by doc_type, step, min_amount"),
        {"c": str(company_id) if company_id else None})
    return [ApprovalRule(**r._mapping) for r in rows]


def set_rule_active(s: Session, rule_id: UUID, active: bool) -> None:
    """Switch a rule on or off. Rules are kept for the history of past requests."""
    if s.execute(text("update kernel.approval_rule set is_active = :a, updated_at = now() where id = :i "
                      "returning id"), {"a": active, "i": str(rule_id)}).first() is None:
        raise NotFound("Approval rule not found")
    audit.record(s, "activate" if active else "deactivate", "kernel.approval_rule", rule_id)


def _matching_rules(s: Session, company_id: UUID, doc_type: str, amount: Decimal, after_step: int = 0) -> list[
        ApprovalRule]:
    rows = s.execute(text(
        f"select {_RULE_COLUMNS} from kernel.approval_rule where is_active and company_id = :c and doc_type = :d "
        "and min_amount <= :a and (max_amount is null or :a <= max_amount) and step > :after "
        "order by step, min_amount desc"),
        {"c": str(company_id), "d": doc_type, "a": amount, "after": after_step})
    return [ApprovalRule(**r._mapping) for r in rows]


# --------------------------------------------------------------------------- requests
def submit_for_approval(s: Session, *, company_id: UUID, doc_type: str, doc_id: UUID,
                        amount: Decimal = Decimal("0")) -> Submission:
    """Start approval of a document. Returns 'approved' at once if no rule applies.

    The module keeps the document in 'pending_approval' while the result is 'pending',
    and posts it when it receives `approval.decided` with status 'approved'.
    """
    open_request = s.execute(text(
        "select 1 from kernel.approval_request where doc_type = :d and doc_id = :i and status = 'pending'"),
        {"d": doc_type, "i": str(doc_id)}).first()
    if open_request:
        raise Conflict("This document is already waiting for approval")
    rules = _matching_rules(s, company_id, doc_type, amount)
    if not rules:
        return Submission(status=APPROVED)
    request_id = _open_request(s, rules[0], company_id, doc_type, doc_id, amount, requested_by=_user())
    return Submission(status=PENDING, request_id=request_id)


def _open_request(s: Session, rule: ApprovalRule, company_id: UUID, doc_type: str, doc_id: UUID,
                  amount: Decimal, requested_by: str | None) -> UUID:
    request_id: UUID = s.execute(text(
        "insert into kernel.approval_request (tenant_id, created_by, rule_id, company_id, doc_type, doc_id, amount, "
        "step, requested_by) values (kernel.current_tenant(), :u, :r, :c, :d, :i, :a, :st, :u) returning id"),
        {"u": requested_by, "r": str(rule.id), "c": str(company_id), "d": doc_type, "i": str(doc_id),
         "a": amount, "st": rule.step}).scalar_one()
    audit.record(s, "submit", "kernel.approval_request", request_id,
                 {"doc_type": doc_type, "doc_id": doc_id, "step": rule.step, "amount": amount})
    return request_id


def get_request(s: Session, request_id: UUID) -> ApprovalRequest:
    """One approval request."""
    row = s.execute(text(f"select {_REQUEST_COLUMNS} from kernel.approval_request where id = :i"),
                    {"i": str(request_id)}).first()
    if row is None:
        raise NotFound("Approval request not found")
    return ApprovalRequest(**row._mapping)


def pending_for_me(s: Session) -> list[ApprovalRequest]:
    """Pending requests the current user could decide (holds the approver role in scope)."""
    ctx = get_context()
    rows = s.execute(text(
        "select r.id, r.company_id, ru.approver_role_id from kernel.approval_request r "
        "join kernel.approval_rule ru on ru.id = r.rule_id where r.status = 'pending' "
        "and (r.expires_at is null or r.expires_at > now()) order by r.created_at"))
    return [get_request(s, r.id) for r in rows if ctx.has_role(r.approver_role_id, company_id=r.company_id)]


def decide(s: Session, request_id: UUID, *, approve: bool, note: str | None = None) -> ApprovalRequest:
    """Approve or reject one step, as the current user.

    Approving the last step (or rejecting any step) publishes `approval.decided`.
    Approving an earlier step opens the next one.
    """
    ctx = get_context()
    if ctx.user_id is None:
        raise Forbidden("Approvals must be given by a signed-in user")
    row = s.execute(text(
        f"select {_REQUEST_COLUMNS}, expires_at from kernel.approval_request where id = :i for update"),
        {"i": str(request_id)}).first()
    if row is None:
        raise NotFound("Approval request not found")
    if row.status != PENDING:
        raise Conflict(f"This request is already {row.status}")
    if row.expires_at is not None and row.expires_at < datetime.now(UTC):
        s.execute(text("update kernel.approval_request set status = 'expired' where id = :i"), {"i": str(row.id)})
        raise Conflict("This request has expired")
    rule = s.execute(text(f"select {_RULE_COLUMNS} from kernel.approval_rule where id = :i"),
                     {"i": str(row.rule_id)}).one()
    if not (ctx.has_role(rule.approver_role_id, company_id=row.company_id)
            and ctx.can("approvals.decide", company_id=row.company_id)):
        raise Forbidden("You do not hold the role that approves this step")
    if rule.forbid_creator and row.requested_by == ctx.user_id:
        raise Forbidden("You cannot approve a request you made (separation of duties)")
    if not approve and not (note and note.strip()):
        raise ValidationFailed("Give a reason for rejecting")

    status = APPROVED if approve else REJECTED
    s.execute(text(
        "update kernel.approval_request set status = :st, decided_by = :u, decided_at = now(), channel = :ch, "
        "note = :n, updated_at = now(), updated_by = :u where id = :i"),
        {"st": status, "u": str(ctx.user_id), "ch": _channel(ctx.channel), "n": note, "i": str(row.id)})
    audit.record(s, "approve" if approve else "reject", "kernel.approval_request", row.id,
                 {"doc_type": row.doc_type, "doc_id": row.doc_id, "step": row.step, "note": note})

    next_rules = _matching_rules(s, row.company_id, row.doc_type, row.amount or Decimal("0"), row.step) \
        if approve else []
    if next_rules:
        _open_request(s, next_rules[0], row.company_id, row.doc_type, row.doc_id, row.amount or Decimal("0"),
                      requested_by=str(row.requested_by) if row.requested_by else None)
    else:
        publish(s, Event(type="approval.decided", aggregate_type=row.doc_type, aggregate_id=row.doc_id,
                         payload={"status": status, "request_id": row.id, "decided_by": ctx.user_id,
                                  "note": note}))
    return get_request(s, row.id)


def _user() -> str | None:
    user_id = get_context().user_id
    return str(user_id) if user_id else None


def _channel(channel: str) -> str:
    return channel if channel in ("web", "pos", "api") else "api"
