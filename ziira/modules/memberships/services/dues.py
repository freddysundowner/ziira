"""Money owed to the business: which membership invoices are unpaid and late, arrears per member, late-payment
reminders,
the hold for unpaid fees, taking a payment, writing off and refunding.

The truth about an invoice lives in Sales. This module copies what it needs (outstanding, settled or not, due date) onto
the invoice run, then onto the membership (`arrears`, `past_due_since`), so a check-in at the door never has to ask
Sales. The copy is refreshed by the hourly task and again the moment a payment, cancellation or credit note is
recorded."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ziira.modules.memberships.domain.quiet import is_quiet
from ziira.modules.memberships.permissions import CREDITS, MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, holds, invoicing, notify
from ziira.sdk import (
    Session,
    ValidationFailed,
    audit_record,
    company_setting,
    current_context,
    format_day,
)

ZERO = Decimal(0)
MEMBER_OWNERS = ("member", "freeze", "change", "exit")
OPEN = "status = 'issued' and settle_state = 'open' and invoice_id is not null"


def _states(session: Session, invoice_ids: list[UUID]) -> dict[UUID, Any]:
    if not invoice_ids or not invoicing.available(session):
        return {}
    import ziira.modules.pos.public as sales

    found: dict[UUID, Any] = {}
    for start in range(0, len(invoice_ids), 500):
        found.update(sales.invoice_states(session, set(invoice_ids[start:start + 500])))
    return found


def refresh_runs(session: Session, company_id: UUID, *, payer_customer_id: UUID | None = None,
                 today: date | None = None) -> int:
    """Re-read the open invoices of a company (or of one payer) from Sales and update the runs, then the memberships.
    Returns how many memberships changed."""
    day = today or common.today(session, company_id)
    runs = repo.many(session, f"select id, invoice_id, owner_type, owner_id, outstanding from memberships.invoice_run "
                              f"where company_id = :c and {OPEN} and (cast(:p as uuid) is null or customer_id = :p)",
                     c=company_id, p=payer_customer_id)
    states = _states(session, [r["invoice_id"] for r in runs])
    touched: set[UUID] = set()
    for run in runs:
        st = states.get(run["invoice_id"])
        if st is None:
            continue
        if st.status == "cancelled":
            state = "cancelled"
        elif st.outstanding <= 0:
            state = "credited" if st.amount_paid <= 0 < st.credited else "paid"
        else:
            state = "open"
        if state != "open" or Decimal(run["outstanding"] or 0) != st.outstanding:
            repo.update(session, "invoice_run", run["id"], {"settle_state": state, "outstanding": st.outstanding,
                                                            "due_date": st.due_date})
            if run["owner_type"] in MEMBER_OWNERS:
                touched.add(run["owner_id"])
    return _refresh_members(session, company_id, day, touched)


def _refresh_members(session: Session, company_id: UUID, day: date, member_ids: set[UUID]) -> int:
    """Recompute `arrears` and `past_due_since` of the memberships named, and of any that had arrears before."""
    carrying = repo.many(session, "select id from memberships.member where company_id = :c and past_due_since is not null",  # noqa: E501
                         c=company_id)
    owing = repo.many(
        session, f"select distinct owner_id from memberships.invoice_run where company_id = :c and {OPEN} "
                 "and owner_type in ('member', 'freeze', 'change', 'exit') and due_date < :d and outstanding > 0",
        c=company_id, d=day)
    ids = member_ids | {r["id"] for r in carrying} | {r["owner_id"] for r in owing}
    if not ids:
        return 0
    fresh = {r["member_id"]: r for r in repo.many(
        session,
        f"select owner_id as member_id, sum(outstanding) as arrears, min(due_date) as since "
        f"from memberships.invoice_run where company_id = :c and {OPEN} and owner_type in "
        "('member', 'freeze', 'change', 'exit') and due_date < :d and outstanding > 0 "
        "and owner_id = any(cast(:ids as uuid[])) group by owner_id", c=company_id, d=day,
        ids=[str(i) for i in ids])}
    changed = 0
    for member in repo.many(session, "select id, arrears, past_due_since from memberships.member "
                                     "where id = any(cast(:ids as uuid[]))", ids=[str(i) for i in ids]):
        now = fresh.get(member["id"])
        arrears, since = (Decimal(now["arrears"]), now["since"]) if now else (ZERO, None)
        if Decimal(member["arrears"]) != arrears or member["past_due_since"] != since:
            repo.update(session, "member", member["id"], {"arrears": arrears, "past_due_since": since})
            changed += 1
    return changed


def refresh_payer(session: Session, payer_customer_id: UUID) -> int:
    """After money moved for a customer (a payment, a cancellation, a credit note): refresh their open invoices now."""
    customer = common.customer_of_any(session, payer_customer_id)
    changed = refresh_runs(session, customer.company_id, payer_customer_id=payer_customer_id)
    return changed + release_arrears_holds(session, customer.company_id)


# --------------------------------------------------------------------------- the hold for unpaid fees
def apply_arrears_holds(session: Session, company_id: UUID, today: date) -> int:
    """Freeze memberships whose payment is late by more than the company's limit (when it set one). The freeze lifts by
    itself when the fees are paid (`release_arrears_holds`). Returns how many were frozen."""
    limit = int(repo.get_settings(session, company_id)["auto_freeze_days"])
    if limit <= 0:
        return 0
    frozen = 0
    for member in repo.many(
            session, "select * from memberships.member where company_id = :c and status = 'active' and arrears > 0 "
                     "and past_due_since is not null and past_due_since <= :d order by past_due_since, id for update",
            c=company_id, d=today - timedelta(days=limit)):
        holds.start(session, member, kind="arrears", resume_on=None, note="Fees unpaid", enforce_rules=False)
        frozen += 1
        payer = common.customer_names(session, {member["billing_customer_id"] or member["customer_id"]}).get(
            member["billing_customer_id"] or member["customer_id"])
        if payer is not None:
            company = common.one_company(session, company_id)
            notify.send(session, company_id, payer, "membership_frozen", {
                "customer": payer.name, "amount": f"{company['base_currency']} {Decimal(member['arrears']):,.2f}",
                "business": company["name"]}, str(repo.get_settings(session, company_id)["message_language"]),
                "memberships.member", member["id"], f"memberships:frozen:{member['id']}:{today}")
    return frozen


def release_arrears_holds(session: Session, company_id: UUID) -> int:
    """Lift the freeze of memberships held for unpaid fees once nothing is owed. Returns how many resumed."""
    day = common.today(session, company_id)
    resumed = 0
    for member in repo.many(
            session, "select * from memberships.member where company_id = :c and status = 'frozen' "
                     "and hold_kind = 'arrears' and arrears <= 0 for update", c=company_id):
        holds.end(session, member, day, "Fees paid")
        resumed += 1
    return resumed


# --------------------------------------------------------------------------- late-payment reminders
def dunning_steps(settings: repo.Row) -> list[int]:
    """The days after the due date a reminder goes on, from the company's setting ('1,7,14')."""
    steps: list[int] = []
    for part in str(settings["dunning_days"]).split(","):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= 365 and int(part) not in steps:
            steps.append(int(part))
    return sorted(steps)


