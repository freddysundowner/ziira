"""What Intelligence may do about buying findings, through Purchasing's and Products' own services.

Both actions need a person: a draft purchase request (the person decides whether to send it) and a new selling price
(a price is money, so it is never automatic).
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import ActionContext, ActionProvider, ActionResult, FindingInfo, Proposal
from ziira.modules.inventory.public import branch_stock_position
from ziira.modules.products.public import find_product, product_labels, selling_prices, set_selling_price
from ziira.modules.purchasing.domain import repricing, watch
from ziira.modules.purchasing.intel_checks import money, pct
from ziira.modules.purchasing.services import orders
from ziira.modules.purchasing.services.common import unit_enabled
from ziira.sdk import Session, company_today

PRODUCT = "products.product"
SUPPLIER = "purchasing.supplier"
SALES_DAYS = 30
OPEN_REQUEST = ("draft", "pending_approval", "approved")


def _currency(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def _product_id(finding: FindingInfo) -> UUID | None:
    found = finding.record_id(PRODUCT)
    if found is None and finding.entity_type == PRODUCT:
        return finding.entity_id
    return found


def _plain(value: Decimal) -> str:
    return f"{value.normalize():f}" if value != 0 else "0"


# --------------------------------------------------------------------------- draft purchase request
def usual_suppliers(session: Session, company_id: UUID, product_id: UUID, limit: int = 2) -> list[dict[str, Any]]:
    """The suppliers this product was bought from most often (then most recently), with their latest cost."""
    rows = session.execute(text(
        "select s.id, s.name, count(*) as times, max(sp.effective_date) as last_day, "
        "(array_agg(sp.unit_cost order by sp.effective_date desc, sp.created_at desc))[1] as last_cost "
        "from purchasing.supplier_price sp join purchasing.supplier s on s.id = sp.supplier_id "
        "where s.company_id = :c and sp.product_id = :p and s.status = 'active' group by s.id, s.name "
        "order by count(*) desc, max(sp.effective_date) desc, s.name limit :n"),
        {"c": str(company_id), "p": str(product_id), "n": limit}).all()
    return [{"id": r.id, "name": r.name, "last_cost": Decimal(r.last_cost), "last_day": r.last_day} for r in rows]


def open_request_number(session: Session, company_id: UUID, branch_id: UUID | None, product_id: UUID) -> str | None:
    """The number of a request for this product at this branch that is still open, if any."""
    row = session.execute(text(
        "select r.number from purchasing.purchase_request r join purchasing.purchase_request_line l "
        "on l.request_id = r.id where r.company_id = :c and r.branch_id is not distinct from cast(:b as uuid) "
        "and l.product_id = :p and r.status = any(:open) order by r.created_at limit 1"),
        {"c": str(company_id), "b": str(branch_id) if branch_id else None, "p": str(product_id),
         "open": list(OPEN_REQUEST)}).first()
    return str(row.number) if row else None


def quantity_to_order(reorder_level: Decimal | None, on_hand: Decimal, sold_recently: Decimal) -> Decimal:
    """Enough to get back to the reorder level, or what was sold in the last month if that is more."""
    gap = (reorder_level - on_hand) if reorder_level and reorder_level > 0 else Decimal(0)
    return max(gap, sold_recently, Decimal(0)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


class DraftPurchaseRequest(ActionProvider):
    """A draft purchase request for a product that has run out or is running low."""

    type = "purchasing.draft_purchase_request"
    title = "Draft a purchase request"
    description = ("Makes a draft request to buy the product for the branch, for the usual supplier, in the quantity "
                   "needed to get back to the reorder level or a month's sales, whichever is more. A person sends it.")
    check_codes = ("inventory.out_of_stock", "inventory.low_stock")
    needs_permission = "po.create"
    auto_allowed = False
    params_schema = {"properties": {
        "product_id": {"type": "uuid", "title": "Product", "editable": False},
        "quantity": {"type": "number", "title": "Quantity", "minimum": "0.0001", "maximum": "10000000"},
        "needed_by": {"type": "date", "title": "Needed by"},
        "note": {"type": "string", "title": "Note for the buyer", "max_length": 200}},
        "required": ["product_id", "quantity"]}

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        product_id = _product_id(finding)
        if product_id is None or finding.branch_id is None:
            return []
        product = find_product(session, product_id)
        if product is None or not product.is_active or product.company_id != finding.company_id:
            return []
        if open_request_number(session, finding.company_id, finding.branch_id, product_id):
            return []                                                   # somebody is already on it
        today = company_today(session, finding.company_id)
        on_hand, sold = (Decimal(finding.value or 0), Decimal(0))
        if unit_enabled(session, "inventory"):
            on_hand, sold = branch_stock_position(session, finding.company_id, finding.branch_id, product_id,
                                                  sold_since=today - timedelta(days=SALES_DAYS))
        quantity = quantity_to_order(product.reorder_level, on_hand, sold)
        if quantity <= 0:
            return []
        sku, name = product_labels(session, {product_id}).get(product_id, (product.sku, product.name))
        suppliers = usual_suppliers(session, finding.company_id, product_id)
        currency = _currency(session, finding.company_id)
        who = "; ".join(f"{s['name']} (last cost {money(s['last_cost'], currency)})" for s in suppliers)
        note = f"Usual supplier: {', '.join(s['name'] for s in suppliers)}" if suppliers else ""
        facts = {"On hand": _plain(on_hand), "Reorder level": _plain(product.reorder_level or Decimal(0)),
                 f"Sold in the last {SALES_DAYS} days": _plain(sold), "Quantity to order": _plain(quantity),
                 "Usual supplier": who or "None on record"}
        return [Proposal(params={"product_id": str(product_id), "quantity": str(quantity), "note": note},
                         description=(f"Draft a purchase request for {_plain(quantity)} x {name} ({sku}) for this "
                                      "branch" + (f", from {suppliers[0]['name']}" if suppliers else "") + "."),
                         facts=facts)]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        product_id = UUID(str(params["product_id"]))
        product = find_product(session, product_id)
        if product is None or not product.is_active or product.company_id != context.company_id:
            return ActionResult(False, "The product is no longer available")
        if context.branch_id is None:
            return ActionResult(False, "This suggestion has no branch to buy for")
        existing = open_request_number(session, context.company_id, context.branch_id, product_id)
        if existing:
            return ActionResult(False, f"Request {existing} for this product is already open")
        if unit_enabled(session, "inventory"):
            on_hand, _ = branch_stock_position(session, context.company_id, context.branch_id, product_id,
                                               sold_since=context.today)
            limit = product.reorder_level if product.reorder_level and product.reorder_level > 0 else Decimal(0)
            if on_hand > limit:
                return ActionResult(False, f"The branch now has {_plain(on_hand)} in stock: nothing needs ordering")
        needed_by = date.fromisoformat(str(params["needed_by"])) if params.get("needed_by") else None
        view = orders.create_request(session, company_id=context.company_id, branch_id=context.branch_id,
                                     lines=[(product_id, Decimal(str(params["quantity"])), params.get("note") or None)],
                                     needed_by=needed_by)
        number = view.request.number
        return ActionResult(True, f"Draft request {number} made for {_plain(view.lines[0].quantity)} x {product.name}",
                            (("purchasing.purchase_request", view.request.id, f"Request {number}"),))


# --------------------------------------------------------------------------- new selling price
class ProposePriceUpdate(ActionProvider):
    """A new selling price that keeps the margin a product had before its cost went up."""

    type = "purchasing.propose_price_update"
    title = "Update the selling price"
    description = ("Sets a new tax-inclusive selling price on the default price list, from tomorrow, that gives the "
                   "new cost the margin the product had before. Always needs a person: a price is money.")
    check_codes = ("purchasing.margin_squeeze", "purchasing.supplier_price_rise")
    needs_permission = "prices.manage"
    auto_allowed = False
    params_schema = {"properties": {
        "product_id": {"type": "uuid", "title": "Product", "editable": False},
        "price": {"type": "number", "title": "New price (with tax)", "minimum": "0.01", "maximum": "100000000"},
        "valid_from": {"type": "date", "title": "From"}},
        "required": ["product_id", "price", "valid_from"]}

    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        product_id = _product_id(finding)
        supplier_id = finding.record_id(SUPPLIER)
        if supplier_id is None and finding.entity_type == SUPPLIER:
            supplier_id = finding.entity_id
        if product_id is None or supplier_id is None:
            return []
        product = find_product(session, product_id)
        if product is None or not product.is_active or product.company_id != finding.company_id:
            return []
        today = company_today(session, finding.company_id)
        costs = [Decimal(r.unit_cost) for r in session.execute(text(
            "select unit_cost from purchasing.supplier_price where supplier_id = :s and product_id = :p "
            "and effective_date >= :since and effective_date <= :today order by effective_date, created_at"),
            {"s": str(supplier_id), "p": str(product_id), "since": today - timedelta(days=90), "today": today})]
        rise = watch.price_rise(costs, 1)
        price = selling_prices(session, finding.company_id, None, {product_id}, today).get(product_id)
        if rise is None or price is None:
            return []
        latest, earlier, _ = rise
        new_price = repricing.price_keeping_margin(price, product.vat_rate, earlier, latest)
        if new_price is None:
            return []
        margin = repricing.margin_percent(price, product.vat_rate, earlier)
        assert margin is not None
        currency = _currency(session, finding.company_id)
        sku, name = product_labels(session, {product_id}).get(product_id, (product.sku, product.name))
        start = today + timedelta(days=1)
        facts = {"Selling price now (with tax)": money(price, currency),
                 "Cost before": money(earlier, currency), "Cost now": money(latest, currency),
                 "Margin before the rise": pct(margin), "Proposed price (with tax)": money(new_price, currency),
                 "Change": pct((new_price - price) / price * 100)}
        return [Proposal(
            params={"product_id": str(product_id), "price": str(new_price), "valid_from": start.isoformat()},
            description=(f"Raise the price of {name} ({sku}) from {money(price, currency)} to "
                         f"{money(new_price, currency)} from {start.isoformat()}, so that it keeps its "
                         f"{pct(margin)} margin now that the cost is {money(latest, currency)}."),
            facts=facts)]

    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        product_id = UUID(str(params["product_id"]))
        product = find_product(session, product_id)
        if product is None or not product.is_active or product.company_id != context.company_id:
            return ActionResult(False, "The product is no longer available")
        price = Decimal(str(params["price"]))
        start = date.fromisoformat(str(params["valid_from"]))
        if start < context.today:
            return ActionResult(False, f"The date {start.isoformat()} has passed: choose a later one")
        current = selling_prices(session, context.company_id, None, {product_id}, context.today).get(product_id)
        if current is not None and current >= price:
            return ActionResult(False, f"The price is already {_plain(current)}, no lower than {_plain(price)}")
        item_id = set_selling_price(session, context.company_id, product_id, price, start)
        return ActionResult(True, f"The price of {product.name} will be {price} from {start.isoformat()}",
                            ((PRODUCT, product_id, f"{product.name}: {price} from {start.isoformat()}"),)
                            if item_id else ())
