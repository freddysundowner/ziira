"""What Intelligence may do about customers who owe: remind them (a routine message the owner may let it send by itself)
and hold their credit (a person decides). Both go through the units' own services, so opt-outs, the business's channel,
credit rules and permissions all apply."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.crm.public import change_credit_limit, find_customer
from ziira.modules.intel.public import ActionContext, ActionProvider, ActionResult, FindingInfo, Proposal
from ziira.modules.pos.intel_checks import currency, money
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import SalesInvoice
from ziira.modules.pos.services import credit, receivables
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import Session, ValidationFailed, company_setting, company_today

CUSTOMER = "crm.customer"
INVOICE = "pos.sales_invoice"
MAX_INVOICES = 3                  # the oldest overdue invoices chased in one go, so one customer is not flooded


def overdue_invoices(session: Session, customer_id: UUID, today_: date, min_days: int) -> list[SalesInvoice]:
    """The customer's unpaid invoices at least `min_days` past their due date, oldest first."""
    return [i for i in pos_repo.invoices_of_customer(session, customer_id)
            if i.status in pos_repo.OPEN_INVOICE and (today_ - i.due_date).days >= max(min_days, 1)
            and i.total - i.amount_paid - i.credited > 0]


def _customer_of(session: Session, finding: FindingInfo) -> UUID | None:
    if finding.entity_type == CUSTOMER:
        return finding.entity_id
    if finding.entity_type == INVOICE and finding.entity_id is not None:
        invoice = pos_repo.get_invoice(session, finding.entity_id)
        return invoice.customer_id if invoice is not None else None
    return None


class SendPaymentReminder(ActionProvider):
    """A payment reminder to a customer who is well past due, by the business's reminder channel."""

    type = "pos.send_payment_reminder"
    title = "Remind the customer to pay"
    description = ("Sends the business's usual payment reminder (by SMS or email, as set in the company's reminder "
                   "channel) about the customer's oldest overdue invoices. Customers who asked not to be contacted "
                   "are not messaged.")
    check_codes = ("pos.customer_overdue",)
    needs_permission = "receivables.manage"
    auto_allowed = True
    params_schema = {"properties": {
        "customer_id": {"type": "uuid", "title": "Customer", "editable": False},
        "min_days_overdue": {"type": "integer", "title": "Chase invoices at least this many days overdue",
                             "minimum": "1", "maximum": "3650"},
        "channel": {"type": "string", "title": "Send by", "enum": ["sms", "email"]}},
        "required": ["customer_id", "min_days_overdue", "channel"]}
    rule_schema = {"properties": {
        "min_days_overdue": {"type": "integer", "title": "Only customers whose oldest invoice is at least this many "
                                                         "days overdue", "minimum": "1", "maximum": "3650"},
        "channel": {"type": "string", "title": "Only when sending by", "enum": ["sms", "email"]}}}

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        customer_id = _customer_of(session, finding)
        if customer_id is None or not unit_enabled(session, "crm"):
            return []
        channel = str(company_setting(session, finding.company_id, "reminder_channel"))
        customer = find_customer(session, customer_id)
        if channel not in ("sms", "email") or customer is None:
            return []                                           # the business has no way set up to remind
        if not (customer.email if channel == "email" else customer.phone):
            return []
        days = max(int(company_setting(session, finding.company_id, "reminder_min_days_overdue")), 1)
        today_ = company_today(session, finding.company_id)
        chase = overdue_invoices(session, customer_id, today_, days)[:MAX_INVOICES]
        if not chase:
            return []
        owed = sum((i.total - i.amount_paid - i.credited for i in chase), Decimal(0))
        cur = currency(session, finding.company_id)
        oldest = (today_ - chase[0].due_date).days
        return [Proposal(
            params={"customer_id": str(customer_id), "min_days_overdue": days, "channel": channel},
            description=(f"Send {customer.name} a payment reminder by {channel} about "
                         f"{len(chase)} overdue invoice{'s' if len(chase) != 1 else ''}."),
            facts={"Customer": customer.name, "Invoices to chase": ", ".join(i.number for i in chase),
                   "Owed on those": f"{cur} {money(owed)}", "Oldest overdue (days)": str(oldest),
                   "Sent by": channel})]

    def covered_by(self, conditions: dict[str, Any], params: dict[str, Any], finding: FindingInfo) -> bool:
        days = int(finding.figures.get("oldest_days_overdue", "0") or 0)
        if "min_days_overdue" in conditions and days < int(conditions["min_days_overdue"]):
            return False
        return conditions.get("channel") in (None, params.get("channel"))

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        customer = find_customer(session, UUID(str(params["customer_id"])))
        if customer is None or customer.company_id != context.company_id:
            return ActionResult(False, "The customer is no longer available")
        channel = str(params["channel"])
        if not (customer.email if channel == "email" else customer.phone):
            way = "email address" if channel == "email" else "phone number"
            return ActionResult(False, f"{customer.name} has no {way} on record")
        chase = overdue_invoices(session, customer.id, context.today, int(params["min_days_overdue"]))[:MAX_INVOICES]
        if not chase:
            return ActionResult(False, f"{customer.name} has nothing overdue by that many days now")
        sent, held_back, already = [], 0, 0
        for invoice in chase:
            try:
                outcome = receivables.send_reminder(session, invoice.id, channel=channel)
            except ValidationFailed as error:
                if "already" in error.message:
                    already += 1
                    continue
                raise
            if outcome["status"] == "queued":
                sent.append(invoice)
            else:
                held_back += 1
        refs = tuple((INVOICE, i.id, f"Invoice {i.number}") for i in sent)
        if sent:
            return ActionResult(True, f"Reminded {customer.name} by {channel} about "
                                      f"{', '.join(i.number for i in sent)}", refs)
        if held_back:
            return ActionResult(True, f"Nothing sent: {customer.name} asked not to be contacted")
        return ActionResult(True, f"{customer.name} was already reminded today")