def send_dunning(session: Session, company_id: UUID, now: datetime | None = None) -> int:
    """Queue the next late-payment reminder for each overdue invoice (outside quiet hours). One message per invoice per
    step, however often this runs. Returns how many were queued."""
    settings = repo.get_settings(session, company_id)
    steps = dunning_steps(settings)
    if not steps or not settings["reminders_enabled"]:
        return 0
    zone = ZoneInfo(str(company_setting(session, company_id, "timezone")))
    local = (now or datetime.now(UTC)).astimezone(zone)
    if is_quiet(local.hour, int(settings["quiet_start"]), int(settings["quiet_end"])):
        return 0
    today = local.date()
    runs = repo.many(
        session,
        "select r.*, (cast(:d as date) - r.due_date) as late from memberships.invoice_run r where r.company_id = :c "
        "and r.status = 'issued' and r.settle_state = 'open' and r.invoice_id is not null "
        "and r.due_date < :d and r.outstanding > 0 and not r.dunning_paused order by r.due_date limit 500",
        c=company_id, d=today)
    if not runs:
        return 0
    payers = common.customer_names(session, {r["customer_id"] for r in runs})
    company = common.one_company(session, company_id)
    queued = 0
    for run in runs:
        reached = [s for s in steps if s <= run["late"]]
        if not reached:
            continue
        step = max(reached)
        if repo.one(session, "select 1 as x from memberships.dunning_log where run_id = :r and step_days = :s",
                    r=run["id"], s=step):
            continue
        payer = payers.get(run["customer_id"])
        if payer is None:
            continue
        channel = notify.send(
            session, company_id, payer, "membership_payment_late", {
                "customer": payer.name, "amount": f"{company['base_currency']} {Decimal(run['outstanding']):,.2f}",
                "invoice": str(run["invoice_number"] or ""), "business": company["name"],
                "date": format_day(run["due_date"])}, str(settings["message_language"]),
            "memberships.invoice_run", run["id"], f"memberships:dunning:{run['id']}:{step}")
        ctx = current_context()
        repo.insert(session, "dunning_log", {
            "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "run_id": run["id"],
            "step_days": step, "customer_id": run["customer_id"], "channel": channel,
            "outcome": "queued" if channel else "no_contact"})
        queued += 1 if channel else 0
    return queued


