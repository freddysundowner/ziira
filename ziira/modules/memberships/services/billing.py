"""Invoicing one period of a schedule, membership or package exactly once.

`invoice_run` has one row per (owner, period start). The row is the lock and the record: a period already issued,
waiting for review, skipped or discarded is never invoiced again; a failed one is tried again by the next run, and
every failure is put in the exceptions inbox, never silently skipped."""

from datetime import date
from uuid import UUID, uuid4

from ziira.modules.memberships.permissions import MANAGE, RECURRING
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, invoicing, values
from ziira.sdk import (
    Conflict,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    flag_for_review,
)

MAX_AUTO_ATTEMPTS = 5
SETTLED = ("issued", "pending_review", "skipped", "discarded")


def _flag(session: Session, run: repo.Row, message: str, kind: str = "recurring_invoice_failed") -> None:
    flag_for_review(session, unit="memberships", kind=kind, severity="medium", company_id=run["company_id"],
                    branch_id=run["branch_id"], ref_type="memberships.invoice_run", ref_id=run["id"],
                    message=message[:500], dedupe_key=f"memberships-run:{run['id']}:{kind}")


def _issue(session: Session, run: repo.Row, *, raise_on_error: bool = False) -> repo.Row:
    """Try to issue the invoice of a run. A failure is recorded on the run and flagged (or raised)."""
    try:
        with session.begin_nested():
            invoice = invoicing.issue(
                session, company_id=run["company_id"], branch_id=run["branch_id"], customer_id=run["customer_id"],
                lines=run["lines"], run_id=run["id"], due_days=run["due_days"], memo=run["memo"],
                issue_date=common.today(session, run["company_id"]))
    except Exception as error:  # noqa: BLE001 - recorded and flagged below, or raised for a person at the screen
        if raise_on_error:
            raise
        message = str(error) or type(error).__name__
        failed = repo.update(session, "invoice_run", run["id"], {
            "status": "failed", "attempts": run["attempts"] + 1, "message": message[:500]})
        _flag(session, failed, f"An invoice could not be issued for the period starting {run['period_start']}: "
                               f"{message}")
        return failed
    return repo.update(session, "invoice_run", run["id"], {
        "status": "issued", "attempts": run["attempts"] + 1, "invoice_id": invoice.id,
        "invoice_number": invoice.number, "total": invoice.total, "message": None, "due_date": invoice.due_date,
        "outstanding": invoice.total, "settle_state": "open"})


def bill_period(session: Session, *, owner_type: str, owner_id: UUID, company_id: UUID, branch_id: UUID,
                customer_id: UUID, period_start: date, period_end: date | None, lines: list[dict[str, str]],
                due_days: int | None, memo: str | None, review: bool = False,
                raise_on_error: bool = False, credit_eligible: bool = True, voucher_code: str | None = None,
                for_customer_id: UUID | None = None, for_label: str | None = None) -> repo.Row:
    """Invoice a period once. `review` leaves the invoice as a draft for a person to issue. Asking again returns the
    run that already exists (a failed one is tried again, unless it has failed too many times)."""
    ctx = current_context()
    repo.one(session, "select cast(pg_advisory_xact_lock(hashtextextended(:k, 0)) as text) as x",
             k=f"run:{owner_type}:{owner_id}:{period_start}")
    run = repo.one(session, "select * from memberships.invoice_run where owner_type = :t and owner_id = :o "
                            "and period_start = :p for update", t=owner_type, o=owner_id, p=period_start)
    if run is None:
        run_id = uuid4()
        if credit_eligible:
            lines = values.apply_credit_to_lines(session, company_id=company_id, customer_id=customer_id, lines=lines,
                                                 source_id=run_id, period_start=period_start,
                                                 voucher_code=voucher_code)
        run = repo.insert(session, "invoice_run", {
            "id": run_id, "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id,
            "branch_id": branch_id, "customer_id": customer_id, "owner_type": owner_type, "owner_id": owner_id,
            "period_start": period_start, "period_end": period_end, "status": "failed", "lines": lines,
            "due_days": due_days, "memo": memo, "for_customer_id": for_customer_id, "for_label": for_label})
    elif run["status"] in SETTLED or run["attempts"] >= MAX_AUTO_ATTEMPTS and not raise_on_error:
        return run
    if review:
        return repo.update(session, "invoice_run", run["id"], {"status": "pending_review", "message": None})
    return _issue(session, run, raise_on_error=raise_on_error)


