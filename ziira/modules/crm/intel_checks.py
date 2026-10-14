"""Intelligence checks over CRM data: customers over their credit limit, credit raises waiting for approval, overdue
follow-ups on open leads, and customers entered twice. Read only; every figure comes from records."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

import ziira.modules.pos.public as pos_public
from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session, provides

OPEN_LEAD = "('new', 'contacted', 'qualified')"


def currency_of(session: Session, company_id: UUID) -> str:
    """The company's base currency code."""
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def money(currency: str, value: Decimal) -> str:
    """Text such as 'USD 1,250.00' from the company's own currency code."""
    return f"{currency} {value:,.2f}"


def pos_is_on(session: Session) -> bool:
    """True when Point of Sale is enabled for this business (customer balances come from it)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


# --------------------------------------------------------------------------- over the credit limit
@provides(INTEL_CHECK)
class OverCreditLimit(IntelCheck):
    """A customer owes more than the credit limit they were given."""

    code = "crm.over_credit_limit"
    title = "Customers over their credit limit"
    area = "customers"
    description = ("A customer whose unpaid invoices, less money they hold on account, are above their credit limit. "
                   "Customers with no credit limit set are not checked.")
    default_severity = "medium"
    params: dict[str, Any] = {"high_over_pct": "50.0", "max_customers": 1000}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        if not pos_is_on(session):
            return []                                   # without sales there are no balances to compare
        currency = currency_of(session, ctx.company_id)
        found: list[Candidate] = []
        for c in session.execute(text(
                "select id, code, name, credit_limit from crm.customer where company_id = :c and credit_limit > 0 "
                "and status <> 'inactive' order by credit_limit desc, code limit :n"),
                {"c": str(ctx.company_id), "n": int(ctx.number("max_customers"))}).all():
            owed = pos_public.customer_balance(session, c.id)
            if owed <= c.credit_limit:
                continue
            over = owed - c.credit_limit
            severe = over * 100 > c.credit_limit * ctx.number("high_over_pct")
            found.append(Candidate(
                fingerprint=fingerprint(self.code, c.id), severity="high" if severe else "medium",
                summary=(f"{c.name} owes {money(currency, owed)}, which is {money(currency, over)} over their credit "
                         f"limit of {money(currency, c.credit_limit)}."),
                recommended_action="Ask the customer to pay before more goods are sold on credit.",
                company_id=ctx.company_id, entity_type="crm.customer", entity_id=c.id, value=owed,
                expected_value=c.credit_limit, amount=over,
                records=(Record("crm.customer", c.id, f"{c.name} ({c.code})"),),
                figures={"owed": str(owed), "credit_limit": str(c.credit_limit), "over_by": str(over)}))
        return found


# --------------------------------------------------------------------------- a raise waiting for a decision
@provides(INTEL_CHECK)
class CreditIncreaseWaiting(IntelCheck):
    """A credit limit increase left waiting for approval."""

    code = "crm.credit_increase_waiting"
    title = "Credit increases waiting for approval"
    area = "customers"
    description = "A request to raise a customer's credit limit that has waited for approval longer than the limit."
    default_severity = "low"
    params: dict[str, Any] = {"days": 3, "lookback_days": 180}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        waited = int(ctx.number("days"))
        found: list[Candidate] = []
        for v in session.execute(text(
                "select v.id, v.credit_limit, coalesce(v.previous_limit, c.credit_limit) as old_limit, "
                "  (v.created_at at time zone :tz)::date as asked_on, c.id as customer_id, c.name, c.code "
                "from crm.customer_credit_version v join crm.customer c on c.id = v.customer_id "
                "where c.company_id = :c and v.status = 'pending_approval' "
                "and v.credit_limit > coalesce(v.previous_limit, c.credit_limit) "
                "and (v.created_at at time zone :tz)::date <= :cut and (v.created_at at time zone :tz)::date >= :since "
                "order by v.created_at"),
                {"c": str(ctx.company_id), "tz": ctx.timezone, "cut": ctx.today - timedelta(days=waited),
                 "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all():
            days = (ctx.today - v.asked_on).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, v.id), severity="low",
                summary=(f"The credit limit of {v.name} was asked to go from {money(currency, v.old_limit)} to "
                         f"{money(currency, v.credit_limit)} {days} days ago and has not been decided."),
                recommended_action="Approve or reject the credit limit change.",
                company_id=ctx.company_id, entity_type="crm.customer", entity_id=v.customer_id,
                period_start=v.asked_on, value=Decimal(days), expected_value=Decimal(waited),
                amount=v.credit_limit - v.old_limit,
                records=(Record("crm.customer", v.customer_id, f"{v.name} ({v.code})"),
                         Record("crm.customer_credit_version", v.id, "Credit limit request")),
                figures={"requested_limit": str(v.credit_limit), "current_limit": str(v.old_limit),
                         "days_waiting": str(days)}))
        return found


# --------------------------------------------------------------------------- follow-ups not done
@provides(INTEL_CHECK)
class OverdueFollowUps(IntelCheck):
    """Follow-ups on open leads that are days past due, one finding per person who owns them."""

    code = "crm.followups_overdue"
    title = "Overdue lead follow-ups"
    area = "customers"
    description = "A salesperson with follow-ups on open leads that are overdue by more than the limit."
    default_severity = "low"
    params: dict[str, Any] = {"days": 3, "many": 5, "lookback_days": 180}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select a.id, a.kind, a.owner_user_id, (a.due_at at time zone :tz)::date as due_on, l.name as lead_name, "
            "  u.full_name as owner_name "
            "from crm.activity a join crm.lead l on l.id = a.related_id "
            "left join kernel.app_user u on u.id = a.owner_user_id "
            f"where a.related_type = 'lead' and l.company_id = :c and l.status in {OPEN_LEAD} "
            "and a.done_at is null and a.due_at is not null "
            "and (a.due_at at time zone :tz)::date <= :cut and (a.due_at at time zone :tz)::date >= :since "
            "order by a.due_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "cut": ctx.today - timedelta(days=int(ctx.number("days"))),
             "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all()
        by_owner: dict[UUID | None, list[Any]] = {}
        for r in rows:
            by_owner.setdefault(r.owner_user_id, []).append(r)
        found: list[Candidate] = []
        limit = int(ctx.number("days"))
        for owner, items in by_owner.items():
            who = items[0].owner_name or "Nobody (unassigned)"
            oldest = items[0].due_on
            found.append(Candidate(
                fingerprint=fingerprint(self.code, owner),
                severity="medium" if len(items) >= int(ctx.number("many")) else "low",
                summary=(f"{who} has {len(items)} follow-up{'s' if len(items) != 1 else ''} on open leads more than "
                         f"{limit} days overdue; the oldest was due on {oldest}."),
                recommended_action="Ask them to make these calls or visits, or hand the leads to someone else.",
                company_id=ctx.company_id, entity_type="kernel.app_user", entity_id=owner, period_start=oldest,
                period_end=ctx.today, value=Decimal(len(items)),
                records=tuple(Record("crm.activity", i.id, f"{i.kind.capitalize()}: {i.lead_name}, due {i.due_on}")
                              for i in items[:10]),
                figures={"overdue_follow_ups": str(len(items)), "oldest_due": str(oldest)}))
        return found


# --------------------------------------------------------------------------- the same customer twice
@provides(INTEL_CHECK)
class DuplicateCustomers(IntelCheck):
    """Customers recently created with the same phone number or tax number as another customer."""

    code = "crm.duplicate_customers"
    title = "Customers entered twice"
    area = "controls"
    description = ("A customer created recently with the same phone number or tax number as another customer, which "
                   "can be used to get more credit than one account allows.")
    default_severity = "low"
    params: dict[str, Any] = {"days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("days")))
        rows = session.execute(text(
            "select id, code, name, phone, nullif(lower(btrim(tax_id)), '') as tax, "
            "  (created_at at time zone :tz)::date >= :since as recent "
            "from crm.customer where company_id = :c and ("
            "  phone in (select phone from crm.customer where company_id = :c and phone is not null and phone <> '' "
            "            and (created_at at time zone :tz)::date >= :since) "
            "  or lower(btrim(tax_id)) in (select lower(btrim(tax_id)) from crm.customer where company_id = :c "
            "            and btrim(coalesce(tax_id, '')) <> '' and (created_at at time zone :tz)::date >= :since)) "
            "order by created_at"), {"c": str(ctx.company_id), "tz": ctx.timezone, "since": since}).all()
        found: list[Candidate] = []
        for kind, label, severity in (("phone", "phone number", "low"), ("tax", "tax number", "medium")):
            groups: dict[str, list[Any]] = {}
            for r in rows:
                key = r.phone if kind == "phone" else r.tax
                if key:
                    groups.setdefault(str(key), []).append(r)
            for key, members in groups.items():
                if len(members) < 2 or not any(m.recent for m in members):
                    continue
                names = ", ".join(m.name for m in members[:4])
                found.append(Candidate(
                    fingerprint=fingerprint(self.code, kind, key), severity=severity,
                    summary=f"{len(members)} customers share the same {label} ({key}): {names}.",
                    recommended_action="Check whether these are the same customer and merge or correct the records.",
                    company_id=ctx.company_id, entity_type="crm.customer", entity_id=members[-1].id,
                    value=Decimal(len(members)),
                    records=tuple(Record("crm.customer", m.id, f"{m.name} ({m.code})") for m in members),
                    figures={label.replace(" ", "_"): key, "customers": str(len(members))}))
        return found
