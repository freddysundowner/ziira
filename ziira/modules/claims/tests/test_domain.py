"""Claims domain rules: sharing the excess, what a payer's answer is worth, who is invoiced what, ageing, payer terms and the
printable estimate. Numbers are worked out by hand in the comments."""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.claims.domain import ageing, document, rates
from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import allocate, cents, line_total
from ziira.modules.claims.domain.split import BillableLine, compute_split

facts = rules.LineFacts


def test_a_line_is_quantity_times_price_to_the_cent() -> None:
    assert line_total(D("2.5"), D("150.00")) == D("375.00")
    assert line_total(D("3"), D("33.335")) == D("100.01")           # 100.005 rounds up
    assert cents(D("0.005")) == D("0.01")


def test_the_excess_is_shared_in_proportion_and_adds_up_exactly() -> None:
    # 500 over 600 / 12000 / 350 / 4500 / 300 / 2000 (total 19750): floors leave 3 cents for the largest remainders
    shares = allocate(D("500.00"), [D(600), D(12000), D(350), D(4500), D(300), D(2000)])
    assert shares == [D("15.19"), D("303.80"), D("8.86"), D("113.92"), D("7.60"), D("50.63")]
    assert sum(shares) == D("500.00")
    assert allocate(D(0), [D(5), D(5)]) == [D(0), D(0)]
    assert allocate(D("0.01"), [D(1), D(1), D(1)]) == [D("0.01"), D(0), D(0)] or sum(
        allocate(D("0.01"), [D(1), D(1), D(1)])) == D("0.01")
    with pytest.raises(ValueError):
        allocate(D(1), [])


@given(st.integers(min_value=0, max_value=10_000_000), st.lists(st.integers(min_value=1, max_value=5_000_000),
                                                                min_size=1, max_size=12))
def test_sharing_never_loses_a_cent_and_never_exceeds_a_line(total_cents: int, weight_cents: list[int]) -> None:
    weights = [D(w) / 100 for w in weight_cents]
    total = min(D(total_cents) / 100, sum(weights, D(0)))
    shares = allocate(total, weights)
    assert sum(shares) == total
    assert all(s >= 0 for s in shares)
    assert all(s <= w for s, w in zip(shares, weights, strict=True))


def test_what_an_answer_is_worth() -> None:
    asked = D("1000.00")
    assert rules.payer_pays(facts(asked, "approved")) == asked
    assert rules.payer_pays(facts(asked, "pending")) == 0
    # a counter-offer is worth nothing to the payer until we accept it
    counter = facts(asked, "countered", D("700.00"))
    assert rules.payer_pays(counter) == 0 and rules.is_open(counter)
    accepted = facts(asked, "countered", D("700.00"), our_decision="accepted", shortfall_to="business")
    assert rules.payer_pays(accepted) == D("700.00") and rules.business_absorbs(accepted) == D("300.00")
    assert rules.customer_owes(accepted) == 0 and not rules.is_open(accepted)
    carried = facts(asked, "countered", D("700.00"), our_decision="accepted", shortfall_to="customer")
    assert rules.customer_owes(carried) == D("300.00") and rules.business_absorbs(carried) == 0
    declined = facts(asked, "countered", D("700.00"), our_decision="declined")
    assert rules.payer_pays(declined) == 0 and not rules.is_open(declined) and not rules.is_authorised_work(declined)
    rejected = facts(asked, "rejected")
    assert rules.is_open(rejected) and not rules.is_authorised_work(rejected)
    assert rules.customer_owes(facts(asked, "rejected", customer_decision="pays")) == asked
    assert rules.customer_owes(facts(asked, "rejected", customer_decision="declined")) == 0


def test_answers_are_checked() -> None:
    asked = D("100.00")
    assert rules.check_answer("approved", asked, None, None) == asked
    assert rules.check_answer("countered", asked, D("60.00"), None) == D("60.00")
    assert rules.check_answer("rejected", asked, None, "Not covered") is None
    for state, amount, reason in (("approved", D("90.00"), None), ("countered", None, None), ("countered", D("100.00"), None),
                                  ("countered", D("-1"), None), ("rejected", None, "  "), ("maybe", None, None)):
        with pytest.raises(ValueError):
            rules.check_answer(state, asked, amount, reason)


def test_the_whole_answer_follows_the_lines() -> None:
    assert rules.overall_response(["approved", "approved"]) == "accepted"
    assert rules.overall_response(["approved", "rejected"]) == "partly_accepted"
    assert rules.overall_response(["approved", "countered", "rejected"]) == "countered"
    assert rules.overall_response(["rejected", "rejected"]) == "rejected"
    assert rules.overall_response(["needs_information"]) == "needs_information"
    assert rules.overall_response(["approved", "needs_information"]) == "needs_information"
    assert rules.overall_response(["approved", "pending"]) is None and rules.overall_response([]) is None


def bill(asked: str, state: str, amount: str | None = None, **kw) -> BillableLine:  # type: ignore[no-untyped-def]
    f = facts(D(asked), state, D(amount) if amount else None, **kw)
    return BillableLine(uuid4(), "line", D(1), D(asked), f)


