"""Use cases: recurring invoices for any customer.

A schedule says: this customer, these lines, every so often, from this date, until this end. A recurring task issues the
invoice of each period that is due, exactly once (see billing.py); with `mode = draft` it leaves the invoice for a
person to review and issue. A schedule that was paused skips the periods it was paused for."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.domain import periods, rules
from ziira.modules.memberships.permissions import RECURRING
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import billing, common
from ziira.sdk import Conflict, Session, ValidationFailed, audit_record, check_company, current_context


def line_dicts(lines: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The lines as stored: text values (so money never passes through a float)."""
    if not lines:
        raise ValidationFailed("A recurring invoice has at least one line")
    made = []
    for line in lines:
        quantity, price = Decimal(str(line["quantity"])), Decimal(str(line["unit_price"]))
        discount = Decimal(str(line.get("discount") or 0))
        if quantity <= 0 or price < 0 or discount < 0:
            raise ValidationFailed("Quantities must be above zero and prices cannot be negative")
        words = " ".join(str(line.get("description") or "").split())[:300]
        made.append({"product_id": str(line["product_id"]), "description": words, "quantity": str(quantity),
                     "unit_price": str(price), "discount": str(discount)})
    return made


def schedule_total(lines: list[dict[str, str]]) -> Decimal:
    return sum((rules.line_total(Decimal(x["quantity"]), Decimal(x["unit_price"]), Decimal(x["discount"]))
                for x in lines), Decimal(0))


def with_total(row: repo.Row) -> repo.Row:
    return {**row, "total": schedule_total(row["lines"])}


def _geometry(row: repo.Row) -> dict[str, Any]:
    return {"first": row["start_date"], "interval": row["billing_interval"], "count": row["interval_count"],
            "anchor_day": row["anchor_day"]}


def create_schedule(session: Session, *, company_id: UUID, branch_id: UUID, customer_id: UUID, name: str,
                    lines: list[dict[str, Any]], billing_interval: str, start_date: date, interval_count: int = 1,
                    anchor_day: int | None = None, end_date: date | None = None, max_runs: int | None = None,
                    mode: str = "issue", due_days: int | None = None, memo: str | None = None,
                    for_customer_id: UUID | None = None, for_label: str | None = None) -> repo.Row:
    """Set up a recurring invoice. `customer_id` is who is billed (a parent, a company); `for_customer_id` and
    `for_label` say whom or what it is for (a learner, a locker). Needs 'recurring.manage' at the branch."""
    common.require(RECURRING, company_id, branch_id)
    return make_schedule(session, company_id=company_id, branch_id=branch_id, customer_id=customer_id, name=name,
                         lines=lines, billing_interval=billing_interval, start_date=start_date,
                         interval_count=interval_count, anchor_day=anchor_day, end_date=end_date, max_runs=max_runs,
                         mode=mode, due_days=due_days, memo=memo, for_customer_id=for_customer_id,
                         for_label=for_label)


def make_schedule(session: Session, *, company_id: UUID, branch_id: UUID, customer_id: UUID, name: str,
                  lines: list[dict[str, Any]], billing_interval: str, start_date: date, interval_count: int = 1,
                  anchor_day: int | None = None, end_date: date | None = None, max_runs: int | None = None,
                  mode: str = "issue", due_days: int | None = None, memo: str | None = None,
                  for_customer_id: UUID | None = None, for_label: str | None = None) -> repo.Row:
    """Set up a recurring invoice for a caller that has checked its own permission (a locker rented at the desk)."""
    check_company(session, company_id, branch_id)
    common.customer_of(session, company_id, customer_id)
    stored = line_dicts(lines)
    for line in stored:
        common.check_product(session, company_id, UUID(line["product_id"]), service_only=False)
    if billing_interval not in periods.INTERVALS:
        raise ValidationFailed("Choose week, month, quarter or year")
    if end_date is not None and end_date < start_date:
        raise ValidationFailed("The end date is before the start date")
    if for_customer_id is not None:
        common.customer_of_any(session, for_customer_id)
    ctx = current_context()
    row = repo.insert(session, "schedule", {
        "for_customer_id": for_customer_id, "for_label": (for_label or "").strip()[:200] or None,
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "customer_id": customer_id, "name": rules.clean_name(name), "lines": stored,
        "billing_interval": billing_interval, "interval_count": interval_count,
        "anchor_day": anchor_day if billing_interval != "week" else None, "start_date": start_date, "next_index": 0,
        "next_run": start_date, "end_date": end_date, "max_runs": max_runs, "mode": mode, "due_days": due_days,
        "memo": (memo or "").strip()[:300] or None})
    audit_record(session, "create", "memberships.schedule", row["id"], {"customer_id": str(customer_id)})
    return with_total(row)


