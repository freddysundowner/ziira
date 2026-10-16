"""Sockets the international pack plugs into (declared under [extends] in manifest.toml)."""

from decimal import Decimal

from ziira.modules.products.public import TaxCodeRow, TaxCodeSeed
from ziira.sdk import provides, read_pack_data


@provides("products.tax_code_seed")
class InternationalTaxCodes(TaxCodeSeed):
    """Codes that charge nothing; the business adds the rate its country charges."""

    countries = ()

    def tax_codes(self) -> list[TaxCodeRow]:
        return [TaxCodeRow(t["code"], t["name"], Decimal(str(t["vat_rate"])), t.get("authority_code"))
                for t in read_pack_data(__file__, "tax_codes.toml")["tax_code"]]
