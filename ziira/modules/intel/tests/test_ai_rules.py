"""Rules of the AI layer that need no database: personal data kept out, every figure traced to the facts, the ranking
a permutation, keys never shown, tool arguments checked, branch scopes."""

import json
import string
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.intel.domain.ai_rules import (
    CONSENT_VERSION,
    FigureChecker,
    Pseudonyms,
    consent_text,
    hide_secrets,
    numbers_in,
    parse_ranking,
    prompt_hash,
    scrub_personal,
    scrub_value,
)
from ziira.modules.intel.domain.rules import reorder_by_preference
from ziira.modules.intel.domain.scope import BranchScope, scope_from_pairs
from ziira.modules.intel.domain.tool_params import BadParams, check_params

D = Decimal


# --------------------------------------------------------------------------- personal data
def test_phones_emails_long_numbers_and_ids_are_replaced_but_money_and_dates_are_not() -> None:
    text = ("Call +254 712 345 678 or 0712 345 678, write to mary@example.com on 2026-10-15. Owes KES 1,250,000.50 "
            "(12500000.50). Tax id A123456789B, account 1234567890123. Period 2026-10-01 2026-10-31.")
    clean = scrub_personal(text)
    for private in ("712 345 678", "mary@example.com", "A123456789B", "1234567890123"):
        assert private not in clean
    for kept in ("2026-10-15", "KES 1,250,000.50", "12500000.50", "2026-10-01 2026-10-31"):
        assert kept in clean


def test_amount_strings_inside_results_survive_but_other_strings_are_scrubbed() -> None:
    cleaned = scrub_value({"total": "123456789.50", "count": 7, "note": "ring 0712345678901", "rows": [{"sku": "A1"}]})
    assert cleaned["total"] == "123456789.50" and cleaned["count"] == 7
    assert "0712345678901" not in cleaned["note"] and cleaned["rows"] == [{"sku": "A1"}]


@given(st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=12, max_size=40), st.text(max_size=60))
def test_a_key_never_survives_hide_secrets(secret: str, around: str) -> None:
    shown = hide_secrets(f"{around}{secret}{around} x-api-key: {secret}", [secret])
    assert secret not in shown


def test_things_shaped_like_keys_are_hidden_even_when_unknown() -> None:
    shown = hide_secrets("failed with Bearer abcdefghijklmnop and sk-ant-api03-abcdefghijkl123")
    assert "abcdefghijklmnop" not in shown and "sk-ant" not in shown


@given(st.lists(st.text(alphabet=string.ascii_letters + " ", min_size=3, max_size=20).filter(lambda s: len(s.strip()) >= 3),
                min_size=1, max_size=5, unique_by=lambda s: s.strip().casefold()))
def test_names_go_out_as_labels_and_come_back(names: list[str]) -> None:
    p = Pseudonyms()
    sentence = " and ".join(f"[{n.strip()}] owes 5" for n in names)
    for n in names:
        p.add(n, "Customer")
    hidden = p.hide(sentence)
    assert not any(n.strip().casefold() in hidden.casefold() for n in names if n.strip().casefold() not in "customer")
    assert p.restore(hidden).casefold() == sentence.casefold()


def test_aliases_hold_no_digits_so_they_never_count_as_figures() -> None:
    p = Pseudonyms()
    first = p.add("Mary Wanjiku", "Customer")
    for i in range(30):
        p.add(f"Person Number{'x' * i}", "Customer")
    assert first == "Customer A" and not any(ch.isdigit() for ch in p.hide("Mary Wanjiku, Person Numberx"))


def test_hide_fields_replaces_named_fields_and_the_names_elsewhere() -> None:
    p = Pseudonyms()
    out = p.hide_fields({"rows": [{"customer": "Mary Wanjiku", "owes": "10"}], "note": "Mary Wanjiku is late"},
                        {"customer": "Customer"})
    assert out == {"rows": [{"customer": "Customer A", "owes": "10"}], "note": "Customer A is late"}


# --------------------------------------------------------------------------- figures
def test_numbers_are_read_with_thousands_separators_decimals_and_dates() -> None:
    assert numbers_in("KES 1,250.50 on 2026-10-15, 3 units, 12%") == [
        D("1250.50"), D("2026"), D("10"), D("15"), D("3"), D("12")]


def test_a_strict_check_accepts_only_numbers_that_are_in_the_facts() -> None:
    check = FigureChecker([D("3"), D("10"), D("350.00")], strict=True)
    assert check.unverified("Only 3 left against a reorder level of 10; 350 is at stake.") == []
    assert check.unverified("Only 4 left, and 350.00 is at stake.") == ["4"]
    assert check.unverified("1. First look at stock\n2. Then 3 units") == []   # list markers are not figures


def test_a_looser_check_accepts_roundings_totals_differences_and_shares() -> None:
    check = FigureChecker([D("1234567.50"), D("10"), D("4"), D("250")], [[D("10"), D("4"), D("250")]])
    assert check.unverified("About 1.2 million, or 1,234,568 to the shilling.") == []
    assert check.unverified("Together 264, a gap of 6, and 4 is 40% of 10.") == []
    assert check.unverified("The three rows add up to 264 on average 88.") == []
    assert check.unverified("That is 99 shillings.") == ["99"]
    assert check.unverified("Up 55%.") == ["55%"]


@given(st.lists(st.decimals(min_value=D("0.01"), max_value=D("100000000"), places=2), min_size=1, max_size=12))
def test_a_number_copied_from_the_facts_is_always_verified(values: list[Decimal]) -> None:
    check = FigureChecker(values, strict=True)
    assert check.unverified(" ; ".join(f"{v:,.2f}" for v in values)) == []


