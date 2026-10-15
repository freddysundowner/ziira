"""What Intelligence itself may do about its own findings: nudge the people who can work through the exceptions
inbox. A message only; it changes no record."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.domain.action_rules import Proposal
from ziira.modules.intel.public import ActionContext, ActionProvider, ActionResult, FindingInfo, nudge_people
from ziira.sdk import Session, company_setting, recipients_with_permission

REVIEW_PERMISSION = "exceptions.manage"             # who works the exceptions inbox, and so who is reminded
NOTE_SCHEMA: dict[str, Any] = {"properties": {
    "note": {"type": "string", "title": "Add a note to the message", "max_length": 200}}}


def reachable(session: Session, company_id: UUID, branch_id: UUID | None, permission: str) -> list[str]:
    """Names of the people who hold `permission` where the company or branch is and have an address on the alert
    channel (what a nudge needs)."""
    channel = str(company_setting(session, company_id, "intel_alert_channel"))
    return [p.full_name for p in recipients_with_permission(session, permission)
            if p.covers(permission, company_id, branch_id) and (p.phone if channel == "sms" else p.email)]


def alert_channel_on(session: Session, info: FindingInfo) -> bool:
    return str(company_setting(session, info.company_id, "intel_alert_channel")) in ("sms", "email")


class NudgeExceptionsReviewers(ActionProvider):
    """Remind the people who work the exceptions inbox that items have been waiting."""

    type = "intel.nudge_exceptions_reviewers"
    title = "Remind the reviewers"
    description = "Sends a short message to the people who can work through the exceptions inbox."
    check_codes = ("controls.exceptions_backlog",)
    needs_permission = "findings.manage"
    auto_allowed = True
    params_schema = NOTE_SCHEMA

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        if not alert_channel_on(session, finding):
            return []                                    # there is no way to reach them
        if not reachable(session, finding.company_id, finding.branch_id, REVIEW_PERMISSION):
            return []
        return [Proposal(params={}, description="Send a reminder to the people who work the exceptions inbox.",
                         facts={"Waiting": finding.figures.get("items", ""),
                                "Oldest": finding.figures.get("oldest", "")})]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        still = session.execute(text(
            "select count(*) from kernel.exception_item where status = 'open' "
            "and (company_id = :c or company_id is null)"),
            {"c": str(context.company_id)}).scalar_one()
        if not still:
            return ActionResult(False, "Nothing is waiting in the exceptions inbox any more")
        message = f"{context.finding_summary} {params.get('note', '')}".strip()
        sent = nudge_people(session, company_id=context.company_id, branch_id=context.branch_id,
                            permission=REVIEW_PERMISSION, text=message, finding_id=context.finding_id,
                            today=context.today)
        if not sent.told and not sent.already:
            return ActionResult(False, "No one with an address on file could be reached (check the alert channel)")
        if not sent.told:
            return ActionResult(True, "They were already reminded today: " + ", ".join(sent.already))
        return ActionResult(True, "Reminder sent to " + ", ".join(sent.told))