class HoldCredit(ActionProvider):
    """Lower a late-paying customer's credit limit to what they owe now, so they cannot take more on account."""

    type = "pos.hold_credit"
    title = "Hold the customer's credit"
    description = ("Lowers the customer's credit limit to what they owe now, through the customers' credit-change "
                   "flow, so no more can be sold to them on account until they pay. Always needs a person.")
    check_codes = ("pos.credit_to_overdue_customer", "pos.customer_overdue")
    needs_permission = "customers.manage"
    auto_allowed = False
    params_schema = {"properties": {
        "customer_id": {"type": "uuid", "title": "Customer", "editable": False},
        "credit_limit": {"type": "number", "title": "New credit limit", "minimum": "0", "maximum": "100000000"}},
        "required": ["customer_id", "credit_limit"]}

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        customer_id = _customer_of(session, finding)
        if customer_id is None or not unit_enabled(session, "crm"):
            return []
        customer = find_customer(session, customer_id)
        if customer is None or customer.company_id != finding.company_id or customer.credit_limit <= 0:
            return []
        owed = credit.owed(session, customer_id).quantize(Decimal("0.01"))
        if owed <= 0 or owed >= customer.credit_limit:
            return []                                           # nothing owed, or the limit already holds them
        cur = currency(session, finding.company_id)
        return [Proposal(
            params={"customer_id": str(customer_id), "credit_limit": str(owed)},
            description=(f"Lower {customer.name}'s credit limit from {cur} {money(customer.credit_limit)} to "
                         f"{cur} {money(owed)}, what they owe now, so they cannot buy more on account."),
            facts={"Customer": customer.name, "Owes now": f"{cur} {money(owed)}",
                   "Credit limit now": f"{cur} {money(customer.credit_limit)}",
                   "Credit limit proposed": f"{cur} {money(owed)}"})]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        customer = find_customer(session, UUID(str(params["customer_id"])))
        if customer is None or customer.company_id != context.company_id:
            return ActionResult(False, "The customer is no longer available")
        new_limit = Decimal(str(params["credit_limit"]))
        if new_limit >= customer.credit_limit:
            return ActionResult(False, f"{customer.name}'s limit is already {customer.credit_limit:,.2f}, "
                                       "no higher than the one proposed")
        change_credit_limit(session, customer.id, new_limit,
                            "Credit held after an overdue balance (suggested by Intelligence and approved)")
        return ActionResult(True, f"{customer.name}'s credit limit is now {new_limit:,.2f}",
                            ((CUSTOMER, customer.id, customer.name),))
