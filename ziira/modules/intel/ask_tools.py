"""Intelligence's own ask tools: the findings the person may see."""

from typing import Any
from uuid import UUID

from ziira.modules.intel.domain.llm import AskTool
from ziira.modules.intel.permissions import FINDINGS_VIEW
from ziira.modules.intel.repository import findings_repo as repo
from ziira.modules.intel.services.explain import PERSON_KINDS
from ziira.sdk import RequestContext, Session

STATUSES = ["new", "sent", "acknowledged", "explained", "resolved", "dismissed"]
SEVERITIES = ["info", "low", "medium", "high", "critical"]


class ListFindings(AskTool):
    name = "intel_list_findings"
    description = ("List findings (things the automated checks flagged for attention) the person may see, most serious "
                   "first: severity, area, a plain summary, the recommended action and the money at stake. Open "
                   "findings unless a status is given.")
    parameters = {"type": "object", "properties": {
        "status": {"type": "string", "enum": STATUSES, "description": "Only this state (default: open ones)"},
        "severity": {"type": "string", "enum": SEVERITIES},
        "branch_id": {"type": "string", "format": "uuid", "description": "Only this branch"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25}}}
    permissions = (FINDINGS_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        sql, scope = repo.scope_clause(context, FINDINGS_VIEW)
        status = params.get("status")
        rows = repo.list_findings(
            session, sql, scope, statuses=[status] if status else ["new", "sent", "acknowledged", "explained"],
            severities=[params["severity"]] if params.get("severity") else None, area=None,
            company_id=UUID(params["company_id"]),
            branch_id=UUID(params["branch_id"]) if params.get("branch_id") else None, check_code=None,
            owner_user_id=None, search=None, limit=int(params.get("limit", 10)), offset=0)
        return {"rows": [{"severity": r.severity, "area": r.area, "status": r.status, "summary": r.summary,
                          "recommended_action": r.recommended_action,
                          "amount": str(r.amount) if r.amount is not None else None,
                          "first_seen": r.first_seen_at.date().isoformat(), "finding_id": str(r.id)} for r in rows]}


class FindingDetail(AskTool):
    name = "intel_finding_detail"
    description = "One finding in full: its summary, figures and the records behind it. Use a finding_id from a list."
    parameters = {"type": "object", "properties": {"finding_id": {"type": "string", "format": "uuid"}},
                  "required": ["finding_id"]}
    permissions = (FINDINGS_VIEW,)
    personal_fields = ("employee_label", "customer_label", "supplier_label", "person_label")

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        row = repo.get_finding(session, UUID(params["finding_id"]))
        if row is None or str(row.company_id) != params["company_id"] or not context.can(
                FINDINGS_VIEW, company_id=row.company_id, branch_id=row.branch_id):
            return {"rows": [], "note": "No such finding that you may see."}
        evidence = row.evidence or {}
        records = [{"type": r.get("type"),
                    (f"{PERSON_KINDS[r['type']].lower()}_label" if r.get("type") in PERSON_KINDS else "label"):
                    r.get("label")} for r in evidence.get("records", [])]
        return {"rows": [{"severity": row.severity, "area": row.area, "status": row.status, "summary": row.summary,
                          "recommended_action": row.recommended_action,
                          "amount": str(row.amount) if row.amount is not None else None,
                          "period_start": row.period_start.isoformat() if row.period_start else None,
                          "period_end": row.period_end.isoformat() if row.period_end else None,
                          "figures": {str(k): str(v) for k, v in (evidence.get("figures") or {}).items()},
                          "records": records}]}