def test_the_split_of_a_whole_claim_by_hand() -> None:
    # approved 600 + 12000 + 350 + 4500 + 300 and an accepted counter 2000 (asked 2200, business absorbs 200) = 19750
    lines = [bill("600", "approved"), bill("12000", "approved"), bill("350", "approved"), bill("4500", "approved"),
             bill("300", "approved"), bill("2200", "countered", "2000", our_decision="accepted", shortfall_to="business"),
             bill("8000", "rejected", customer_decision="pays")]
    split = compute_split(lines, excess=D("500.00"))
    assert split.payer_gross == D("19750.00") and split.payer_net == D("19250.00")
    assert split.excess_applied == D("500.00")
    assert split.customer_total == D("8500.00")               # excess 500 + the rejected paint the customer pays
    assert split.absorbed == D("200.00")
    assert [p.kind for p in split.customer_parts] == ["excess", "rejected_line"]
    assert all(p.net >= 0 for p in split.payer_parts)


def test_the_customer_carries_the_difference_of_a_counter_when_they_agreed() -> None:
    split = compute_split([bill("4500", "countered", "3000", our_decision="accepted", shortfall_to="customer")],
                          excess=D(0))
    assert split.payer_net == D("3000.00") and split.customer_total == D("1500.00")
    assert split.customer_parts[0].kind == "shortfall" and split.absorbed == 0


def test_an_excess_bigger_than_the_claim_is_capped_at_what_the_payer_pays() -> None:
    split = compute_split([bill("300", "approved")], excess=D("1000.00"))
    assert split.excess_applied == D("300.00") and split.payer_net == D(0) and split.customer_total == D("300.00")


def test_a_later_run_takes_only_the_excess_that_is_left() -> None:
    first = compute_split([bill("200", "approved")], excess=D("500.00"))
    assert first.excess_applied == D("200.00")
    later = compute_split([bill("1000", "approved")], excess=D("500.00"), embedded_before=D("200.00"),
                          charged_before=D("200.00"), gross_before=D("200.00"))
    assert later.excess_applied == D("300.00") and later.payer_net == D("700.00")
    third = compute_split([bill("1000", "approved")], excess=D("500.00"), embedded_before=D("500.00"),
                          charged_before=D("500.00"), gross_before=D("1200.00"))
    assert third.excess_applied == 0 and third.payer_net == D("1000.00") and third.customer_total == 0


def test_after_a_reduction_the_credited_discount_is_taken_again_but_the_customer_is_not_charged_twice() -> None:
    # excess 500 was charged to the customer; the 303.80 that sat on a credited line is back to be taken from the payer
    again = compute_split([bill("10000", "countered", "10000.00", our_decision="accepted")], excess=D("500.00"),
                          embedded_before=D("196.20"), charged_before=D("500.00"), gross_before=D("7750.00"))
    assert again.payer_parts[0].discount == D("303.80") and again.payer_net == D("9696.20")
    assert again.excess_applied == 0 and again.customer_total == 0


@given(st.lists(st.integers(min_value=1, max_value=900_000), min_size=1, max_size=10),
       st.integers(min_value=0, max_value=3_000_000))
def test_every_cent_of_a_split_is_somewhere(gross_cents: list[int], excess_cents: int) -> None:
    lines = [bill(str(D(g) / 100), "approved") for g in gross_cents]
    excess = D(excess_cents) / 100
    split = compute_split(lines, excess=excess)
    assert split.payer_net + split.excess_applied == split.payer_gross
    assert split.excess_applied == min(excess, split.payer_gross)
    assert all(p.discount <= p.gross for p in split.payer_parts)
    assert split.customer_total == split.excess_applied


def test_ageing_buckets_follow_the_days_past_due() -> None:
    today = date(2026, 10, 18)
    assert ageing.bucket(date(2026, 10, 18), today) == "not_due"
    assert ageing.bucket(date(2026, 11, 1), today) == "not_due"
    assert ageing.bucket(date(2026, 10, 17), today) == "d1_30"
    assert ageing.bucket(date(2026, 9, 18), today) == "d1_30"           # exactly 30 days late
    assert ageing.bucket(date(2026, 9, 17), today) == "d31_60"
    assert ageing.bucket(date(2026, 8, 19), today) == "d31_60"          # 60 days
    assert ageing.bucket(date(2026, 8, 18), today) == "d61_90"          # 61 days
    assert ageing.bucket(date(2026, 7, 20), today) == "d61_90"          # 90 days
    assert ageing.bucket(date(2026, 7, 19), today) == "d90_plus"


def test_payer_terms_suggest_prices() -> None:
    assert rates.labour_rate({"body": "150", "default": "100"}, "Body") == D("150")
    assert rates.labour_rate({"body": "150", "default": "100"}, "electrical") == D("100")
    assert rates.labour_rate({"body": "150"}, "electrical") is None
    assert rates.parts_price(D("1000.00"), D("10"), D(0)) == D("900.00")
    assert rates.parts_price(D("1000.00"), D(0), D("20")) == D("1200.00")
    assert rates.parts_price(D("1000.00"), D("10"), D("20")) == D("1080.00")      # 1000 x 1.20 x 0.90


def test_the_printable_estimate_escapes_what_people_typed() -> None:
    doc = document.DocEstimate(
        business="Mama <b>Garage</b>", currency="KES", label="Estimate version 1", claim_number="CLM-1", payer="Jubilee",
        policy_number="P1", insurer_claim_number="C1", subject="Corolla", loss_date="", notes="<script>x</script>",
        valid_until="2026-11-01", total=D("100.00"), link="",
        lines=[document.DocLine(1, "labour", "Fit <i>bumper</i>", D(1), D("100.00"), D("100.00"))])
    html = document.render_html(doc)
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Garage" in html
    assert "Fit &lt;i&gt;bumper" in html and "KES 100.00" in html
    text = document.render_text(doc)
    assert "Total (tax included where it applies): KES 100.00" in text
