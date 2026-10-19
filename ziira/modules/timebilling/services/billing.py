"""Use cases: invoicing approved time and expenses.

    draft review (built from approved work, the work is set aside) -> edit lines / rounding / grouping -> issue
        issue: one invoice through POS's invoice service (numbering, tax, credit limit, events, posting all apply);
               the entries and expenses are marked invoiced with the invoice; milestones become invoiced;
               retainer top-ups add to the balance.
        discard: everything set aside comes back as unbilled work.
        invoice cancelled in POS (event `invoice.cancelled`): the work is released and can be invoiced again.

The invoice service wants tax-inclusive prices. A company whose rates are tax-exclusive (the default) has each line
grossed up at its service item's tax rate; a line is always sent as quantity 1 at the line's amount, with the hours and
rate in its wording, so the invoice total equals the review's figures exactly.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text

from ziira.modules.timebilling.domain import billing as rules
from ziira.modules.timebilling.domain.timesheet import hours
from ziira.modules.timebilling.permissions import TIME_BILL, TIME_PARTNER
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import (
    Entry,
    Expense,
    InvoiceBatch,
    InvoiceBatchLine,
    Milestone,
    Project,
    Retainer,
)
from ziira.modules.timebilling.services import access, common, notify, retainers
from ziira.modules.timebilling.services import settings as settings_service
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    flag_for_review,
    publish,
)

SOURCE_TYPE = "timebilling.invoice_batch"


@dataclass
class BatchView:
    batch: InvoiceBatch
    lines: list[InvoiceBatchLine]
    client_name: str
    net_total: Decimal
    estimated_tax: Decimal
    problems: list[str]
    problem_items: list[tuple[str, int | None]]       # (code, line number): the same problems for a screen to translate
    write_down: Decimal = Decimal(0)                  # what was worked but is billed for less (lines' list - amount)
    review_needed: bool = False                       # a partner has to look before this can be issued


# --------------------------------------------------------------------------- reading
def _scope_check(batch: InvoiceBatch) -> None:
    if not current_context().can(TIME_BILL, company_id=batch.company_id, branch_id=batch.branch_id):
        raise NotFound("Invoice review not found")


def get_batch(session: Session, batch_id: UUID, *, lock: bool = False) -> InvoiceBatch:
    batch = repo.get(session, InvoiceBatch, batch_id, lock=lock)
    if batch is None:
        raise NotFound("Invoice review not found")
    _scope_check(batch)
    return batch


def _vat(session: Session, product_id: UUID | None) -> Decimal:
    if product_id is None:
        return Decimal(0)
    from ziira.modules.products.public import find_product

    product = find_product(session, product_id)
    return product.vat_rate if product else Decimal(0)


def _needs_partner(setting: Any, net: Decimal) -> bool:
    return bool(setting.partner_review) and net > Decimal(setting.partner_review_above or 0)


def view_batch(session: Session, batch_id: UUID) -> BatchView:
    batch = get_batch(session, batch_id)
    lines = repo.batch_lines(session, batch.id)
    setting = common.settings(session, batch.company_id)
    net = sum((x.amount for x in lines), Decimal(0))
    gross = sum((rules.gross_amount(x.amount, _vat(session, x.service_product_id), setting.rates_include_tax)
                 for x in lines), Decimal(0))
    items: list[tuple[str, int | None]] = []
    for x in lines:
        if x.kind == "time" and x.rate is None:
            items.append(("no_rate", x.line_no))
        if x.service_product_id is None:
            items.append(("no_service", x.line_no))
    needed = _needs_partner(setting, net) and batch.review_status != "approved" and not current_context().can(
        TIME_PARTNER, company_id=batch.company_id, branch_id=batch.branch_id)
    if needed and batch.status == "draft":
        items.append(("partner_review", None))
    if batch.status == "draft":
        items += [("over_cap", None) for _ in _cap_breaches(session, batch, lines)]
    problems = [PROBLEMS[code].format(n=n) for code, n in items]
    names = common.customer_names(session, {batch.client_id})
    down = sum((max((x.list_amount if x.list_amount is not None else x.amount) - x.amount, Decimal(0))
                for x in lines), Decimal(0))
    return BatchView(batch, lines, names.get(batch.client_id, ""), net, gross - net, problems, items, down, needed)


PROBLEMS = {
    "no_rate": "Line {n} has no rate",
    "no_service": "Line {n} has no service item to invoice under",
    "partner_review": "A partner has to review this invoice before it goes out",
    "over_cap": "This would bill more than the project's fee cap",
}


def list_batches(session: Session, *, company_id: UUID | None = None, client_id: UUID | None = None,
                 status: str | None = None, limit: int = 50, offset: int = 0) -> list[InvoiceBatch]:
    q = select(InvoiceBatch).where(repo.in_scope(access.scopes_for(TIME_BILL), InvoiceBatch.company_id,
                                                 InvoiceBatch.branch_id))
    if company_id:
        q = q.where(InvoiceBatch.company_id == company_id)
    if client_id:
        q = q.where(InvoiceBatch.client_id == client_id)
    if status:
        q = q.where(InvoiceBatch.status == status)
    return list(session.scalars(q.order_by(InvoiceBatch.created_at.desc()).limit(min(limit, 200)).offset(offset)))


# --------------------------------------------------------------------------- building a review
def _service_for(project: Project | None, setting: Any, *, expense: bool = False) -> UUID | None:
    if expense and setting.expense_product_id:
        return setting.expense_product_id  # type: ignore[no-any-return]
    if project is not None and project.service_product_id:
        return project.service_product_id
    return setting.service_product_id  # type: ignore[no-any-return]


def _branch_for(session: Session, company_id: UUID, projects: list[Project], branch_id: UUID | None) -> UUID:
    if branch_id is not None:
        check_company(session, company_id, branch_id)
        return branch_id
    branches = {p.branch_id for p in projects if p.branch_id}
    if len(branches) == 1:
        return next(iter(branches))
    found = list(session.execute(text("select id from kernel.branch where company_id = :c order by code"),
                                 {"c": str(company_id)}).scalars())
    if len(found) == 1:
        return UUID(str(found[0]))
    raise ValidationFailed("Choose the branch that issues this invoice")


def create_draft(session: Session, *, company_id: UUID, client_id: UUID, project_id: UUID | None = None,
                 branch_id: UUID | None = None, group_by: str | None = None, date_to: date | None = None,
                 include_expenses: bool = True, include_milestones: bool = True,
                 memo: str | None = None) -> BatchView:
    """Set aside a client's approved, unbilled time and expenses (and ready milestones) as an invoice review. Needs
    'time.bill'. Nothing is invoiced yet: the review can be edited, then issued or discarded."""
    ctx = current_context()
    check_company(session, company_id)
    setting = common.settings(session, company_id)
    group = group_by or setting.default_group_by
    if group not in rules.GROUPINGS:
        raise ValidationFailed(f"Group by one of: {', '.join(rules.GROUPINGS)}")
    q = select(Project).where(Project.company_id == company_id, Project.client_id == client_id)
    if project_id:
        q = q.where(Project.id == project_id)
    projects = list(session.scalars(q))
    if not projects:
        raise ValidationFailed("This client has no projects")
    by_id = {p.id: p for p in projects}
    branch = _branch_for(session, company_id, projects, branch_id)
    ctx.require(TIME_BILL, company_id=company_id, branch_id=branch)
    batch = InvoiceBatch(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch,
                         client_id=client_id, project_id=project_id, group_by=group,
                         round_minutes=setting.invoice_round_minutes, memo=(memo or "").strip()[:500] or None)
    terms = settings_service.get_client_terms(session, company_id, client_id)
    if terms is not None and terms.payment_terms_days is not None:
        batch.due_days = terms.payment_terms_days
    repo.add(session, batch)

    # time (not for fixed-fee projects: their fee is billed by milestone)
    billable_ids = [p.id for p in projects if p.billing_mode != "fixed_fee"]
    entries = list(session.scalars(select(Entry).where(
        Entry.project_id.in_(billable_ids), Entry.status == "approved", Entry.billable.is_(True),
        Entry.invoice_id.is_(None), Entry.batch_id.is_(None), Entry.minutes > Entry.retainer_minutes,
        *([Entry.work_date <= date_to] if date_to else [])).with_for_update()))
    for e in entries:
        e.batch_id = batch.id
    names = common.user_names(session, {e.user_id for e in entries})
    session.flush()
    expenses: list[Expense] = []
    if include_expenses:
        expenses = list(session.scalars(select(Expense).where(
            Expense.project_id.in_(list(by_id)), Expense.status == "approved", Expense.billable.is_(True),
            Expense.invoice_id.is_(None), Expense.batch_id.is_(None),
            *([Expense.expense_date <= date_to] if date_to else [])).with_for_update()))
        for x in expenses:
            x.batch_id = batch.id
    milestones: list[Milestone] = []
    if include_milestones:
        milestones = list(session.scalars(select(Milestone).where(
            Milestone.project_id.in_(list(by_id)), Milestone.status == "ready", Milestone.batch_id.is_(None))
            .with_for_update()))
        for m in milestones:
            m.batch_id = batch.id
    if not entries and not expenses and not milestones:
        raise ValidationFailed("Nothing is ready to invoice for this client: approve some time first")
    session.flush()
    _write_time_lines(session, batch, entries, names, by_id, setting)
    n = len(repo.batch_lines(session, batch.id))
    for x in expenses:
        n += 1
        project = by_id[x.project_id]
        _add_line(session, batch, n, "expense", f"{project.name}: {x.description}"
                  + (f" ({x.reference})" if x.reference else ""), rules.expense_amount(x.amount, x.markup_percent),
                  project, _service_for(project, setting, expense=True), expense_ids=[x.id])
    for m in milestones:
        n += 1
        project = by_id[m.project_id]
        _add_line(session, batch, n, "milestone", f"{project.name}: {m.name}", m.amount, project,
                  _service_for(project, setting), milestone_id=m.id)
    session.flush()
    audit_record(session, "create", "timebilling.invoice_batch", batch.id,
                 {"client_id": client_id, "entries": len(entries), "expenses": len(expenses)})
    return view_batch(session, batch.id)


def _add_line(session: Session, batch: InvoiceBatch, number: int, kind: str, description: str, amount: Decimal,
              project: Project | None, service_id: UUID | None, *, minutes: int | None = None,
              rate: Decimal | None = None, entry_ids: list[UUID] | None = None, expense_ids: list[UUID] | None = None,
              milestone_id: UUID | None = None, retainer_id: UUID | None = None,
              period: str | None = None) -> InvoiceBatchLine:
    line = InvoiceBatchLine(
        tenant_id=batch.tenant_id, created_by=current_context().user_id, batch_id=batch.id, line_no=number, kind=kind,
        project_id=project.id if project else None, description=description[:300], minutes=minutes, rate=rate,
        amount=amount, service_product_id=service_id, entry_ids=entry_ids or [], expense_ids=expense_ids or [],
        milestone_id=milestone_id, retainer_id=retainer_id, period=period, list_amount=amount, list_minutes=minutes)
    session.add(line)
    return line


def _time_description(project: Project, line: rules.TimeLine, rate: Decimal | None) -> str:
    where = f" - {line.label}" if line.label else ""
    when = ""
    if line.dates:
        a, b = line.dates
        when = f" ({a.isoformat()})" if a == b else f" ({a.isoformat()} to {b.isoformat()})"
    priced = f" at {rate}" if rate is not None else ""
    return f"{project.name}{where}: {hours(line.minutes)} h{priced}{when}"


def _write_time_lines(session: Session, batch: InvoiceBatch, entries: list[Entry], names: dict[UUID, str],
                      projects: dict[UUID, Project], setting: Any) -> None:
    """(Re)make the time lines of a review from the entries set aside in it."""
    for old in [x for x in repo.batch_lines(session, batch.id) if x.kind == "time"]:
        session.delete(old)
    session.flush()
    others = repo.batch_lines(session, batch.id)
    number = max((x.line_no for x in others), default=0)
    billable = [rules.BillableEntry(e.id, e.project_id, e.user_id, names.get(e.user_id, ""), e.task or "", e.work_date,
                                    e.minutes - e.retainer_minutes, e.bill_rate, e.note or "") for e in entries]
    for line in rules.build_lines(billable, batch.group_by, batch.round_minutes):
        number += 1
        project = projects[line.project_id]
        _add_line(session, batch, number, "time", _time_description(project, line, line.rate), line.amount, project,
                  _service_for(project, setting), minutes=line.minutes, rate=line.rate, entry_ids=line.entry_ids)
    session.flush()
    _apply_caps(session, batch, projects)
    _renumber(session, batch)


def billed_time(session: Session, project_id: UUID, *, exclude_batch: UUID | None = None) -> Decimal:
    """What time on a project is billed for on live reviews and issued invoices (the cap counts all of it)."""
    q = (select(func.coalesce(func.sum(InvoiceBatchLine.amount), 0)).join(
        InvoiceBatch, InvoiceBatch.id == InvoiceBatchLine.batch_id).where(
        InvoiceBatchLine.project_id == project_id, InvoiceBatchLine.kind == "time",
        InvoiceBatch.status.in_(("draft", "issued"))))
    if exclude_batch is not None:
        q = q.where(InvoiceBatch.id != exclude_batch)
    return Decimal(session.scalar(q) or 0)


def _apply_caps(session: Session, batch: InvoiceBatch, projects: dict[UUID, Project]) -> None:
    """A capped-fee project never bills more than its cap: write the excess down on the newest time lines (with the
    reason 'fee cap', so a person sees why), whatever was worked."""
    for project in projects.values():
        if project.billing_mode != "capped_fee" or project.fee_cap is None:
            continue
        lines = [x for x in repo.batch_lines(session, batch.id) if x.kind == "time" and x.project_id == project.id]
        if not lines:
            continue
        room = project.fee_cap - billed_time(session, project.id, exclude_batch=batch.id)
        downs = rules.cap_write_downs([x.list_amount if x.list_amount is not None else x.amount for x in lines], room)
        for line, down in zip(lines, downs, strict=True):
            if down > 0:
                line.amount = (line.list_amount if line.list_amount is not None else line.amount) - down
                line.write_down_reason, line.automatic = "Fee cap reached", True
    session.flush()


def _cap_breaches(session: Session, batch: InvoiceBatch, lines: list[InvoiceBatchLine]) -> list[UUID]:
    """Capped-fee projects whose time on this review would take the billed total over the cap."""
    out = []
    for pid in {x.project_id for x in lines if x.kind == "time" and x.project_id}:
        project = session.get(Project, pid)
        if project is None or project.billing_mode != "capped_fee" or project.fee_cap is None:
            continue
        mine = sum((x.amount for x in lines if x.kind == "time" and x.project_id == pid), Decimal(0))
        if billed_time(session, pid, exclude_batch=batch.id) + mine > project.fee_cap:
            out.append(pid)
    return out


KIND_ORDER = ("time", "expense", "milestone", "retainer_topup", "retainer_fee", "manual")


def _renumber(session: Session, batch: InvoiceBatch) -> None:
    """Number the lines 1..n with time first, then expenses, milestones, retainer lines and manual lines."""
    lines = sorted(repo.batch_lines(session, batch.id), key=lambda x: (KIND_ORDER.index(x.kind), x.line_no))
    for n, line in enumerate(lines, start=1):
        line.line_no = -n                                   # out of the way of the unique (batch, line) number
    session.flush()
    for line in lines:
        line.line_no = -line.line_no
    session.flush()


def _entries_of(session: Session, batch: InvoiceBatch) -> list[Entry]:
    return list(session.scalars(select(Entry).where(Entry.batch_id == batch.id)))


def _draft(session: Session, batch_id: UUID) -> InvoiceBatch:
    batch = get_batch(session, batch_id, lock=True)
    if batch.status != "draft":
        raise Conflict(f"This review is {batch.status}")
    return batch


def _edited(batch: InvoiceBatch) -> None:
    """Any change to a review takes back a partner's approval: they approved what they saw."""
    if batch.review_status in ("approved", "changes_requested"):
        batch.review_status = "none"
        batch.review_by = batch.review_at = None
    batch.updated_by = current_context().user_id


