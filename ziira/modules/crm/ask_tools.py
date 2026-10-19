"""Questions Ask Ziira may put to customer data: what a customer owes, and who is overdue."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.permissions import CUSTOMERS_VIEW
from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, company_visible, requested_branch
from ziira.sdk import Forbidden, RequestContext, Session, ValidationFailed, company_today, provides

RECEIVABLES_VIEW = "receivables.view"       # POS's permission; named here because CRM may not import POS code
OPEN = "('issued', 'part_paid')"
OWED = "(i.total - i.amount_paid - i.credited)"


def _guard(session: Session, context: RequestContext, params: dict[str, Any]) -> tuple[UUID, Any, UUID | None]:
    """The company, the branches whose invoices the person may see, and the branch asked about."""
    if not session.execute(text("select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
                                "and tenant_id = kernel.current_tenant()")).first():
        raise ValidationFailed("Customer balances need the sales module, which is not switched on")
    company = UUID(params["company_id"])
    if not company_visible(context, CUSTOMERS_VIEW, company):
        raise Forbidden("You do not have permission to see customers")
    scope = branch_scope(context, (RECEIVABLES_VIEW,), company)
    if scope.nothing:
        raise Forbidden("You do not have permission to see what customers owe")
    return company, scope, requested_branch(scope, params)


@provides(INTEL_ASK_TOOL)
class CustomerBalance(AskTool):
    name = "crm_customer_balance"
    plain_label = "Checking what a customer owes"
    plain_label_sw = "Naangalia deni la mteja"
    description = ("What customers whose name contains the given text owe on open invoices: balance, how much of it is "
                   "overdue, and their credit limit. Counts only invoices at branches the person may see.")
    parameters = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 80}}, "required": ["name"]}
    permissions = (CUSTOMERS_VIEW, RECEIVABLES_VIEW)
    personal_fields = ("customer",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company, scope, _ = _guard(session, context, params)
        clause, scope_params = scope.sql("i.branch_id")
        pattern = "%" + str(params["name"]).replace("%", "").replace("_", "") + "%"
        rows = session.execute(text(
            f"select c.name, c.credit_limit, coalesce(sum({OWED}), 0) as balance, "
            f"coalesce(sum({OWED}) filter (where i.due_date < :today), 0) as overdue, count(i.id) as open_invoices "
            f"from crm.customer c left join pos.sales_invoice i on i.customer_id = c.id and i.status in {OPEN} "
            f"and i.company_id = :company and {clause} where c.company_id = :company and c.name ilike :pattern "
            "group by c.id, c.name, c.credit_limit order by c.name limit 8"),
            {"company": company, "pattern": pattern, "today": company_today(session, company), **scope_params}).all()
        return {"rows": [{"customer": r.name, "balance": str(r.balance), "overdue": str(r.overdue),
                          "open_invoices": r.open_invoices, "credit_limit": str(r.credit_limit)} for r in rows],
                "note": "Counts only invoices at branches you may see."}


@provides(INTEL_ASK_TOOL)
class OverdueCustomers(AskTool):
    name = "crm_overdue_customers"
    plain_label = "Looking at overdue customers"
    plain_label_sw = "Naangalia wateja waliochelewa kulipa"
    description = ("Customers with invoices past their due date, largest overdue amount first: the amount, how many "
                   "invoices and how long the oldest has been overdue.")
    parameters = {"type": "object", "properties": {
        "branch_id": {"type": "string", "format": "uuid"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}}
    permissions = (CUSTOMERS_VIEW, RECEIVABLES_VIEW)
    personal_fields = ("customer",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company, scope, branch = _guard(session, context, params)
        clause, scope_params = scope.sql("i.branch_id")
        extra = " and i.branch_id = :branch" if branch else ""
        today = company_today(session, company)
        rows = session.execute(text(
            f"select c.name, sum({OWED}) as overdue, count(*) as invoices, min(i.due_date) as oldest_due "
            "from pos.sales_invoice i join crm.customer c on c.id = i.customer_id "
            f"where i.company_id = :company and i.status in {OPEN} and i.due_date < :today and {OWED} > 0 and {clause}"
            f"{extra} group by c.id, c.name order by overdue desc, c.name limit :n"),
            {"company": company, "today": today, "branch": branch, "n": int(params.get("limit", 10)),
             **scope_params}).all()
        return {"rows": [{"customer": r.name, "overdue": str(r.overdue), "invoices": r.invoices,
                          "oldest_due": r.oldest_due.isoformat(), "days_overdue": (today - r.oldest_due).days}
                         for r in rows], "note": "Counts only invoices at branches you may see."}
