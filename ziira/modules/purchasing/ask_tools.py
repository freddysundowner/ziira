"""Questions Ask Ziira may put to purchasing data: what suppliers are owed, and which bills fall due."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope
from ziira.modules.purchasing.permissions import ALL
from ziira.sdk import RequestContext, Session, company_today, provides

OWED = "(b.total - b.amount_paid - b.credited)"
UNPAID = "b.status in ('posted', 'part_paid')"


def _scope(context: RequestContext, params: dict[str, Any]) -> tuple[UUID, str, dict[str, Any]]:
    company = UUID(params["company_id"])
    clause, values = branch_scope(context, ALL, company).sql("b.branch_id")
    return company, clause, values


@provides(INTEL_ASK_TOOL)
class SupplierBalance(AskTool):
    name = "purchasing_supplier_balance"
    plain_label = "Checking what you owe a supplier"
    plain_label_sw = "Naangalia deni la msambazaji"
    description = ("What the business owes suppliers whose name contains the given text on posted, unpaid bills: the "
                   "balance and how much is past its due date.")
    parameters = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 80}}, "required": ["name"]}
    permissions = ALL
    personal_fields = ("supplier",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company, clause, values = _scope(context, params)
        pattern = "%" + str(params["name"]).replace("%", "").replace("_", "") + "%"
        rows = session.execute(text(
            f"select s.name, coalesce(sum({OWED}), 0) as balance, "
            f"coalesce(sum({OWED}) filter (where b.due_date < :today), 0) as overdue, count(b.id) as open_bills "
            f"from purchasing.supplier s left join purchasing.supplier_bill b on b.supplier_id = s.id and {UNPAID} "
            f"and {OWED} > 0 and {clause} where s.company_id = :company and s.name ilike :pattern "
            "group by s.id, s.name order by s.name limit 8"),
            {"company": company, "pattern": pattern, "today": company_today(session, company), **values}).all()
        return {"rows": [{"supplier": r.name, "balance": str(r.balance), "overdue": str(r.overdue),
                          "open_bills": r.open_bills} for r in rows],
                "note": "Counts only bills at branches you may see."}


@provides(INTEL_ASK_TOOL)
class BillsDue(AskTool):
    name = "purchasing_bills_due"
    plain_label = "Looking at bills due"
    plain_label_sw = "Naangalia bili zinazodaiwa"
    description = ("Unpaid supplier bills that are overdue or fall due within the next days (default 7), earliest due "
                   "first: supplier, bill number, due date and amount still owed.")
    parameters = {"type": "object", "properties": {
        "days_ahead": {"type": "integer", "minimum": 0, "maximum": 90},
        "limit": {"type": "integer", "minimum": 1, "maximum": 30}}}
    permissions = ALL
    personal_fields = ("supplier",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import timedelta

        company, clause, values = _scope(context, params)
        today = company_today(session, company)
        until = today + timedelta(days=int(params.get("days_ahead", 7)))
        rows = session.execute(text(
            f"select s.name, b.number, b.due_date, {OWED} as owed from purchasing.supplier_bill b "
            f"join purchasing.supplier s on s.id = b.supplier_id where b.company_id = :company and {UNPAID} "
            f"and {OWED} > 0 and b.due_date <= :until and {clause} order by b.due_date, b.number limit :n"),
            {"company": company, "until": until, "n": int(params.get("limit", 15)), **values}).all()
        return {"rows": [{"supplier": r.name, "bill": r.number, "due_date": r.due_date.isoformat(),
                          "days_overdue": max((today - r.due_date).days, 0), "owed": str(r.owed)} for r in rows],
                "total_owed": str(sum((r.owed for r in rows), 0)), "note": "Counts only bills at branches you may see."}
