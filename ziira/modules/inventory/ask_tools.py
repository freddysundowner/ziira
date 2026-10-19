"""Questions Ask Ziira may put to stock data: what is on hand, and what is running low, at the person's branches."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_ASK_TOOL, AskTool, branch_scope, requested_branch
from ziira.modules.inventory.intel_checks.common import ON_HAND_CTE
from ziira.modules.inventory.permissions import STOCK_COST, STOCK_VIEW
from ziira.sdk import RequestContext, Session, provides

BRANCH = {"branch_id": {"type": "string", "format": "uuid",
                        "description": "Only this branch (default: all you may see)"}}


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _rows(session: Session, context: RequestContext, params: dict[str, Any], condition: str, order: str,
          extra: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    company = UUID(params["company_id"])
    scope = branch_scope(context, (STOCK_VIEW,), company)
    branch = requested_branch(scope, params)
    cost = branch_scope(context, (STOCK_COST,), company)
    clause, scope_params = scope.sql("o.branch_id")
    rows = session.execute(text(
        f"with {ON_HAND_CTE} select p.name, p.sku, b.name as branch, o.branch_id, o.qty, p.reorder_level, "
        "o.qty * coalesce(pc.average_cost, 0) as value from onhand o join products.product p on p.id = o.product_id "
        "join kernel.branch b on b.id = o.branch_id "
        "left join inventory.product_cost pc on pc.company_id = :company and pc.product_id = o.product_id "
        f"where p.is_active and p.product_type = 'stock' and {clause} and {condition}"
        f"{' and o.branch_id = :branch' if branch else ''} order by {order} limit :n"),
        {"company": company, "branch": branch, "n": limit, **scope_params, **extra}).all()
    return [{"product": r.name, "sku": r.sku, "branch": r.branch, "on_hand": _qty(r.qty),
             "reorder_level": _qty(r.reorder_level) if r.reorder_level is not None else None,
             **({"stock_value": str(r.value.quantize(Decimal("0.01")))} if cost.allows(r.branch_id) else {})}
            for r in rows]


@provides(INTEL_ASK_TOOL)
class StockOnHand(AskTool):
    name = "inventory_stock_on_hand"
    plain_label = "Counting stock on hand"
    plain_label_sw = "Nahesabu hisa iliyopo"
    description = ("How much of a product is in stock at each branch: products whose name or code contains the given "
                   "text. Shows what the stock is worth only to people allowed to see costs.")
    parameters = {"type": "object", "properties": {**BRANCH, "product": {"type": "string", "maxLength": 80}},
                  "required": ["product"]}
    permissions = (STOCK_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        pattern = "%" + str(params["product"]).replace("%", "").replace("_", "") + "%"
        return {"rows": _rows(session, context, params, "(p.name ilike :pattern or p.sku ilike :pattern)",
                              "p.name, b.name", {"pattern": pattern}, 30),
                "note": "Only branches you may see are included."}


@provides(INTEL_ASK_TOOL)
class LowStock(AskTool):
    name = "inventory_low_stock"
    plain_label = "Checking stock levels"
    plain_label_sw = "Naangalia viwango vya hisa"
    description = "Products at or below their reorder level at each branch, the most short first."
    parameters = {"type": "object", "properties": {**BRANCH, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}}
    permissions = (STOCK_VIEW,)

    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        return {"rows": _rows(session, context, params, "p.reorder_level > 0 and o.qty <= p.reorder_level",
                              "o.qty - p.reorder_level, p.name", {}, int(params.get("limit", 15))),
                "note": "Only branches you may see are included."}
