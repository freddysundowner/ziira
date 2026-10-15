"""What Intelligence may do about decisions that are waiting on people: remind whoever can make them. A message only; it
approves nothing and changes no record."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import (
    ActionContext,
    ActionProvider,
    ActionResult,
    FindingInfo,
    Proposal,
    nudge_people,
)
from ziira.modules.people.permissions import LEAVE_APPROVE, PAYROLL_APPROVE, PAYROLL_PAY
from ziira.sdk import Session, company_setting, recipients_with_permission

LEAVE = "people.leave_request"
RUN = "people.payroll_run"
UNFINISHED_RUN = ("draft", "calculated", "pending_approval", "approved", "posted")


def decider_permission(kind: str, status: str | None) -> str:
    """Who is waited for: leave is decided by `leave.approve`; a run not yet approved by `payroll.approve`, one approved
    but not paid by `payroll.pay`."""
    if kind == LEAVE:
        return LEAVE_APPROVE
    return PAYROLL_PAY if status in ("approved", "posted") else PAYROLL_APPROVE


def reachable(session: Session, company_id: UUID, branch_id: UUID | None, permission: str) -> list[str]:
    channel = str(company_setting(session, company_id, "intel_alert_channel"))
    if channel not in ("sms", "email"):
        return []
    return [p.full_name for p in recipients_with_permission(session, permission)
            if p.covers(permission, company_id, branch_id) and (p.phone if channel == "sms" else p.email)]


class NudgeApprover(ActionProvider):
    """Remind the people who can decide a leave request or approve and pay a payroll run that it is waiting."""

    type = "people.nudge_approver"
    title = "Remind whoever can decide"
    description = ("Sends a short message, by the business's alert channel, to the people who can approve the leave "
                   "request or the payroll run that has been waiting too long.")
    check_codes = ("people.leave_waiting", "people.payroll_overdue")
    needs_permission = "findings.manage"
    auto_allowed = True
    params_schema = {"properties": {"note": {"type": "string", "title": "Add a note to the message",
                                             "max_length": 200}}}

    def _state(self, session: Session, kind: str, record_id: UUID) -> str | None:
        """The leave request's or run's status while it still waits for a decision, else None."""
        if kind == LEAVE:
            row = session.execute(text("select status from people.leave_request where id = :i and status = 'pending'"),
                                  {"i": str(record_id)}).first()
        else:
            row = session.execute(text("select status from people.payroll_run where id = :i and status = any(:s)"),
                                  {"i": str(record_id), "s": list(UNFINISHED_RUN)}).first()
        return str(row.status) if row else None

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        if finding.entity_type not in (LEAVE, RUN) or finding.entity_id is None:
            return []
        status = self._state(session, finding.entity_type, finding.entity_id)
        if status is None:
            return []
        permission = decider_permission(finding.entity_type, status)
        names = reachable(session, finding.company_id, finding.branch_id, permission)
        if not names:
            return []                                    # no channel set, or nobody to tell
        what = "leave request" if finding.entity_type == LEAVE else "payroll run"
        return [Proposal(params={}, description=f"Remind {', '.join(names)} that a {what} is waiting for a decision.",
                         facts={"Waiting": finding.figures.get("days_waiting") or finding.figures.get("days_late", ""),
                                "Will be told": ", ".join(names)})]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        finding = session.execute(text("select entity_type, entity_id from intel.finding where id = :i"),
                                  {"i": str(context.finding_id)}).first()
        if finding is None or finding.entity_id is None:
            return ActionResult(False, "The finding is gone")
        status = self._state(session, finding.entity_type, finding.entity_id)
        if status is None:
            return ActionResult(False, "It has been decided already: nobody needs reminding")
        permission = decider_permission(finding.entity_type, status)
        message = f"{context.finding_summary} {params.get('note', '')}".strip()
        sent = nudge_people(session, company_id=context.company_id, branch_id=context.branch_id, permission=permission,
                            text=message, finding_id=context.finding_id, today=context.today)
        if sent.told:
            return ActionResult(True, "Reminder sent to " + ", ".join(sent.told))
        if sent.already:
            return ActionResult(True, "They were already reminded today: " + ", ".join(sent.already))
        return ActionResult(False, "No one who can decide could be reached (check the alert channel)")
