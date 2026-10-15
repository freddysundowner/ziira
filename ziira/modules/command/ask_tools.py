"""The Command Center's question for Ask Ziira: the day's figures for a period, from the stored copy."""

from typing import Any
from uuid import UUID

from ziira.modules.command.permissions import COMMAND_VIEW
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, date_range, requested_branch
from ziira.sdk import RequestContext, Session, provides


@provides(INTEL_ASK_TOOL)
class Figures(AskTool):
    name = "command_figures"
    description = ("The business's key figures for a period (sales, voids, refunds, stock value, overdue balances), "
                   "each against the period of the same length just before it, company-wide and by branch. These are "
                   "the figures shown in the Command Center; money and counts are added over the days, percentages "
                   "averaged.")
    parameters = {"type": "object", "properties": {
        "date_from": {"type": "string", "format": "date", "description": "First day, YYYY-MM-DD"},
        "date_to": {"type": "string", "format": "date", "description": "Last day, YYYY-MM-DD"},
        "branch_id": {"type": "string", "format": "uuid", "description": "Only this branch"}},
        "required": ["date_from", "date_to"]}
    permissions = (COMMAND_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company = UUID(params["company_id"])
        start, end = date_range(params, max_days=100)
        branch = requested_branch(branch_scope(context, (COMMAND_VIEW,), company), params)
        rows = [r for r in pulse.summarise(session, context, company, start, end)
                if branch is None or r.branch_id in (None, branch)]
        return {"rows": [{"figure": r.label, "kind": r.kind, "value": str(r.value),
                          "before": str(r.previous) if r.previous is not None else None,
                          "branch": r.branch_name or "Whole company"} for r in rows[:40]],
                "note": "Stored figures; they may lag the latest sales by up to an hour."}