def update_batch(session: Session, batch_id: UUID, **changes: Any) -> BatchView:
    """Change a draft review: the memo, the payment days, the narrative, how time is grouped or the invoice rounding.
    Changing the grouping or rounding rebuilds the time lines (wording you edited on them is replaced)."""
    batch = _draft(session, batch_id)
    rebuild = False
    if changes.get("group_by") is not None:
        if changes["group_by"] not in rules.GROUPINGS:
            raise ValidationFailed(f"Group by one of: {', '.join(rules.GROUPINGS)}")
        rebuild |= changes["group_by"] != batch.group_by
        batch.group_by = changes["group_by"]
    if changes.get("round_minutes") is not None:
        if changes["round_minutes"] not in (0, 5, 6, 10, 15, 30, 60):
            raise ValidationFailed("Round to 0, 5, 6, 10, 15, 30 or 60 minutes")
        rebuild |= changes["round_minutes"] != batch.round_minutes
        batch.round_minutes = changes["round_minutes"]
    if "memo" in changes:
        batch.memo = (changes["memo"] or "").strip()[:500] or None
    if "narrative" in changes:
        batch.narrative = (changes["narrative"] or "").strip()[:4000] or None
    if "due_days" in changes:
        batch.due_days = changes["due_days"]
    if rebuild:
        entries = _entries_of(session, batch)
        projects = repo.projects_by_ids(session, {e.project_id for e in entries})
        _write_time_lines(session, batch, entries, common.user_names(session, {e.user_id for e in entries}), projects,
                          common.settings(session, batch.company_id))
    _edited(batch)
    session.flush()
    audit_record(session, "update", "timebilling.invoice_batch", batch.id,
                 {k: ("(text)" if k in ("narrative", "memo") else str(v)) for k, v in changes.items()})
    return view_batch(session, batch.id)


