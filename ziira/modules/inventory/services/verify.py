"""Verify the stock ledger: balances and cost figures must equal what the movements add up to.

Stock balances and the company's cost figure per product are derived from the movements, which never change.
`verify_stock` compares them and, with `fix`, rebuilds them from the movements (the nightly check of
specification section 08; run it with `ziira stock-verify`).
"""

from decimal import Decimal

from ziira.modules.inventory.domain import costing
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.products.public import product_labels
from ziira.sdk import Session, current_context


def _quantity(value: Decimal) -> str:
    return f"{value.normalize():f}"


def verify_stock(session: Session, *, fix: bool = False) -> list[str]:
    """Describe every balance or cost figure that disagrees with the movements. With `fix`, rebuild them."""
    tenant_id = current_context().tenant_id
    problems: list[str] = []

    mismatches = inventory_repo.balance_mismatches(session)
    labels = product_labels(session, {m.product_id for m in mismatches})
    codes = {m.location_id: (loc.code if (loc := inventory_repo.get_location(session, m.location_id)) else "?")
             for m in mismatches}
    for m in mismatches:
        sku = labels.get(m.product_id, ("?", ""))[0]
        batch = f" batch {m.batch_id}" if m.batch_id else ""
        problems.append(f"Balance of {sku}{batch} at {codes[m.location_id]} is {_quantity(m.stored)} but its "
                        f"movements add up to {_quantity(m.moved)}")
        if fix:
            inventory_repo.set_balance(session, tenant_id, m)

    history = inventory_repo.movement_history(session)
    stored = inventory_repo.all_costs(session)
    cost_labels = product_labels(session, {product for _, product in set(history) | set(stored)})
    for key in sorted(set(history) | set(stored), key=str):
        expected = costing.rebuild(history.get(key, []))
        cost = stored.get(key)
        have = (cost.quantity, cost.value, cost.average_cost) if cost else (Decimal(0), Decimal(0), Decimal(0))
        want = (expected.quantity, expected.value, expected.average_cost)
        if have == want:
            continue
        sku = cost_labels.get(key[1], ("?", ""))[0]
        problems.append(f"Cost figure of {sku} is {_quantity(have[0])} units worth {have[1]} (average {have[2]}) "
                        f"but its movements give {_quantity(want[0])} units worth {want[1]} (average {want[2]})")
        if fix and cost is not None:
            cost.quantity, cost.value, cost.average_cost = want
            session.flush()
    return problems
