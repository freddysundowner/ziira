"""The pure rules behind "Move to Ziira Core": codes for customers and suppliers, text for amounts, grouping reasons,
and which "no such record" messages a move may ignore. Worked out by hand."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.connect.domain import move as rules


def test_codes_count_up_from_one_and_pass_the_taken_ones() -> None:
    assert rules.code_for("customer", 1) == "C-0001" and rules.code_for("supplier", 12) == "S-0012"
    assert rules.next_codes("customer", [], lambda c: False, 3) == ["C-0001", "C-0002", "C-0003"]
    # C-0001 is already given, C-0003 is already in Ziira: the next two free ones are C-0002 and C-0004
    assert rules.next_codes("customer", ["C-0001"], lambda c: c == "C-0003", 2) == ["C-0002", "C-0004"]
    assert rules.next_codes("supplier", ["S-0001"], lambda c: False, 0) == []


@given(taken=st.sets(st.integers(1, 40).map(lambda n: rules.code_for("customer", n))),
       busy=st.sets(st.integers(1, 40).map(lambda n: rules.code_for("customer", n))), how_many=st.integers(0, 15))
def test_new_codes_are_distinct_and_never_collide(taken: set[str], busy: set[str], how_many: int) -> None:
    found = rules.next_codes("customer", taken, lambda c: c in busy, how_many)
    assert len(found) == how_many == len(set(found))
    assert not set(found) & (taken | busy)


def test_amounts_are_written_the_way_the_importers_read_them() -> None:
    assert rules.money_text(Decimal("2000")) == "2000.00"
    assert rules.money_text(Decimal("0.125")) == "0.13"                  # half up
    assert rules.number_text(Decimal("4.500000")) == "4.5"
    assert rules.number_text(Decimal("160.0000")) == "160"
    assert rules.number_text(Decimal("4.3333333")) == "4.333333"
    assert rules.outstanding(Decimal("2500.50"), Decimal("500.50")) == Decimal("2000.00")
    assert rules.sku_of("  bolt-10 ") == "BOLT-10" and rules.sku_of(None) == ""


def test_a_move_ignores_only_the_missing_records_it_is_about_to_create() -> None:
    planned = {"product": {"BOLT-10", "A.B"}, "customer": {"C-0001"}, "supplier": set()}
    messages = [
        "sku: no product with code BOLT-10. Import or add the product first.",
        "sku: no product with code A.B. Import or add the product first.",           # a dot inside the code
        "sku: no product with code NUT-8. Import or add the product first.",         # not part of this move
        "customer_code: no customer with code C-0001. Import the customers first",
        "customer_code: no customer with code C-0009. Import the customers first",
        "supplier_code: no supplier with code S-0001. Import the suppliers first",
        "quantity: must be more than zero",
    ]
    assert rules.forgive_lookup(messages, planned) == [messages[2], messages[4], messages[5], messages[6]]


def test_reasons_are_grouped_counted_and_shown_with_a_few_examples() -> None:
    entries = [("skipped", "No cost is known", "Bolt"), ("exists", "Already there", "Cement"),
               ("skipped", "No cost is known", "Nut"), ("skipped", "No cost is known", "Washer"),
               ("skipped", "No cost is known", "Screw"), ("skipped", "No name", "")]
    found = rules.tally(entries)
    assert [(r.status, r.reason, r.count) for r in found] == [
        ("skipped", "No cost is known", 4), ("exists", "Already there", 1), ("skipped", "No name", 1)]
    assert found[0].examples == ["Bolt", "Nut", "Washer"]               # at most three
    assert found[2].examples == []
