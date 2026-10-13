"""Shared setup for the finance tests: a business with stock and the books on."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system

FIN = "/api/v1/finance"


def make_books_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """The stock shop (HQ and JUJA branches, products CEM/PAINT/DELIVERY, users) with Finance enabled before any stock
    exists, so every movement posts to the books."""
    shop = make_stock_shop(client, registry, name)
    registry.enable(shop["tenant_id"], "finance")
    return shop


def opening(client, shop, quantity: str = "100", cost: str = "10"):  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": shop["cement"], "quantity": quantity, "unit_cost": cost}]})
    assert r.status_code == 201, r.text
    return r.json()


def sale_payload(shop, *, net: str = "100", tax: str = "16", payments=None, location=None, lines=None,  # type: ignore[no-untyped-def]
                 business_date: str | None = None, customer: UUID | None = None) -> dict:  # type: ignore[type-arg]
    """What POS publishes with `sale.posted`: the sale's money, plus the stock lines Inventory takes out."""
    total = str(Decimal(net) + Decimal(tax))
    return {"company_id": shop["company_id"], "branch_id": shop["branch_id"], "location_id": location or shop["main"],
            "business_date": business_date, "net": net, "tax": tax, "number": "POS-1",
            "payments": payments if payments is not None else [{"method": "cash", "amount": total}],
            "lines": lines if lines is not None else [{"line_id": uuid4(), "product_id": shop["delivery"],
                                                       "quantity": "1"}],          # a service: no stock moves
            "customer_id": customer}


def publish_sale(shop, *, sale_id: UUID | None = None, **kwargs) -> UUID:  # type: ignore[no-untyped-def]
    """Publish `sale.posted` in one transaction, as POS will."""
    from ziira.sdk import Event, publish

    sale_id = sale_id or uuid4()
    with system(shop) as s:
        publish(s, Event("sale.posted", "pos.sale", sale_id, sale_payload(shop, **kwargs)))
    return sale_id


def entries(shop, **where):  # type: ignore[no-untyped-def]
    """Journal entries with their lines, newest last: [(number, source_type, [(code, debit, credit, branch)])]."""
    condition = "where " + " and ".join(f"e.{k} = :{k}" for k in where) if where else ""
    sql = ("select e.id, e.number, e.source_type, e.entry_date, e.description from finance.journal_entry e "
           + condition + " order by e.posted_at, e.number")
    out = []
    with system(shop) as s:
        for e in s.execute(text(sql), {k: str(v) for k, v in where.items()}).all():
            lines = s.execute(text(
                "select a.code, l.debit, l.credit, l.branch_id from finance.journal_line l join finance.account a "
                "on a.id = l.account_id where l.entry_id = :i order by l.created_at, l.id"), {"i": str(e.id)}).all()
            out.append((e.number, e.source_type, [(c, d, cr, b) for c, d, cr, b in lines], e.entry_date, e.description))
    return out


def balance(shop, code: str) -> Decimal:  # type: ignore[no-untyped-def]
    """Debits minus credits posted to the account with this code."""
    with system(shop) as s:
        return s.execute(text(
            "select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l join finance.account a "
            "on a.id = l.account_id where a.code = :c"), {"c": code}).scalar_one()