def _set_amount(line: InvoiceBatchLine, amount: Decimal, reason: str | None, may_write_off: bool) -> None:
    """Bill a line at `amount`. Below what the work is worth it is a write-down and needs a reason; nothing at all is a
    write-off and needs a partner; above what the work is worth is refused (add a line of your own for that)."""
    worth = line.list_amount if line.list_amount is not None else line.amount
    if amount > worth:
        raise ValidationFailed(f"This line can be billed at most {worth}: to charge more, add a line of your own")
    if amount < worth:
        why = (reason if reason is not None else line.write_down_reason or "").strip()
        if not why:
            raise ValidationFailed("A write-down needs a reason: say why this is billed for less than it is worth")
        if amount == 0 and not may_write_off:
            raise ValidationFailed("Writing a line off completely needs a partner (time.partner)")
        line.write_down_reason = why[:300]
    else:
        line.write_down_reason = None
    line.automatic = False                                        # a person has now looked at this line
    line.amount = amount


def update_line(session: Session, batch_id: UUID, line_id: UUID, **changes: Any) -> BatchView:
    """Edit a line of a draft review: its wording; for time, the billed minutes and rate (the amount follows); for a
    manual line, the amount. Billing less than the work is worth is a write-down: it needs `write_down_reason`, the
    approved time itself is never touched, and the difference is kept on the line for the realisation report."""
    batch = _draft(session, batch_id)
    line = repo.get(session, InvoiceBatchLine, line_id, lock=True)
    if line is None or line.batch_id != batch.id:
        raise NotFound("Line not found")
    ctx = current_context()
    may_write_off = ctx.can(TIME_PARTNER, company_id=batch.company_id, branch_id=batch.branch_id)
    reason = changes.get("write_down_reason")
    if changes.get("description") is not None:
        if not changes["description"].strip():
            raise ValidationFailed("A line needs wording")
        line.description = changes["description"].strip()[:300]
    if line.kind == "time":
        if changes.get("minutes") is not None:
            if changes["minutes"] < 0:
                raise ValidationFailed("Billed time cannot be negative")
            if changes["minutes"] == 0 and not may_write_off:
                raise ValidationFailed("Writing a line off completely needs a partner (time.partner)")
            if changes["minutes"] > (line.list_minutes or line.minutes or 0):
                raise ValidationFailed("A line cannot bill more hours than were worked: add a line of your own")
            line.minutes = changes["minutes"]
        if changes.get("rate") is not None:
            if changes["rate"] < 0:
                raise ValidationFailed("A rate cannot be negative")
            if line.rate is None:                                  # pricing an unpriced line: the work is worth this
                line.list_amount = rules.amount_for(line.list_minutes or line.minutes or 0, changes["rate"])
            line.rate = changes["rate"]
        if line.rate is not None and line.minutes is not None:
            _set_amount(line, rules.amount_for(line.minutes, line.rate), reason, may_write_off)
        if "write_down_reason" in changes and line.amount < (line.list_amount or 0) and reason:
            line.write_down_reason = reason.strip()[:300]
    elif changes.get("amount") is not None:
        if line.kind not in ("manual", "retainer_topup", "retainer_fee", "milestone", "expense"):
            raise ValidationFailed("This line's amount cannot be changed")
        if changes["amount"] < 0:
            raise ValidationFailed("An amount cannot be negative")
        if line.kind in ("manual", "retainer_topup", "retainer_fee"):
            if changes["amount"] <= 0:
                raise ValidationFailed("A line of your own needs an amount: remove it instead")
            line.amount = line.list_amount = changes["amount"]
        else:
            if line.kind == "milestone" and changes["amount"] == 0:
                raise ValidationFailed("A milestone is billed or written down, not written off: set it back to planned")
            _set_amount(line, changes["amount"], reason, may_write_off)
    elif reason is not None and line.amount < (line.list_amount if line.list_amount is not None else line.amount):
        line.write_down_reason = reason.strip()[:300] or line.write_down_reason
    _edited(batch)
    session.flush()
    audit_record(session, "update_line", "timebilling.invoice_batch", batch.id,
                 {"line": line.line_no, "amount": line.amount, "worth": line.list_amount,
                  "reason": line.write_down_reason})
    return view_batch(session, batch.id)


