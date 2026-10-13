"""Property tests of weighted average costing: whatever happens, the figures stay consistent."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.inventory.domain import costing
from ziira.modules.inventory.domain.costing import CostState, cost_movement
from ziira.modules.inventory.domain.movements import INTERNAL_TRANSFER

quantities = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("500"), places=2)
costs = st.decimals(min_value=Decimal("0"), max_value=Decimal("5000"), places=2)
OPS = ("receipt", "sale", "sale_return", "adjust_up", "adjust_down", "write_off", "purchase_return", "transfer")
operations = st.lists(st.tuples(st.sampled_from(OPS), quantities, costs), max_size=40)


def run(ops, *, allow_negative: bool):  # type: ignore[no-untyped-def]
    """Apply the operations, skipping outgoing ones the stock cannot cover (unless negative sales are allowed).

    Yields (state before, movement type, quantity, result) for every movement made, and the history for a rebuild.
    """
    state = CostState()
    history: list[tuple[str, Decimal, Decimal]] = []
    steps = []

    def apply(kind: str, quantity: Decimal, unit_cost: Decimal | None):  # type: ignore[no-untyped-def]
        nonlocal state
        result = cost_movement(state, kind, quantity, unit_cost)
        steps.append((state, kind, quantity, result))
        history.append((kind, quantity, result.value))
        state = result.state
        return result

    for op, quantity, cost in ops:
        outgoing = op in ("sale", "adjust_down", "write_off", "purchase_return", "transfer")
        if outgoing and quantity > state.quantity and not (allow_negative and op == "sale"):
            continue
        if op == "receipt":
            apply("receipt", quantity, cost)
        elif op == "sale_return":
            apply("sale_return", quantity, cost)
        elif op == "adjust_up":
            apply("adjustment", quantity, None)
        elif op == "transfer":
            out = apply("transfer_out", -quantity, None)
            apply("transfer_in", quantity, out.unit_cost)
        else:
            kind = {"adjust_down": "adjustment"}.get(op, op)
            apply(kind, -quantity, None)
    return state, history, steps


@given(operations)
@settings(max_examples=300, deadline=None)
def test_figures_always_equal_the_sums_of_the_movements(ops) -> None:  # type: ignore[no-untyped-def]
    state, history, steps = run(ops, allow_negative=False)
    pool = [(kind, quantity, result.value) for _, kind, quantity, result in steps if kind not in INTERNAL_TRANSFER]
    assert state.quantity == sum((q for _, q, _ in pool), Decimal(0))
    assert state.value == sum((v for _, _, v in pool), Decimal(0))
    assert state.quantity >= 0
    assert costing.rebuild(history) == state                       # replaying the history gives the same figure


@given(operations)
@settings(max_examples=300, deadline=None)
def test_an_empty_shelf_holds_no_value_and_value_never_goes_negative(ops) -> None:  # type: ignore[no-untyped-def]
    _, _, steps = run(ops, allow_negative=False)
    for _, _, _, result in steps:
        assert result.state.value >= 0
        if result.state.quantity == 0:
            assert result.state.value == 0


@given(operations)
@settings(max_examples=300, deadline=None)
def test_outgoing_stock_takes_the_average_and_transfers_change_nothing(ops) -> None:  # type: ignore[no-untyped-def]
    _, _, steps = run(ops, allow_negative=False)
    for before, kind, quantity, result in steps:
        if quantity < 0:
            assert result.unit_cost == before.average_cost
        if kind in INTERNAL_TRANSFER:
            assert result.state == before
        else:
            assert result.value == 0 or (result.value > 0) == (quantity > 0)     # value has the quantity's sign


@given(operations)
@settings(max_examples=300, deadline=None)
def test_a_transfer_nets_to_zero(ops) -> None:  # type: ignore[no-untyped-def]
    _, _, steps = run(ops, allow_negative=False)
    pairs = [(steps[i][3], steps[i + 1][3]) for i in range(len(steps) - 1)
             if steps[i][1] == "transfer_out" and steps[i + 1][1] == "transfer_in"]
    for out, into in pairs:
        assert out.value + into.value == 0 and out.unit_cost == into.unit_cost


@given(st.lists(st.tuples(st.sampled_from(("receipt", "sale", "adjust_up", "write_off")),
                          st.integers(1, 500).map(Decimal), costs), max_size=40))
@settings(max_examples=300, deadline=None)
def test_the_average_stays_between_the_costs_paid(ops) -> None:  # type: ignore[no-untyped-def]
    _, _, steps = run(ops, allow_negative=False)
    paid: list[Decimal] = []            # every cost stock came in at (found stock comes in at the average)
    for _, _, quantity, result in steps:
        if quantity > 0:
            paid.append(result.unit_cost)
        if paid and result.state.quantity > 0:
            assert min(paid) - Decimal("0.01") <= result.state.average_cost <= max(paid) + Decimal("0.01")


@given(operations)
@settings(max_examples=300, deadline=None)
def test_negative_sales_keep_the_ledger_consistent(ops) -> None:  # type: ignore[no-untyped-def]
    state, history, steps = run(ops, allow_negative=True)
    pool = [(q, r.value) for _, kind, q, r in steps if kind not in INTERNAL_TRANSFER]
    assert state.quantity == sum((q for q, _ in pool), Decimal(0))
    assert state.value == sum((v for _, v in pool), Decimal(0))
    assert costing.rebuild(history) == state