def set_dunning_paused(session: Session, run_id: UUID, paused: bool) -> repo.Row:
    """Stop (or resume) late-payment reminders for one invoice, for example while a payment plan is agreed. Needs
    'memberships.manage'."""
    run = common.get_row(session, "invoice_run", run_id, "Invoice run", lock=True)
    common.require(MANAGE, run["company_id"], run["branch_id"])
    saved = repo.update(session, "invoice_run", run_id, {"dunning_paused": paused})
    audit_record(session, "dunning", "memberships.invoice_run", run_id, {"paused": paused})
    return saved


# --------------------------------------------------------------------------- arrears and the late-payment list
def arrears(session: Session, *, company_id: UUID, min_days: int = 1, limit: int = 100, offset: int = 0) -> list[repo.Row]:  # noqa: E501
    """Who owes what: one row per paying customer with overdue invoices, oldest first. Includes how long late, what the
    invoices are, the members the money is for, and the last reminder."""
    common.check_visible(company_id, None, "Company")
    clause, params = repo.scope_sql(common.view_scopes(), "r")
    today = common.today(session, company_id)
    rows = repo.many(
        session,
        "select r.customer_id, sum(r.outstanding) as owed, min(r.due_date) as oldest_due, count(*) as invoices, "
        "  (cast(:d as date) - min(r.due_date)) as days_late, "
        "  (select max(l.created_at) from memberships.dunning_log l where l.customer_id = r.customer_id) as last_reminder, "  # noqa: E501
        "  array_agg(distinct r.invoice_number) as invoice_numbers "
        f"from memberships.invoice_run r where {clause} and r.company_id = :c and r.status = 'issued' "
        "and r.settle_state = 'open' and r.invoice_id is not null and r.due_date < :d and r.outstanding > 0 "
        "group by r.customer_id having (cast(:d as date) - min(r.due_date)) >= :m "
        "order by min(r.due_date), r.customer_id limit :l offset :o",
        c=company_id, d=today, m=min_days, l=min(limit, 500), o=offset, **params)
    names = common.customer_names(session, {r["customer_id"] for r in rows})
    out: list[repo.Row] = []
    for r in rows:
        who = names.get(r["customer_id"])
        members = repo.many(session, "select m.number, m.plan_name, m.status, m.customer_id from memberships.member m "
                                     "where m.company_id = :c and m.arrears > 0 and (m.customer_id = :p or "
                                     "m.billing_customer_id = :p) order by m.number", c=company_id, p=r["customer_id"])
        out.append({**r, "customer_name": who.name if who else None, "phone": who.phone if who else None,
                    "email": who.email if who else None, "members": members,
                    "invoice_numbers": [n for n in (r["invoice_numbers"] or []) if n]})
    return out


