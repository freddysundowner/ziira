"""Use cases: accounting periods (monthly) and closing them."""

from datetime import UTC, date, datetime
from uuid import UUID

from ziira.modules.finance.domain import periods
from ziira.modules.finance.permissions import PERIOD_CLOSE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Period
from ziira.modules.finance.services.access import require_visible
from ziira.modules.finance.services.books import ensure_books, get_or_create_period
from ziira.sdk import Event, NotFound, Session, ValidationFailed, audit_record, check_company, current_context, publish


def list_periods(session: Session, company_id: UUID) -> list[Period]:
    """The company's accounting periods so far (a period is created when something is first posted into its month)."""
    require_visible(company_id)
    return finance_repo.list_periods(session, company_id)


def open_period(session: Session, company_id: UUID, day: date) -> Period:
    """Create the monthly period containing a date (if it does not exist). Needs 'period.close' for the company."""
    check_company(session, company_id)
    current_context().require(PERIOD_CLOSE, company_id=company_id)
    ensure_books(session, company_id)
    return get_or_create_period(session, company_id, day)


def closing_problems(session: Session, period: Period) -> list[str]:
    """What stops a period from being closed: the checklist of specification section 07 that exists so far."""
    problems = []
    pending = finance_repo.pending_manuals_in(session, period.company_id, period.start_date, period.end_date)
    if pending:
        problems.append(f"{pending} manual journal(s) dated in this period are waiting for approval")
    problems.extend(_subledger_problems(session, period))
    return problems


def _subledger_problems(session: Session, period: Period) -> list[str]:
    """Sub-ledgers must equal their control accounts: today the stock ledger against the inventory accounts."""
    from sqlalchemy import text

    enabled = session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'inventory' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first()
    if enabled is None:
        return []
    from ziira.modules.inventory.public import stock_value_as_of

    stock = stock_value_as_of(session, period.company_id, period.end_date)
    books = finance_repo.balance_by_subtype_until(session, period.company_id, ["inventory", "inventory_in_transit"],
                                                  period.end_date)
    if stock != books:
        return [f"The stock ledger is worth {stock} at the end of the period but the inventory accounts show {books}"]
    return []


def period_checklist(session: Session, period_id: UUID) -> list[str]:
    """The problems that stop a period from being closed (empty when it is ready). Needs 'period.close'."""
    period = finance_repo.get_period(session, period_id)
    if period is None:
        raise NotFound("Period not found")
    current_context().require(PERIOD_CLOSE, company_id=period.company_id)
    return closing_problems(session, period)


def change_status(session: Session, period_id: UUID, new_status: str) -> Period:
    """Close (soft), lock or reopen a period. Closing checks the period-close checklist first. Needs 'period.close'."""
    period = finance_repo.get_period(session, period_id, lock=True)
    if period is None:
        raise NotFound("Period not found")
    ctx = current_context()
    can_close = ctx.can(PERIOD_CLOSE, company_id=period.company_id)
    periods.check_status_change(period.status, new_status, can_close=can_close)
    if period.status == periods.OPEN and new_status == periods.SOFT_CLOSED:
        problems = closing_problems(session, period)
        if problems:
            raise ValidationFailed("The period cannot be closed yet: " + "; ".join(problems))
    before = period.status
    period.status = new_status
    if new_status == periods.OPEN:
        period.closed_by, period.closed_at = None, None
    else:
        period.closed_by, period.closed_at = ctx.user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "status", "finance.period", period.id,
                 {"from": before, "to": new_status, "start": period.start_date, "end": period.end_date})
    if new_status != periods.OPEN:
        publish(session, Event("period.closed", "finance.period", period.id, {
            "company_id": period.company_id, "start_date": period.start_date, "end_date": period.end_date,
            "status": new_status}))
    return period