def add_manual_line(session: Session, batch_id: UUID, *, description: str, amount: Decimal,
                    service_product_id: UUID | None = None) -> BatchView:
    """Add a line of your own (a fee, an adjustment) to a draft review."""
    batch = _draft(session, batch_id)
    if amount <= 0 or not description.strip():
        raise ValidationFailed("A line needs wording and an amount above nothing")
    setting = common.settings(session, batch.company_id)
    n = max((x.line_no for x in repo.batch_lines(session, batch.id)), default=0) + 1
    _add_line(session, batch, n, "manual", description.strip(), amount, None,
              service_product_id or setting.service_product_id)
    _edited(batch)
    session.flush()
    _renumber(session, batch)
    return view_batch(session, batch.id)


def remove_line(session: Session, batch_id: UUID, line_id: UUID) -> BatchView:
    """Take a line off the review; its time, expenses or milestone go back to unbilled work."""
    batch = _draft(session, batch_id)
    line = repo.get(session, InvoiceBatchLine, line_id, lock=True)
    if line is None or line.batch_id != batch.id:
        raise NotFound("Line not found")
    _release_line_sources(session, line)
    session.delete(line)
    _edited(batch)
    session.flush()
    return view_batch(session, batch.id)


def _release_line_sources(session: Session, line: InvoiceBatchLine) -> None:
    if line.entry_ids:
        for e in session.scalars(select(Entry).where(Entry.id.in_(line.entry_ids)).with_for_update()):
            e.batch_id = None
    if line.expense_ids:
        for x in session.scalars(select(Expense).where(Expense.id.in_(line.expense_ids)).with_for_update()):
            x.batch_id = None
    if line.milestone_id:
        m = session.get(Milestone, line.milestone_id)
        if m is not None:
            m.batch_id = None