def test_an_invented_number_is_found_even_among_many_checks() -> None:
    check = FigureChecker([D("5")])
    assert check.unverified(" ".join(str(7000 + i) for i in range(40)))[:3] == ["7000", "7001", "7002"]


# --------------------------------------------------------------------------- ranking
ALIASES = ["F1", "F2", "F3"]


def ranking(order: list[str], reasons: bool = True) -> str:
    return "Here you go: " + json.dumps({"order": [{"id": a, **({"reason": f"why {a}"} if reasons else {})}
                                                  for a in order]})


@given(st.permutations(ALIASES))
def test_any_permutation_of_the_findings_given_is_accepted(order: list[str]) -> None:
    parsed = parse_ranking(ranking(list(order)), ALIASES)
    assert parsed is not None and [a for a, _ in parsed] == list(order)


@pytest.mark.parametrize("order", [["F1", "F2"], ["F1", "F2", "F2"], ["F1", "F2", "F9"], ["F1", "F2", "F3", "F3"], []])
def test_anything_but_a_permutation_is_refused(order: list[str]) -> None:
    assert parse_ranking(ranking(order), ALIASES) is None


@pytest.mark.parametrize("reply", ["no json here", '{"order": "F1"}', '{"other": []}', "{broken", '{"order": [1, 2, 3]}'])
def test_a_reply_that_is_not_the_asked_shape_is_refused(reply: str) -> None:
    assert parse_ranking(reply, ALIASES) is None


def test_reasons_are_kept_to_one_short_line() -> None:
    reply = json.dumps({"order": [{"id": a, "reason": "a\nlong\n" + "x" * 500} for a in ALIASES]})
    parsed = parse_ranking(reply, ALIASES)
    assert parsed is not None and all("\n" not in r and len(r) <= 200 for _, r in parsed)


@given(st.permutations(["a", "b", "c", "d", "e"]), st.permutations(["a", "b", "c", "d", "e"]),
       st.sets(st.sampled_from(["a", "b", "c", "d", "e"])))
def test_a_preferred_order_only_moves_findings_it_knows(current: list[str], preferred: list[str],
                                                        known: set[str]) -> None:
    order = [k for k in preferred if k in known]
    result = reorder_by_preference([(k, "co") for k in current], {"co": order})
    assert sorted(result) == sorted(current)
    for i, key in enumerate(current):
        if key not in known:
            assert result[i] == key                           # a finding the ranking never saw keeps its place
    assert [k for k in result if k in known] == order


def test_a_group_without_a_preference_is_left_alone() -> None:
    assert reorder_by_preference([("a", 1), ("b", 2), ("c", 1)], {1: ["c", "a"]}) == ["c", "b", "a"]
    assert reorder_by_preference([("a", 1), ("b", 2)], {}) == ["a", "b"]


# --------------------------------------------------------------------------- tool arguments and scope
SCHEMA = {"type": "object", "properties": {
    "date_from": {"type": "string", "format": "date"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    "by": {"type": "string", "enum": ["branch", "day"]}, "branch_id": {"type": "string", "format": "uuid"}},
    "required": ["date_from"]}


def test_good_arguments_pass_and_unknown_ones_are_dropped() -> None:
    assert check_params(SCHEMA, {"date_from": "2026-10-01", "limit": 5, "company_id": "x", "sql": "drop"}) == {
        "date_from": "2026-10-01", "limit": 5}


@pytest.mark.parametrize("arguments", [
    {}, {"date_from": "yesterday"}, {"date_from": "2026-10-01", "limit": 500}, {"date_from": "2026-10-01", "limit": True},
    {"date_from": "2026-10-01", "by": "year"}, {"date_from": "2026-10-01", "branch_id": "Thika"}, "text", None])
def test_bad_arguments_are_refused(arguments: object) -> None:
    with pytest.raises(BadParams):
        check_params(SCHEMA, arguments)


def test_a_scope_says_which_branches_a_person_may_read() -> None:
    company, other, hq, juja = uuid4(), uuid4(), uuid4(), uuid4()
    assert scope_from_pairs(None, company).everything
    assert scope_from_pairs([(company, None)], company).everything
    only_hq = scope_from_pairs([(company, hq), (other, juja)], company)
    assert only_hq.allows(hq) and not only_hq.allows(juja) and not only_hq.allows(None) and not only_hq.everything
    assert only_hq.sql("s.branch_id")[0] == "s.branch_id = any(:scope_branches)"
    assert scope_from_pairs([(other, None)], company).nothing
    assert BranchScope(True).sql() == ("true", {}) and BranchScope(False).sql() == ("false", {})


# --------------------------------------------------------------------------- consent and hashing
def test_the_consent_text_names_the_provider_and_what_is_and_is_not_sent_in_both_languages() -> None:
    for language in ("en", "sw"):
        text = consent_text(language, "Provider X, model m")
        assert "Provider X, model m" in text and "Customer A" in text and "{" not in text
    assert "Names of customers" in consent_text("en", "p") and "Majina ya wateja" in consent_text("sw", "p")
    assert CONSENT_VERSION


def test_a_prompt_hash_is_stable_and_changes_with_the_prompt() -> None:
    assert prompt_hash("a", ["b"]) == prompt_hash("a", ["b"]) != prompt_hash("a", ["c"])
    assert len(prompt_hash("a")) == 64
