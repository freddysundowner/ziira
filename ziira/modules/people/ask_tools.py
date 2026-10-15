"""Questions Ask Ziira may put to people data: headcount and leave waiting for approval.

Pay, bank details and payroll are never offered to the assistant.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, requested_branch
from ziira.modules.people.permissions import (
    ATTENDANCE_MANAGE,
    EMPLOYEES_MANAGE,
    EMPLOYEES_VIEW,
    LEAVE_APPROVE,
)
from ziira.sdk import RequestContext, Session, provides

READERS = (EMPLOYEES_VIEW, EMPLOYEES_MANAGE, ATTENDANCE_MANAGE, LEAVE_APPROVE)
BRANCH = {"branch_id": {"type": "string", "format": "uuid", "description": "Only this branch"}}


@provides(INTEL_ASK_TOOL)
class Headcount(AskTool):
    name = "people_headcount"
    description = "How many employees are active, on leave or have left, for each branch the person may see."
    parameters = {"type": "object", "properties": BRANCH}
    permissions = READERS

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company = UUID(params["company_id"])
        scope = branch_scope(context, READERS, company)
        branch = requested_branch(scope, params)
        clause, values = scope.sql("e.branch_id")
        rows = session.execute(text(
            "select coalesce(b.name, 'No branch') as branch, "
            "count(*) filter (where e.status = 'active') as active, "
            "count(*) filter (where e.status = 'on_leave') as on_leave, "
            "count(*) filter (where e.status = 'terminated') as left_the_business "
            "from people.employee e left join kernel.branch b on b.id = e.branch_id "
            f"where e.company_id = :company and {clause}{' and e.branch_id = :branch' if branch else ''} "
            "group by 1 order by 1 limit 40"), {"company": company, "branch": branch, **values}).all()
        return {"rows": [{"branch": r.branch, "active": r.active, "on_leave": r.on_leave,
                          "left_the_business": r.left_the_business} for r in rows],
                "note": "Only branches you may see are included."}


@provides(INTEL_ASK_TOOL)
class LeavePending(AskTool):
    name = "people_leave_pending"
    description = "Leave requests waiting for approval: who asked, the dates and the number of days (latest first)."
    parameters = {"type": "object", "properties": {**BRANCH, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}}
    permissions = (LEAVE_APPROVE, EMPLOYEES_MANAGE, ATTENDANCE_MANAGE)
    personal_fields = ("employee",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        company = UUID(params["company_id"])
        scope = branch_scope(context, (LEAVE_APPROVE, EMPLOYEES_MANAGE, ATTENDANCE_MANAGE), company)
        branch = requested_branch(scope, params)
        clause, values = scope.sql("e.branch_id")
        rows = session.execute(text(
            "select e.full_name, r.start_date, r.end_date, r.days from people.leave_request r "
            "join people.employee e on e.id = r.employee_id "
            f"where e.company_id = :company and r.status = 'pending' and {clause}"
            f"{' and e.branch_id = :branch' if branch else ''} order by r.start_date desc, e.full_name limit :n"),
            {"company": company, "branch": branch, "n": int(params.get("limit", 15)), **values}).all()
        return {"rows": [{"employee": r.full_name, "from": r.start_date.isoformat(), "to": r.end_date.isoformat(),
                          "days": f"{r.days.normalize():f}"} for r in rows], "count_waiting": len(rows),
                "note": "Only branches you may see are included."}