def discard_batch(session: Session, batch_id: UUID) -> InvoiceBatch:
    """Throw away a draft review; the work goes back to unbilled."""
    batch = _draft(session, batch_id)
    for line in repo.batch_lines(session, batch.id):
        _release_line_sources(session, line)
    batch.status, batch.released_at = "discarded", datetime.now(UTC)
    session.flush()
    audit_record(session, "discard", "timebilling.invoice_batch", batch.id)
    return batch


# --------------------------------------------------------------------------- narrative
def write_narrative(session: Session, batch_id: UUID, *, into_lines: bool = False) -> BatchView:
    """Write the account of the work behind the review from its entries' notes and tasks (by date, person and
    hours). It is text a person can edit and send with the invoice. With `into_lines` each time line's wording also
    gets a short version of its own entries (the invoice line is limited to 300 characters)."""
    batch = _draft(session, batch_id)
    entries = _entries_of(session, batch)
    names = common.user_names(session, {e.user_id for e in entries})
    billable = [rules.BillableEntry(e.id, e.project_id, e.user_id, names.get(e.user_id, ""), e.task or "", e.work_date,
                                    e.minutes - e.retainer_minutes, e.bill_rate, e.note or "") for e in entries]
    batch.narrative = rules.narrative(billable) or None
    if into_lines:
        by_id = {b.id: b for b in billable}
        projects = repo.projects_by_ids(session, {e.project_id for e in entries})
        for line in repo.batch_lines(session, batch.id):
            if line.kind != "time" or not line.entry_ids:
                continue
            story = rules.narrative([by_id[i] for i in line.entry_ids if i in by_id], limit=220).replace("\n", "; ")
            project = projects.get(line.project_id) if line.project_id else None
            head = (f"{project.name}: " if project else "") + f"{hours(line.minutes or 0)} h"
            line.description = f"{head}. {story}"[:300] if story else line.description
    _edited(batch)
    session.flush()
    audit_record(session, "narrative", "timebilling.invoice_batch", batch.id, {"into_lines": into_lines})
    return view_batch(session, batch.id)