def member_dues(session: Session, member_id: UUID) -> list[repo.Row]:
    """The invoices of one membership: issued, with what is still owed."""
    common.get_row(session, "member", member_id, "Membership")
    return repo.many(session, "select r.id, r.owner_type, r.period_start, r.period_end, r.invoice_number, r.total, "
                              "r.outstanding, r.due_date, r.settle_state, r.status, r.dunning_paused, r.message "
                              "from memberships.invoice_run r where r.owner_id = :m order by r.period_start desc "
                              "limit 60", m=member_id)


# --------------------------------------------------------------------------- taking money, writing off, refunding
def take_payment(session: Session, member_id: UUID, *, amount: Decimal, method: str,
                 reference: str | None = None) -> dict[str, Any]:
    """Record money received for a membership's unpaid invoices (oldest first). The receipt comes from Sales: it can be
    printed there, and cash goes through the cashier's open till. Needs 'memberships.manage' (and Sales'
    'receivables.manage')."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if not invoicing.available(session):
        raise ValidationFailed("Payments are taken in Sales: switch on Point of Sale and Invoices")
    if amount <= 0:
        raise ValidationFailed("A payment is more than zero")
    runs = repo.many(session, f"select * from memberships.invoice_run where owner_id = :m and {OPEN} "
                              "and owner_type in ('member', 'freeze', 'change', 'exit') order by due_date, period_start",  # noqa: E501
                     m=member_id)
    states = _states(session, [r["invoice_id"] for r in runs])
    left, plan = amount, []
    for run in runs:
        st = states.get(run["invoice_id"])
        if st is None or st.outstanding <= 0 or left <= 0:
            continue
        part = min(left, st.outstanding)
        plan.append((run["invoice_id"], part))
        left -= part
    if not plan:
        raise ValidationFailed("Nothing is owed on this membership")
    if left > 0:
        raise ValidationFailed(f"Only {amount - left:,.2f} is owed on this membership")
    import ziira.modules.pos.public as sales

    payer = runs[0]["customer_id"]
    receipt = sales.take_payment(session, customer_id=payer, branch_id=member["branch_id"], amount=amount,
                                 method=method, allocations=plan, external_ref=reference)
    refresh_payer(session, payer)
    audit_record(session, "payment", "memberships.member", member_id,
                 {"amount": str(amount), "method": method, "receipt": receipt.number})
    return {"receipt_id": receipt.id, "receipt_number": receipt.number, "amount": receipt.amount,
            "method": receipt.method}


def credit_run(session: Session, run_id: UUID, *, reason_code_id: UUID, refund_method: str,
               amount: Decimal | None = None, note: str | None = None) -> repo.Row:
    """Write off (a credit note: less owed) or refund (cash or mobile money once paid) an invoice this unit made, in
    whole or in part, through Sales' credit-note rules and approval. The reason is one of Sales' 'sale_return'
    reasons and
    the note is kept. The invoice is never edited. Needs 'memberships.credits'."""
    run = common.get_row(session, "invoice_run", run_id, "Invoice run", lock=True)
    common.require(CREDITS, run["company_id"], run["branch_id"])
    if run["status"] != "issued" or run["invoice_id"] is None:
        raise ValidationFailed("This period has no invoice to credit")
    if refund_method not in ("credit_note", "cash", "mobile_money"):
        raise ValidationFailed("Write off with a credit note, or refund in cash or mobile money")
    if not (note or "").strip():
        raise ValidationFailed("Say why the invoice is credited")
    import ziira.modules.pos.public as sales

    made = sales.credit_invoice(session, run["invoice_id"], reason_code_id=reason_code_id,
                                refund_method=refund_method, amount=amount, note=note)
    saved = repo.update(session, "invoice_run", run_id, {"message": f"Credited: {made.number}"})
    audit_record(session, "credit", "memberships.invoice_run", run_id,
                 {"credit_note": made.number, "total": str(made.total), "method": refund_method, "note": note})
    refresh_payer(session, run["customer_id"])
    return {**saved, "credit_number": made.number, "credit_total": made.total, "credit_status": made.status}
