"""Questions Ask Ziira may put to sales data: totals, best sellers and voids, within the branches the person may see."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, date_range, requested_branch
from ziira.modules.pos.permissions import SALES_REFUND, SALES_SELL, SALES_VOID, TILL_REVIEW
from ziira.sdk import RequestContext, Session, provides

SALES_PERMISSIONS = (SALES_SELL, TILL_REVIEW, SALES_VOID, SALES_REFUND)
PERIOD = {"date_from": {"type": "string", "format": "date", "description": "First day, YYYY-MM-DD"},
          "date_to": {"type": "string", "format": "date", "description": "Last day, YYYY-MM-DD"}}
BRANCH = {"branch_id": {"type": "string", "format": "uuid",
                        "description": "Only this branch (default: all you may see)"}}


def _where(context: RequestContext, params: dict[str, Any], alias: str = "s") -> tuple[str, dict[str, Any]]:
    """The conditions shared by every sales question: the company, the period, and the branches the person may see."""
    company = UUID(params["company_id"])
    scope = branch_scope(context, SALES_PERMISSIONS, company)
    branch = requested_branch(scope, params)
    start, end = date_range(params)
    clause, scope_params = scope.sql(f"{alias}.branch_id")
    sql = f"{alias}.company_id = :company and {alias}.business_date between :d1 and :d2 and {clause}"
    values: dict[str, Any] = {"company": company, "d1": start, "d2": end, **scope_params}
    if branch:
        sql += f" and {alias}.branch_id = :branch"
        values["branch"] = branch
    return sql, values


@provides(INTEL_ASK_TOOL)
class SalesSummary(AskTool):
    name = "pos_sales_summary"
    description = ("Sales between two dates: how many sales and their total, and how many were voided, for each branch "
                   "(or each day). Counts only branches the person may see.")
    parameters = {"type": "object", "properties": {**PERIOD, **BRANCH, "by": {
        "type": "string", "enum": ["branch", "day"], "description": "Break down by branch (default) or by day"}},
        "required": ["date_from", "date_to"]}
    permissions = SALES_PERMISSIONS

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        where, values = _where(context, params)
        by_day = params.get("by") == "day"
        label = "s.business_date::text" if by_day else "b.name"
        rows = session.execute(text(
            f"select {label} as label, count(*) filter (where s.status = 'posted') as sales_count, "
            "coalesce(sum(s.total) filter (where s.status = 'posted'), 0) as sales_total, "
            "count(*) filter (where s.status = 'voided') as voided_count, "
            "coalesce(sum(s.total) filter (where s.status = 'voided'), 0) as voided_total "
            f"from pos.sale s join kernel.branch b on b.id = s.branch_id where {where} "
            "group by 1 order by 1 limit 40"), values).all()
        key = "day" if by_day else "branch"
        return {"rows": [{key: r.label, "sales_count": r.sales_count, "sales_total": str(r.sales_total),
                          "voided_count": r.voided_count, "voided_total": str(r.voided_total)} for r in rows],
                "total_sales_count": sum(r.sales_count for r in rows),
                "total_sales": str(sum((r.sales_total for r in rows), 0)),
                "note": "Only branches you may see are included."}


@provides(INTEL_ASK_TOOL)
class TopProducts(AskTool):
    name = "pos_top_products"
    description = "The best-selling products between two dates, by sales value, with the quantity sold."
    parameters = {"type": "object", "properties": {**PERIOD, **BRANCH, "limit": {
        "type": "integer", "minimum": 1, "maximum": 20}}, "required": ["date_from", "date_to"]}
    permissions = SALES_PERMISSIONS

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        where, values = _where(context, params)
        rows = session.execute(text(
            "select p.name, sum(l.quantity) as quantity, sum(l.line_total) as sales_value "
            "from pos.sale_line l join pos.sale s on s.id = l.sale_id join products.product p on p.id = l.product_id "
            f"where s.status = 'posted' and {where} group by p.id, p.name order by sales_value desc, p.name "
            "limit :n"), {**values, "n": int(params.get("limit", 10))}).all()
        return {"rows": [{"product": r.name, "quantity": f"{r.quantity.normalize():f}",
                          "sales_value": str(r.sales_value)} for r in rows],
                "note": "Only branches you may see are included."}


@provides(INTEL_ASK_TOOL)
class Voids(AskTool):
    name = "pos_voids"
    description = "Voided sales between two dates: how many and their value, with the latest (number, date, total)."
    parameters = {"type": "object", "properties": {**PERIOD, **BRANCH}, "required": ["date_from", "date_to"]}
    permissions = SALES_PERMISSIONS
    personal_fields = ("voided_by",)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        where, values = _where(context, params)
        totals = session.execute(text(
            "select count(*) as n, coalesce(sum(s.total), 0) as total from pos.sale s "
            f"where s.status = 'voided' and {where}"), values).one()
        rows = session.execute(text(
            "select s.number, s.business_date, s.total, b.name as branch, u.full_name as voided_by from pos.sale s "
            "join kernel.branch b on b.id = s.branch_id left join kernel.app_user u on u.id = s.voided_by "
            f"where s.status = 'voided' and {where} order by s.business_date desc, s.number desc limit 20"),
            values).all()
        return {"voided_count": totals.n, "voided_total": str(totals.total),
                "rows": [{"number": r.number, "date": r.business_date.isoformat(), "total": str(r.total),
                          "branch": r.branch, "voided_by": r.voided_by} for r in rows],
                "note": "Only branches you may see are included."}