UPDATABLE = ("name", "lines", "end_date", "max_runs", "mode", "due_days", "memo", "branch_id")


def update_schedule(session: Session, schedule_id: UUID, **changes: Any) -> repo.Row:
    """Change what future periods invoice (periods already invoiced are not touched). Needs 'recurring.manage'."""
    row = common.get_row(session, "schedule", schedule_id, "Recurring invoice", lock=True)
    common.require(RECURRING, row["company_id"], row["branch_id"])
    if row["status"] == "ended":
        raise Conflict("This recurring invoice has ended")
    values = {k: v for k, v in changes.items() if k in UPDATABLE}
    if "lines" in values:
        values["lines"] = line_dicts(values["lines"])
        for line in values["lines"]:
            common.check_product(session, row["company_id"], UUID(line["product_id"]), service_only=False)
    if "name" in values:
        values["name"] = rules.clean_name(str(values["name"]))
    if "branch_id" in values:
        check_company(session, row["company_id"], values["branch_id"])
        common.require(RECURRING, row["company_id"], values["branch_id"])
    end = values.get("end_date", row["end_date"])
    if end is not None and end < row["start_date"]:
        raise ValidationFailed("The end date is before the start date")
    saved = repo.update(session, "schedule", schedule_id, {**values, "updated_by": current_context().user_id})
    audit_record(session, "update", "memberships.schedule", schedule_id, {k: str(v) for k, v in values.items()})
    return with_total(_settle(session, saved))


def _settle(session: Session, row: repo.Row) -> repo.Row:
    """End the schedule when no further period can be due."""
    if row["status"] != "ended" and periods.schedule_finished(
            **_geometry(row), next_index=row["next_index"], end_date=row["end_date"], max_runs=row["max_runs"]):
        return repo.update(session, "schedule", row["id"], {"status": "ended"})
    return row


def list_schedules(session: Session, *, company_id: UUID | None = None, customer_id: UUID | None = None,
                   status: str | None = None, limit: int = 50, offset: int = 0) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes())
    rows = repo.many(
        session,
        f"select * from memberships.schedule where {clause} and (cast(:c as uuid) is null or company_id = :c) "
        "and (cast(:cu as uuid) is null or customer_id = :cu) and (cast(:s as text) is null or status = :s) "
        "order by status, next_run limit :l offset :o", c=company_id, cu=customer_id, s=status,
        l=min(limit, 200), o=offset, **params)
    return [with_total(r) for r in rows]


def get_schedule(session: Session, schedule_id: UUID) -> repo.Row:
    return with_total(common.get_row(session, "schedule", schedule_id, "Recurring invoice"))


def pause(session: Session, schedule_id: UUID, resume_on: date | None = None) -> repo.Row:
    """Stop invoicing until `resume_on` (or until someone resumes it). Periods that start while paused are not invoiced
    afterwards. Needs 'recurring.manage'."""
    row = common.get_row(session, "schedule", schedule_id, "Recurring invoice", lock=True)
    common.require(RECURRING, row["company_id"], row["branch_id"])
    if row["status"] != "active":
        raise Conflict("Only an active recurring invoice can be paused")
    if resume_on is not None and resume_on <= common.today(session, row["company_id"]):
        raise ValidationFailed("The resume date must be in the future")
    saved = repo.update(session, "schedule", schedule_id, {"status": "paused", "resume_on": resume_on})
    audit_record(session, "pause", "memberships.schedule", schedule_id, {"resume_on": str(resume_on)})
    return with_total(saved)


def resume(session: Session, schedule_id: UUID, *, today: date | None = None) -> repo.Row:
    """Start invoicing again from the next period that starts today or later. Needs 'recurring.manage'."""
    row = common.get_row(session, "schedule", schedule_id, "Recurring invoice", lock=True)
    common.require(RECURRING, row["company_id"], row["branch_id"])
    if row["status"] != "paused":
        raise Conflict("This recurring invoice is not paused")
    return with_total(_resume(session, row, today or common.today(session, row["company_id"])))


