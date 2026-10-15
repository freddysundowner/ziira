"""Questions Ask Ziira may put to the books: profit and loss for a period, and the cash position.

They call the report services, which already restrict what a person sees to the branches their role covers.
"""

from typing import Any
from uuid import UUID

from ziira.modules.finance.permissions import REPORTS_VIEW
from ziira.modules.finance.services import statements
from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, date_range, requested_branch
from ziira.sdk import RequestContext, Session, provides

PERIOD = {"date_from": {"type": "string", "format": "date", "description": "First day, YYYY-MM-DD"},
          "date_to": {"type": "string", "format": "date", "description": "Last day, YYYY-MM-DD"},
          "branch_id": {"type": "string", "format": "uuid", "description": "Only this branch (default: all you see)"}}


def _lines(lines: list[Any], limit: int = 8) -> list[dict[str, str]]:
    return [{"account": line.name, "amount": str(line.amount)} for line in lines[:limit]]


@provides(INTEL_ASK_TOOL)
class ProfitAndLoss(AskTool):
    name = "finance_profit_and_loss"
    description = ("Income, cost of sales, gross profit, expenses and net profit between two dates, from the books, "
                   "for all branches the person may see or one branch; with the largest income and expense accounts.")
    parameters = {"type": "object", "properties": PERIOD, "required": ["date_from", "date_to"]}
    permissions = (REPORTS_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company = UUID(params["company_id"])
        start, end = date_range(params)
        branch = requested_branch(branch_scope(context, (REPORTS_VIEW,), company), params)
        pnl = statements.profit_and_loss(session, company, start, end, branch_id=branch).consolidated
        return {"rows": [{"total_income": str(pnl.total_income), "total_cost_of_sales": str(pnl.total_cost_of_sales),
                          "gross_profit": str(pnl.gross_profit), "total_expenses": str(pnl.total_expenses),
                          "net_profit": str(pnl.net_profit)}],
                "income_accounts": _lines(pnl.income), "expense_accounts": _lines(pnl.expenses),
                "note": "From the books for the branches you may see."}


@provides(INTEL_ASK_TOOL)
class CashPosition(AskTool):
    name = "finance_cash_position"
    description = ("Cash, bank, mobile-money and card balances: the balance at the start and at the end of the period "
                   "and what moved it, from the books.")
    parameters = {"type": "object", "properties": PERIOD, "required": ["date_from", "date_to"]}
    permissions = (REPORTS_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company = UUID(params["company_id"])
        start, end = date_range(params)
        branch = requested_branch(branch_scope(context, (REPORTS_VIEW,), company), params)
        flow = statements.cash_flow(session, company, start, end, branch_id=branch).flow
        return {"rows": [{"opening": str(flow.opening), "closing": str(flow.closing),
                          "net_movement": str(flow.net_movement)}],
                "movements": [{"cause": label, "amount": str(amount)} for label, amount in flow.movements[:12]],
                "note": "From the books for the branches you may see."}
