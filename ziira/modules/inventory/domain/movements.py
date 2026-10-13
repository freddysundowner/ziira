"""What a stock movement may look like. Pure Python: no database, no HTTP.

A movement is one signed quantity (+ in, - out, in the product's base unit) of one product at one
location. These rules decide whether a proposed movement is well formed; costing (what it is
worth) is in costing.py and batch choice in batches.py.
"""

from decimal import Decimal

from ziira.sdk import ValidationFailed

QUANTITY_PLACES = Decimal("0.0001")

# Movement types and the direction they allow. "any" = either, e.g. a count finds more or less.
DIRECTION: dict[str, str] = {
    "opening": "in",
    "receipt": "in",
    "sale_return": "in",
    "transfer_in": "in",
    "sale": "out",
    "purchase_return": "out",
    "transfer_out": "out",
    "write_off": "out",
    "adjustment": "any",
    "count_variance": "any",
}
MOVEMENT_TYPES = tuple(DIRECTION)

# These need a reason code (also enforced by a database constraint).
REASON_REQUIRED = frozenset({"adjustment", "count_variance", "write_off"})
# These bring stock in at a cost the caller knows (a supplier invoice, a transfer's dispatch cost).
COST_REQUIRED = frozenset({"opening", "receipt", "transfer_in"})
# Moves between locations of one company: the company's stock value does not change.
INTERNAL_TRANSFER = frozenset({"transfer_in", "transfer_out"})


def check_quantity(quantity: Decimal) -> Decimal:
    """A quantity has at most 4 decimal places (the database precision) and is not zero."""
    if not quantity.is_finite():
        raise ValidationFailed("Quantity must be a number")
    if quantity != quantity.quantize(QUANTITY_PLACES):
        raise ValidationFailed("Quantity can have at most 4 decimal places")
    if quantity == 0:
        raise ValidationFailed("Quantity cannot be zero")
    return quantity


def check_movement(movement_type: str, quantity: Decimal, *, reason_code_id: object | None = None,
                   unit_cost: Decimal | None = None) -> None:
    """Raise ValidationFailed unless the movement is allowed for its type."""
    if movement_type not in DIRECTION:
        raise ValidationFailed(f"Movement type must be one of: {', '.join(MOVEMENT_TYPES)}")
    check_quantity(quantity)
    direction = DIRECTION[movement_type]
    if direction == "in" and quantity < 0:
        raise ValidationFailed(f"A {movement_type.replace('_', ' ')} brings stock in, so the quantity must be positive")
    if direction == "out" and quantity > 0:
        raise ValidationFailed(f"A {movement_type.replace('_', ' ')} takes stock out, so the quantity must be negative")
    if movement_type in REASON_REQUIRED and reason_code_id is None:
        raise ValidationFailed(f"A reason is required for a {movement_type.replace('_', ' ')}")
    if unit_cost is not None and (not unit_cost.is_finite() or unit_cost < 0):
        raise ValidationFailed("Unit cost cannot be negative")
    if movement_type in COST_REQUIRED and unit_cost is None:
        raise ValidationFailed(f"A unit cost is required for a {movement_type.replace('_', ' ')}")


def check_product_can_hold_stock(product_type: str, is_active: bool) -> None:
    """Only active stock products have stock (services and non-stock items do not)."""
    if product_type != "stock":
        raise ValidationFailed("Only stock products can have stock movements")
    if not is_active:
        raise ValidationFailed("This product is inactive")


def check_negative_stock(on_hand: Decimal, change: Decimal, *, allowed: bool) -> bool:
    """Apply the company's negative stock policy to a change of `change` on `on_hand`.

    Returns True if the change leaves the balance below zero and the policy allows it, so the
    caller can raise an exception for review (specification section 08). Raises
    ValidationFailed if it is not allowed.
    """
    after = on_hand + change
    if after >= 0:
        return False
    if not allowed:
        raise ValidationFailed(f"Not enough stock: {on_hand.normalize():f} on hand, "
                               f"{(-change).normalize():f} needed")
    return True
