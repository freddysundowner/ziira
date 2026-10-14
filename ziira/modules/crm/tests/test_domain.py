"""CRM rules: phone numbers, validation, lead moves, credit changes."""

from decimal import Decimal as D  # noqa: N817

import pytest

from ziira.modules.crm.domain import rules
from ziira.sdk import ValidationFailed, normalise_phone


def test_phone_numbers_are_read_with_the_calling_code_of_the_company() -> None:
    for given in ("0712345678", "+254712345678", "254712345678", "712345678", "0712 345 678", "(0712)-345-678"):
        assert normalise_phone(given, "254") == "254712345678", given
    assert normalise_phone("07911 123456", "44") == "447911123456"                 # another country, same function
    assert normalise_phone("+1 415 555 2671", "254") == "14155552671"              # written in full: left as it is
    assert normalise_phone(None, "254") is None and normalise_phone("  ", "254") is None
    for bad in ("12345", "abc", "0", "+0123456789", "1234567890123456"):
        with pytest.raises(ValidationFailed):
            normalise_phone(bad, "254")
    with pytest.raises(ValidationFailed):
        normalise_phone("0712345678", "")                                            # no code set: write it in full


def test_other_fields_are_cleaned() -> None:
    assert rules.clean_name("  Mary   Wanjiku ") == "Mary Wanjiku"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValidationFailed):
            rules.clean_name(bad)
    assert rules.clean_email(" Mary@Shop.CO.KE ") == "mary@shop.co.ke" and rules.clean_email("") is None
    for bad in ("nope", "a@b", "a b@c.d"):
        with pytest.raises(ValidationFailed):
            rules.clean_email(bad)
    assert rules.clean_tax_id("p051234567a") == "P051234567A" and rules.clean_tax_id("GB 123 456 789") == "GB 123 456 789"
    assert rules.clean_tax_id("12-345/6") == "12-345/6" and rules.clean_tax_id(" ") is None   # any country's format
    for bad in ("12", "!!!", "x" * 31):
        with pytest.raises(ValidationFailed):
            rules.clean_tax_id(bad)
    assert rules.normalise_code(" cus-01 ") == "CUS-01"
    with pytest.raises(ValidationFailed):
        rules.normalise_code("a b")
    assert rules.clean_group("  Wholesale   dealers ") == "Wholesale dealers" and rules.clean_group(" ") is None
    with pytest.raises(ValidationFailed):
        rules.clean_group("x" * 61)


def test_credit_figures_and_who_approves() -> None:
    rules.check_credit(D("50000.00"), 30)
    for limit, days in ((D("-1"), 0), (D("1.005"), 0), (D("2000000000"), 0), (D("10"), -1), (D("10"), 366)):
        with pytest.raises(ValidationFailed):
            rules.check_credit(limit, days)
    assert rules.credit_change_needs_approval(D("1000"), D("1000.01"))
    assert not rules.credit_change_needs_approval(D("1000"), D("1000"))
    assert not rules.credit_change_needs_approval(D("1000"), D("500"))


def test_leads_move_forward_and_can_be_reopened() -> None:
    rules.check_lead_move("new", "contacted")
    rules.check_lead_move("contacted", "qualified")
    rules.check_lead_move("qualified", "lost")
    rules.check_lead_move("lost", "contacted")
    for current, new in (("converted", "contacted"), ("qualified", "new"), ("lost", "qualified"), ("new", "converted"),
                         ("new", "nonsense"), ("qualified", "contacted")):
        with pytest.raises(ValidationFailed):
            rules.check_lead_move(current, new)
