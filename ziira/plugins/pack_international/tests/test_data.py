"""The international pack supplies only codes that charge nothing."""

from decimal import Decimal

from ziira.modules.products.public import check_tax_codes
from ziira.plugins.pack_international.hooks import InternationalTaxCodes


def test_no_code_charges_a_tax() -> None:
    rows = InternationalTaxCodes().tax_codes()
    check_tax_codes(rows)
    assert {r.code for r in rows} == {"NONE", "ZERO", "EXEMPT"} and {r.vat_rate for r in rows} == {Decimal(0)}
    assert InternationalTaxCodes.countries == ()