def schedule(session: Session, batch_id: UUID) -> tuple[list[str], list[list[object]]]:
    """The time and expense schedule behind a review, one row per entry and expense (the page a client gets with the
    invoice): date, person, project, task, hours, rate, value and the person's note."""
    batch = get_batch(session, batch_id)
    entries = sorted(_entries_of(session, batch), key=lambda e: (e.work_date, e.created_at))
    expenses = list(session.scalars(select(Expense).where(Expense.batch_id == batch.id).order_by(Expense.expense_date)))
    names = common.user_names(session, {e.user_id for e in entries})
    projects = repo.projects_by_ids(session, {e.project_id for e in entries} | {x.project_id for x in expenses})
    header = ["Date", "Person", "Project", "Task or item", "Hours", "Rate", "Value", "Note"]
    rows: list[list[object]] = []
    for e in entries:
        p = projects.get(e.project_id)
        billed = e.minutes - e.retainer_minutes
        rows.append([e.work_date.isoformat(), names.get(e.user_id, ""), p.code if p else "", e.task or "",
                     str(hours(billed)), str(e.bill_rate) if e.bill_rate is not None else "",
                     str(rules.amount_for(billed, e.bill_rate)) if e.bill_rate is not None else "", e.note or ""])
    for x in expenses:
        p = projects.get(x.project_id)
        rows.append([x.expense_date.isoformat(), "", p.code if p else "", x.description, "", "",
                     str(rules.expense_amount(x.amount, x.markup_percent)), x.reference or ""])
    return header, rows


# --------------------------------------------------------------------------- partner review
def request_review(session: Session, batch_id: UUID) -> BatchView:
    """Send the review to the partners (people with 'time.partner') to look at before it is issued. Needs
    'time.bill'."""
    batch = _draft(session, batch_id)
    if batch.review_status == "requested":
        return view_batch(session, batch.id)
    batch.review_status = "requested"
    batch.review_requested_by, batch.review_requested_at = current_context().user_id, datetime.now(UTC)
    batch.review_by = batch.review_at = batch.review_note = None
    session.flush()
    audit_record(session, "request_review", "timebilling.invoice_batch", batch.id)
    view = view_batch(session, batch.id)
    notify.partner_review_requested(session, batch, view.client_name, view.net_total)
    return view


def decide_review(session: Session, batch_id: UUID, *, approve: bool, note: str | None = None) -> BatchView:
    """A partner approves the review or sends it back with a note. Needs 'time.partner'."""
    batch = _draft(session, batch_id)
    ctx = current_context()
    ctx.require(TIME_PARTNER, company_id=batch.company_id, branch_id=batch.branch_id)
    if not approve and not (note or "").strip():
        raise ValidationFailed("Say what needs changing")
    batch.review_status = "approved" if approve else "changes_requested"
    batch.review_by, batch.review_at = ctx.user_id, datetime.now(UTC)
    batch.review_note = (note or "").strip()[:500] or None
    session.flush()
    audit_record(session, "approve_review" if approve else "reject_review", "timebilling.invoice_batch", batch.id,
                 {"note": batch.review_note})
    if not approve:
        notify.review_sent_back(session, batch, batch.review_note or "")
    return view_batch(session, batch.id)