def _resume(session: Session, row: repo.Row, day: date) -> repo.Row:
    index = row["next_index"]
    while periods.nth_start(row["start_date"], row["billing_interval"], row["interval_count"], row["anchor_day"],
                            index) < day and index < row["next_index"] + periods.MAX_PERIODS_LOOKED_AT:
        index += 1
    saved = repo.update(session, "schedule", row["id"], {
        "status": "active", "resume_on": None, "next_index": index,
        "next_run": periods.nth_start(row["start_date"], row["billing_interval"], row["interval_count"],
                                      row["anchor_day"], index)})
    audit_record(session, "resume", "memberships.schedule", row["id"], {"next_run": str(saved["next_run"])})
    return _settle(session, saved)


def end(session: Session, schedule_id: UUID) -> repo.Row:
    """End a recurring invoice for good (invoices already issued stay). Needs 'recurring.manage'."""
    row = common.get_row(session, "schedule", schedule_id, "Recurring invoice", lock=True)
    common.require(RECURRING, row["company_id"], row["branch_id"])
    saved = repo.update(session, "schedule", schedule_id, {"status": "ended", "resume_on": None})
    audit_record(session, "end", "memberships.schedule", schedule_id, None)
    return with_total(saved)


def run_due(session: Session, schedule_id: UUID, today: date | None = None) -> repo.Row:
    """Invoice the periods of a schedule that are due on `today` (default: the company's today). Exactly once each: the
    same period is never invoiced twice, however often this runs. The recurring task and the 'run now' button use it."""
    row = repo.get(session, "schedule", schedule_id, lock=True)
    if row is None:
        raise ValidationFailed("Recurring invoice not found")
    day = today or common.today(session, row["company_id"])
    if row["status"] == "paused" and row["resume_on"] is not None and row["resume_on"] <= day:
        row = _resume(session, row, day)
    if row["status"] != "active":
        return with_total(row)
    settings = repo.get_settings(session, row["company_id"])
    due = periods.due_periods(**_geometry(row), next_index=row["next_index"], today=day, end_date=row["end_date"],
                              max_runs=row["max_runs"], max_catch_up=int(settings["catch_up_max_periods"]))
    last: repo.Row | None = None
    next_index = row["next_index"]
    for period in due.skipped:
        last = billing.skip_period(
            session, owner_type="schedule", owner_id=row["id"], company_id=row["company_id"],
            branch_id=row["branch_id"], customer_id=row["customer_id"], period_start=period.start,
            period_end=period.end, message=f"{row['name']}: the period starting {period.start} was not invoiced "
                                           "because more periods were missed than the company allows catching up")
        next_index = period.index + 1
    for period in due.issue:
        last = billing.bill_period(
            session, owner_type="schedule", owner_id=row["id"], company_id=row["company_id"],
            branch_id=row["branch_id"], customer_id=row["customer_id"], period_start=period.start,
            period_end=period.end, lines=row["lines"], due_days=row["due_days"], memo=row["memo"],
            review=row["mode"] == "draft", for_customer_id=row["for_customer_id"], for_label=row["for_label"])
        if last["status"] == "failed":
            break                                       # the same period is tried again at the next run
        next_index = period.index + 1
    values: repo.Row = {"next_index": next_index, "next_run": periods.nth_start(
        row["start_date"], row["billing_interval"], row["interval_count"], row["anchor_day"], next_index)}
    if last is not None:
        values.update({"last_run_at": repo.scalar(session, "select now()"), "last_run_status": last["status"],
                       "last_run_message": last["message"], "last_invoice_number": last["invoice_number"]
                       if last["status"] == "issued" else row["last_invoice_number"]})
    return with_total(_settle(session, repo.update(session, "schedule", row["id"], values)))


def run_now(session: Session, schedule_id: UUID) -> repo.Row:
    """Run a schedule's due periods now instead of waiting for the next hourly run. Needs 'recurring.manage'."""
    row = common.get_row(session, "schedule", schedule_id, "Recurring invoice")
    common.require(RECURRING, row["company_id"], row["branch_id"])
    return run_due(session, schedule_id)
