"""Checks of the books (the nightly checks of specification section 07), run by `ziira verify`.

- every entry balances, and each company's total debits equal its total credits;
- the inventory accounts equal what the stock ledger is worth (sub-ledger equals control account);
- every stock movement has been posted. With `fix`, missing postings are made from the movements in order.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.services.event_postings import post_stock_movement
from ziira.sdk import Event, Session


def _inventory_enabled(session: Session) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'inventory' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def verify_books(session: Session, *, fix: bool = False) -> list[str]:
    """Describe everything wrong with the books. With `fix`, post the stock movements that are missing."""
    problems: list[str] = []
    for entry_id, debit, credit in finance_repo.unbalanced_entries(session):
        problems.append(f"Entry {entry_id} does not balance: debits {debit}, credits {credit}")
    for company_id, (debit, credit) in finance_repo.ledger_totals(session).items():
        if debit != credit:
            problems.append(f"Company {company_id}: total debits {debit} differ from total credits {credit}")
    if _inventory_enabled(session):
        problems.extend(_verify_stock(session, fix))
    return problems


def _verify_stock(session: Session, fix: bool) -> list[str]:
    from ziira.modules.inventory.public import MovementView, movements_after, stock_value

    problems: list[str] = []
    missing: list[MovementView] = []
    after = 0
    while True:
        batch = movements_after(session, after, 500)
        if not batch:
            break
        after = batch[-1].seq
        posted = finance_repo.posted_sources(session, "stock_movement", {m.id for m in batch})
        missing += [m for m in batch if m.id not in posted and m.value != 0]
    if missing:
        problems.append(f"{len(missing)} stock movement(s) worth {sum((m.value for m in missing), Decimal(0))} "
                        "have not been posted to the books")
        if fix:
            for m in missing:                                    # in posting order, so the books match the ledger
                post_stock_movement(session, Event("stock.moved", "inventory.stock_movement", m.id, {
                    "company_id": m.company_id, "branch_id": m.branch_id, "location_kind": m.location_kind,
                    "movement_type": m.movement_type, "value": m.value, "business_date": m.business_date}))
    companies: set[UUID] = {c for c, in session.execute(text("select distinct company_id from inventory.product_cost"))}
    for company_id in sorted(companies, key=str):
        stock = stock_value(session, company_id)
        books = finance_repo.balances_by_subtype(session, company_id, ["inventory", "inventory_in_transit"])
        if stock != books and not (fix and missing):
            problems.append(f"Company {company_id}: the stock ledger is worth {stock} but the inventory accounts "
                            f"show {books}")
    return problems