# --------------------------------------------------------------------------- retainer lines
def add_retainer_topup(session: Session, retainer_id: UUID, *, minutes: int, amount: Decimal,
                       branch_id: UUID | None = None, memo: str | None = None) -> BatchView:
    """Bill a top-up of prepaid hours: a new review with one line. The hours join the balance when it is issued."""
    retainer = retainers.get_retainer(session, retainer_id)
    if retainer.kind != "hours" or retainer.status != "active":
        raise ValidationFailed("Top-ups are for an active hours retainer")
    if minutes <= 0 or amount <= 0:
        raise ValidationFailed("Give the hours and the amount")
    project = session.get(Project, retainer.project_id)
    assert project is not None
    setting = common.settings(session, retainer.company_id)
    branch = _branch_for(session, retainer.company_id, [project], branch_id)
    current_context().require(TIME_BILL, company_id=retainer.company_id, branch_id=branch)
    batch = InvoiceBatch(tenant_id=current_context().tenant_id, created_by=current_context().user_id,
                         company_id=retainer.company_id, branch_id=branch, client_id=project.client_id,
                         project_id=project.id, group_by=setting.default_group_by, memo=memo)
    repo.add(session, batch)
    _add_line(session, batch, 1, "retainer_topup", f"{project.name}: prepaid hours ({hours(minutes)} h)", amount,
              project, _service_for(project, setting), minutes=minutes, retainer_id=retainer.id)
    session.flush()
    return view_batch(session, batch.id)


def add_retainer_fee(session: Session, retainer_id: UUID, *, period: str,
                     branch_id: UUID | None = None) -> BatchView:
    """Bill a monthly-fee retainer for a month (`YYYY-MM`) as a new review. A month is billed once: asking again while
    that month is on a live review or invoice is refused."""
    retainer = retainers.get_retainer(session, retainer_id)
    if retainer.kind != "monthly_fee" or retainer.status != "active" or retainer.monthly_fee is None:
        raise ValidationFailed("Fees are for an active monthly-fee retainer")
    try:
        year, month = (int(x) for x in period.split("-"))
        date(year, month, 1)
    except ValueError as exc:
        raise ValidationFailed("Give the month as YYYY-MM") from exc
    taken = session.scalar(select(InvoiceBatchLine.id).join(
        InvoiceBatch, InvoiceBatch.id == InvoiceBatchLine.batch_id).where(
        InvoiceBatchLine.retainer_id == retainer.id, InvoiceBatchLine.period == period,
        InvoiceBatchLine.kind == "retainer_fee", InvoiceBatch.status.in_(("draft", "issued"))))
    if taken is not None:
        raise Conflict(f"{period} has already been billed for this retainer")
    project = session.get(Project, retainer.project_id)
    assert project is not None
    setting = common.settings(session, retainer.company_id)
    branch = _branch_for(session, retainer.company_id, [project], branch_id)
    current_context().require(TIME_BILL, company_id=retainer.company_id, branch_id=branch)
    batch = InvoiceBatch(tenant_id=current_context().tenant_id, created_by=current_context().user_id,
                         company_id=retainer.company_id, branch_id=branch, client_id=project.client_id,
                         project_id=project.id, group_by=setting.default_group_by)
    repo.add(session, batch)
    _add_line(session, batch, 1, "retainer_fee", f"{project.name}: monthly retainer {period}", retainer.monthly_fee,
              project, _service_for(project, setting), retainer_id=retainer.id, period=period)
    session.flush()
    return view_batch(session, batch.id)


