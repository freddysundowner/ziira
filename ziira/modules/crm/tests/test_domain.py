"""CRM rules: phone numbers, validation, lead moves, credit changes."""

from decimal import Decimal as D  # noqa: N817

import pytest

from ziira.modules.crm.domain import rules
from ziira.sdk import ValidationFailed


def test_phone_numbers_are_normalised() -> None:
    for given in ("0712345678", "+254712345678", "254712345678", "712345678", "0712 345 678", "(0712)-345-678"):
        assert rules.normalise_phone(given) == "254712345678", given
    assert rules.normalise_phone("0112345678") == "254112345678"
    assert rules.normalise_phone(None) is None and rules.normalise_phone("  ") is None
    for bad in ("12345", "0212345678", "254812345678", "07123456789", "abc", "+1 202 555 0100"):
        with pytest.raises(ValidationFailed):
            rules.normalise_phone(bad)


def test_other_fields_are_cleaned() -> None:
    assert rules.clean_name("  Mary   Wanjiku ") == "Mary Wanjiku"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValidationFailed):
            rules.clean_name(bad)
    assert rules.clean_email(" Mary@Shop.CO.KE ") == "mary@shop.co.ke" and rules.clean_email("") is None
    for bad in ("nope", "a@b", "a b@c.d"):
        with pytest.raises(ValidationFailed):
            rules.clean_email(bad)
    assert rules.clean_kra_pin("p051234567a") == "P051234567A"
    with pytest.raises(ValidationFailed):
        rules.clean_kra_pin("12345")
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
