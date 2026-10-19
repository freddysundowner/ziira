"""Personal trainers: what each is paid per session and the sessions they delivered.

A trainer is whatever the business calls the person in its calendar (a Bookings resource, or a user): Memberships only
keeps the reference, the name to show and the rate. When a session is completed (Bookings publishes
`appointment.completed`), the trainer's earning is written once; payroll reads the figures, nothing here pays anyone.
A fixed rate pays the same for every session; a percent rate pays a share of what the session was worth."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.permissions import MANAGE, PLANS, REPORTS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Forbidden, Session, ValidationFailed, audit_record, check_company, current_context

CENT = Decimal("0.01")


def set_rate(session: Session, *, company_id: UUID, trainer_ref: UUID, trainer_name: str, basis: str,
             amount: Decimal, service_ref: str | None = None) -> repo.Row:
    """Set what a trainer is paid per session, for one service or for all (the earlier rate for the same trainer and
    service is retired, not erased). Needs 'memberships.plans'."""
    common.require(PLANS, company_id)
    check_company(session, company_id)
    if basis not in ("fixed", "percent"):
        raise ValidationFailed("A rate is a fixed amount or a percent")
    if amount < 0 or (basis == "percent" and amount > 100):
        raise ValidationFailed("A percent is between 0 and 100")
    name = " ".join(trainer_name.split())[:200]
    if not name:
        raise ValidationFailed("Name the trainer")
    ref = (service_ref or "").strip()[:100] or None
    repo.run(session, "update memberships.trainer_rate set status = 'retired', updated_at = now() "
                      "where company_id = :c and trainer_ref = :t and coalesce(service_ref, '') = coalesce(:s, '') "
                      "and status = 'active'", c=company_id, t=trainer_ref, s=ref)
    ctx = current_context()
    row = repo.insert(session, "trainer_rate", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "trainer_ref": trainer_ref,
        "trainer_name": name, "service_ref": ref, "basis": basis, "amount": amount})
    audit_record(session, "set", "memberships.trainer_rate", row["id"], {"trainer": name, "basis": basis,
                                                                           "amount": str(amount)})
    return row


def list_rates(session: Session, company_id: UUID, active_only: bool = True) -> list[repo.Row]:
    common.check_visible(company_id, None, "Company")
    return repo.many(session, "select * from memberships.trainer_rate where company_id = :c "
                              "and (not :a or status = 'active') order by trainer_name, service_ref nulls first",
                     c=company_id, a=active_only)


def rate_for(session: Session, company_id: UUID, trainer_ref: UUID, service_ref: str | None) -> repo.Row | None:
    """The trainer's rate for the service, else their general rate."""
    return repo.one(session, "select * from memberships.trainer_rate where company_id = :c and trainer_ref = :t "
                             "and status = 'active' and (service_ref is null or service_ref = :s) "
                             "order by (service_ref is null) limit 1", c=company_id, t=trainer_ref, s=service_ref)


def record_session(session: Session, *, company_id: UUID, branch_id: UUID | None, trainer_ref: UUID,
                   customer_id: UUID | None, service_ref: str | None, source_type: str, source_id: UUID,
                   session_value: Decimal, earned_on: date) -> repo.Row | None:
    """Write what the trainer earns for a delivered session, once per (source, trainer). No rate: nothing is written.
    The caller has checked access (an event handler, a desk screen)."""
    rate = rate_for(session, company_id, trainer_ref, service_ref)
    if rate is None:
        return None
    found = repo.one(session, "select * from memberships.trainer_earning where source_type = :t and source_id = :s "
                              "and trainer_ref = :r", t=source_type, s=source_id, r=trainer_ref)
    if found is not None:
        return found
    amount = (Decimal(rate["amount"]) if rate["basis"] == "fixed"
              else (session_value * Decimal(rate["amount"]) / 100).quantize(CENT, rounding=ROUND_HALF_UP))
    ctx = current_context()
    row = repo.insert(session, "trainer_earning", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "trainer_ref": trainer_ref, "trainer_name": rate["trainer_name"], "customer_id": customer_id,
        "service_ref": service_ref, "source_type": source_type, "source_id": source_id,
        "session_value": session_value, "amount": amount, "basis": rate["basis"], "earned_on": earned_on})
    return row


def reverse_session(session: Session, source_type: str, source_id: UUID, note: str | None = None) -> int:
    """The session did not happen after all: its earnings are marked reversed (kept, not erased)."""
    return repo.run(session, "update memberships.trainer_earning set status = 'reversed', note = :n, updated_at = now() "  # noqa: E501
                             "where source_type = :t and source_id = :s and status = 'earned'",
                    t=source_type, s=source_id, n=(note or "").strip()[:300] or None)


def earnings(session: Session, *, company_id: UUID, start: date, end: date,
             trainer_ref: UUID | None = None) -> list[dict[str, Any]]:
    """Per trainer: sessions and what they earned between two dates. Needs the reports or manage right."""
    common.check_visible(company_id, None, "Company")
    for permission in (REPORTS, MANAGE, PLANS):
        companies = current_context().companies_with(permission)
        if companies is None or company_id in companies:
            break
    else:
        raise Forbidden("You need the reports right to see what trainers earn")
    return repo.many(
        session,
        "select trainer_ref, trainer_name, count(*) filter (where status <> 'reversed') as sessions, "
        "coalesce(sum(amount) filter (where status <> 'reversed'), 0) as earned, "
        "coalesce(sum(amount) filter (where status = 'paid'), 0) as paid, "
        "coalesce(sum(session_value) filter (where status <> 'reversed'), 0) as session_value "
        "from memberships.trainer_earning where company_id = :c and earned_on between :s and :e "
        "and (cast(:t as uuid) is null or trainer_ref = :t) group by trainer_ref, trainer_name order by trainer_name",
        c=company_id, s=start, e=end, t=trainer_ref)


def earning_rows(session: Session, *, company_id: UUID, start: date, end: date, trainer_ref: UUID,
                 limit: int = 200) -> list[repo.Row]:
    common.check_visible(company_id, None, "Company")
    return repo.many(session, "select * from memberships.trainer_earning where company_id = :c and trainer_ref = :t "
                              "and earned_on between :s and :e order by earned_on desc, created_at desc limit :l",
                     c=company_id, t=trainer_ref, s=start, e=end, l=min(limit, 500))


def mark_paid(session: Session, *, company_id: UUID, trainer_ref: UUID, through: date) -> int:
    """After payroll paid the trainer: mark earnings up to a date as paid. Needs 'memberships.plans'."""
    common.require(PLANS, company_id)
    today = common.today(session, company_id)
    n = repo.run(session, "update memberships.trainer_earning set status = 'paid', paid_on = :p, updated_at = now() "
                         "where company_id = :c and trainer_ref = :t and status = 'earned' and earned_on <= :d",
                 c=company_id, t=trainer_ref, d=through, p=today)
    audit_record(session, "pay", "memberships.trainer_earning", None, {"trainer": str(trainer_ref), "rows": n})
    return n