def skip_period(session: Session, *, owner_type: str, owner_id: UUID, company_id: UUID, branch_id: UUID,
                customer_id: UUID, period_start: date, period_end: date | None, message: str) -> repo.Row:
    """Record a period that was not invoiced because too many were missed (flagged for a person to look at)."""
    ctx = current_context()
    run = repo.one(session, "select * from memberships.invoice_run where owner_type = :t and owner_id = :o "
                            "and period_start = :p", t=owner_type, o=owner_id, p=period_start)
    if run is not None:
        return run
    run = repo.insert(session, "invoice_run", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "customer_id": customer_id, "owner_type": owner_type, "owner_id": owner_id, "period_start": period_start,
        "period_end": period_end, "status": "skipped", "lines": [], "message": message[:500]})
    _flag(session, run, message, kind="recurring_period_skipped")
    return run


# --------------------------------------------------------------------------- people reviewing runs
def _run_for_person(session: Session, run_id: UUID) -> repo.Row:
    run = common.get_row(session, "invoice_run", run_id, "Invoice run", lock=True)
    common.require(RECURRING if run["owner_type"] == "schedule" else MANAGE, run["company_id"], run["branch_id"])
    return run


def list_runs(session: Session, *, company_id: UUID | None = None, status: str | None = None,
              owner_id: UUID | None = None, customer_id: UUID | None = None, limit: int = 50,
              offset: int = 0) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes())
    return repo.many(
        session,
        f"select * from memberships.invoice_run where {clause} and (cast(:c as uuid) is null or company_id = :c) "
        "and (cast(:s as text) is null or status = :s) and (cast(:o as uuid) is null or owner_id = :o) "
        "and (cast(:cu as uuid) is null or customer_id = :cu) order by period_start desc, created_at desc "
        "limit :l offset :off", c=company_id, s=status, o=owner_id, cu=customer_id, l=min(limit, 200), off=offset,
        **params)


def get_run(session: Session, run_id: UUID) -> repo.Row:
    return common.get_row(session, "invoice_run", run_id, "Invoice run")


def issue_run(session: Session, run_id: UUID) -> repo.Row:
    """Issue the invoice of a draft (or retry a failed one). Needs 'recurring.manage' (memberships.manage for a
    membership or package)."""
    run = _run_for_person(session, run_id)
    if run["status"] not in ("pending_review", "failed"):
        raise Conflict("This invoice has already been dealt with")
    issued = _issue(session, run, raise_on_error=True)
    audit_record(session, "issue", "memberships.invoice_run", run_id, {"invoice": issued["invoice_number"]})
    after_issue(session, issued)
    return issued


def after_issue(session: Session, run: repo.Row) -> None:
    """Show the result on the schedule the run belongs to."""
    if run["owner_type"] == "schedule":
        repo.update(session, "schedule", run["owner_id"], {
            "last_run_at": repo.scalar(session, "select now()"), "last_run_status": run["status"],
            "last_run_message": run["message"], "last_invoice_number": run["invoice_number"]})


def discard_run(session: Session, run_id: UUID, note: str | None = None) -> repo.Row:
    """Throw away a draft (or a failed run) without invoicing the period. Needs 'recurring.manage'."""
    run = _run_for_person(session, run_id)
    if run["status"] not in ("pending_review", "failed"):
        raise Conflict("This invoice has already been dealt with")
    why = (note or "").strip()
    if not why:
        raise ValidationFailed("Say why the period is not invoiced")
    discarded = repo.update(session, "invoice_run", run_id, {"status": "discarded", "message": why[:300]})
    values.release(session, source_type="memberships.run", source_id=run_id)
    audit_record(session, "discard", "memberships.invoice_run", run_id, {"note": why})
    after_issue(session, discarded)
    return discarded

