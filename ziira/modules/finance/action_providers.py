"""What Intelligence may do about the books: remind the people who reconcile the bank that a reconciliation was left
open. A message only; it reconciles nothing."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.permissions import BANK_RECONCILE
from ziira.modules.intel.public import (
    ActionContext,
    ActionProvider,
    ActionResult,
    FindingInfo,
    Proposal,
    nudge_people,
)
from ziira.sdk import Session, company_setting, recipients_with_permission

RECONCILIATION = "finance.bank_reconciliation"


def still_open(session: Session, reconciliation_id: UUID) -> bool:
    return session.execute(text("select 1 from finance.bank_reconciliation where id = :i and status = 'in_progress'"),
                           {"i": str(reconciliation_id)}).first() is not None


class AskForReconciliation(ActionProvider):
    """Remind the people who reconcile the bank that a reconciliation has been left open."""

    type = "finance.ask_for_reconciliation"
    title = "Ask for the reconciliation to be finished"
    description = ("Sends a short message, by the business's alert channel, to the people who can reconcile the bank, "
                   "asking them to finish the reconciliation that has been open too long.")
    check_codes = ("finance.stale_reconciliation",)
    needs_permission = "findings.manage"
    auto_allowed = True
    params_schema = {"properties": {"note": {"type": "string", "title": "Add a note to the message",
                                             "max_length": 200}}}

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        if finding.entity_id is None or not still_open(session, finding.entity_id):
            return []
        channel = str(company_setting(session, finding.company_id, "intel_alert_channel"))
        names = [p.full_name for p in recipients_with_permission(session, BANK_RECONCILE)
                 if p.covers(BANK_RECONCILE, finding.company_id, finding.branch_id)
                 and (p.phone if channel == "sms" else p.email if channel == "email" else None)]
        if not names:
            return []
        return [Proposal(params={}, description=f"Ask {', '.join(names)} to finish the open bank reconciliation.",
                         facts={"Open for (days)": finding.figures.get("days_open", ""),
                                "Will be told": ", ".join(names)})]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        found = session.execute(text("select entity_id from intel.finding where id = :i"),
                                {"i": str(context.finding_id)}).first()
        if found is None or found.entity_id is None or not still_open(session, found.entity_id):
            return ActionResult(False, "The reconciliation is no longer open: nobody needs reminding")
        message = f"{context.finding_summary} {params.get('note', '')}".strip()
        sent = nudge_people(session, company_id=context.company_id, branch_id=context.branch_id,
                            permission=BANK_RECONCILE, text=message, finding_id=context.finding_id, today=context.today)
        if sent.told:
            return ActionResult(True, "Asked " + ", ".join(sent.told))
        if sent.already:
            return ActionResult(True, "They were already asked today: " + ", ".join(sent.already))
        return ActionResult(False, "No one who reconciles the bank could be reached (check the alert channel)")