# --------------------------------------------------------------------------- issuing
def issue_batch(session: Session, batch_id: UUID) -> BatchView:
    """Issue the review as one invoice. Needs 'time.bill' and the invoice permission of POS. Safe to ask twice: the same
    review always gives the same invoice. Lines billed at nothing (written off, with a reason) are left off the invoice
    and their work is settled; when the company asks for partner review, a partner must have approved the review (or
    be the one issuing it)."""
    batch = get_batch(session, batch_id, lock=True)
    if batch.status == "issued":
        return view_batch(session, batch.id)
    if batch.status != "draft":
        raise Conflict(f"This review is {batch.status}")
    view = view_batch(session, batch.id)
    if not view.lines:
        raise ValidationFailed("The review has no lines")
    if view.problems:
        raise ValidationFailed("; ".join(view.problems) + ". Set them on the review first.")
    ctx = current_context()
    setting = common.settings(session, batch.company_id)
    if _needs_partner(setting, view.net_total) and batch.review_status != "approved":
        batch.review_status, batch.review_by = "approved", ctx.user_id                       # a partner issuing
        batch.review_at = datetime.now(UTC)
        batch.review_note = batch.review_note or "Approved by the partner who issued it"
    if not access.unit_enabled(session, "pos"):
        raise ValidationFailed("Enable Point of Sale and Sales to issue invoices")
    from ziira.modules.pos.public import InvoiceLineIn, issue_invoice_from_lines

    lines = []
    settled: set[UUID] = set()                  # ids of entries and expenses on lines that are billed at nothing
    for x in view.lines:
        assert x.service_product_id is not None
        if x.amount <= 0:
            if not (x.write_down_reason or "").strip():
                raise ValidationFailed(f"Line {x.line_no} is worth nothing: give the reason it is written off")
            settled.update(x.entry_ids)
            settled.update(x.expense_ids)
            continue
        gross = rules.gross_amount(x.amount, _vat(session, x.service_product_id), setting.rates_include_tax)
        lines.append(InvoiceLineIn(product_id=x.service_product_id, description=x.description, quantity=Decimal(1),
                                   unit_price=gross))
    now = datetime.now(UTC)
    ref = None
    if lines:
        ref = issue_invoice_from_lines(
            session, company_id=batch.company_id, branch_id=batch.branch_id, customer_id=batch.client_id, lines=lines,
            source_type=SOURCE_TYPE, source_id=batch.id, due_days=batch.due_days, memo=batch.memo)
        batch.invoice_id, batch.invoice_number = ref.id, ref.number
        batch.total, batch.tax_total = ref.total, ref.tax_total
    else:
        batch.total = batch.tax_total = Decimal(0)         # everything written off: no invoice is made
    batch.status, batch.issued_at, batch.issued_by = "issued", now, ctx.user_id
    today = common.today(session, batch.company_id)
    for e in _entries_of(session, batch):
        e.invoice_id, e.invoiced_at = (ref.id if ref else None), now
        e.written_off = e.id in settled
    for expense in session.scalars(select(Expense).where(Expense.batch_id == batch.id)):
        expense.invoice_id, expense.invoiced_at = (ref.id if ref else None), now
        expense.written_off = expense.id in settled
    for m in session.scalars(select(Milestone).where(Milestone.batch_id == batch.id)):
        m.status = "invoiced"
    label = ref.number if ref else "written off"
    for line in view.lines:
        if line.kind == "retainer_topup" and line.retainer_id and line.minutes:
            retainer = repo.get(session, Retainer, line.retainer_id, lock=True)
            if retainer is not None:
                retainers.add_minutes(session, retainer, line.minutes, today, amount=line.amount, batch_id=batch.id,
                                      note=f"Invoice {label}")
    session.flush()
    audit_record(session, "issue", "timebilling.invoice_batch", batch.id,
                 {"invoice": label, "total": batch.total, "lines": len(view.lines), "written_down": view.write_down})
    if ref is not None:
        publish(session, Event("timebilling.invoiced", "timebilling.invoice_batch", batch.id, {
            "company_id": batch.company_id, "client_id": batch.client_id, "invoice_id": ref.id, "number": ref.number,
            "total": ref.total}))
    return view_batch(session, batch.id)


# --------------------------------------------------------------------------- the invoice is cancelled
def release_for_cancelled_invoice(session: Session, invoice_id: UUID, reason: str | None = None) -> None:
    """The invoice made from a review was cancelled in POS: the time, expenses and milestones come back as unbilled
    work, and prepaid hours that the invoice added are taken off the balance again."""
    batch = repo.batch_for_invoice(session, invoice_id)
    if batch is None or batch.status != "issued":
        return
    for e in _entries_of(session, batch):
        e.invoice_id = e.invoiced_at = e.batch_id = None
        e.written_off = False
    for x in session.scalars(select(Expense).where(Expense.batch_id == batch.id)):
        x.invoice_id = x.invoiced_at = x.batch_id = None
        x.written_off = False
    for m in session.scalars(select(Milestone).where(Milestone.batch_id == batch.id)):
        m.status, m.batch_id = "ready", None
    today = common.today(session, batch.company_id)
    for line in repo.batch_lines(session, batch.id):
        if line.kind == "retainer_topup" and line.retainer_id and line.minutes:
            retainer = repo.get(session, Retainer, line.retainer_id, lock=True)
            if retainer is not None:
                take = min(retainer.balance_minutes, line.minutes)
                if take > 0:
                    retainer.balance_minutes -= take
                    retainer.topped_up_minutes = max(retainer.topped_up_minutes - line.minutes, 0)
                    retainers._txn(session, retainer, "release", -take, today, batch_id=batch.id,
                                   note="Top-up invoice cancelled")
                if take < line.minutes:
                    flag_for_review(session, unit="timebilling", kind="topup_already_used",
                                    message=f"Invoice {batch.invoice_number} was cancelled but "
                                            f"{hours(line.minutes - take)} of its prepaid hours were already used",
                                    company_id=batch.company_id, ref_type="timebilling.retainer", ref_id=retainer.id,
                                    dedupe_key=f"topup-cancel-{batch.id}")
    batch.status, batch.released_at = "cancelled", datetime.now(UTC)
    session.flush()
    audit_record(session, "release", "timebilling.invoice_batch", batch.id,
                 {"invoice": batch.invoice_number, "reason": reason})
