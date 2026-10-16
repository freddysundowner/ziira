"""Sockets the Kenya pack plugs into (declared under [extends] in manifest.toml). Figures and names are in `data/`."""

from datetime import date
from decimal import Decimal

from ziira.modules.finance.public import AccountSeed, ChartTemplate
from ziira.modules.people.public import StatutoryTables, StatutoryTableSeed
from ziira.modules.products.public import TaxCodeRow, TaxCodeSeed
from ziira.sdk import provides, read_pack_data


@provides("products.tax_code_seed")
class KenyaTaxCodes(TaxCodeSeed):
    countries = ("KE",)

    def tax_codes(self) -> list[TaxCodeRow]:
        return [TaxCodeRow(t["code"], t["name"], Decimal(str(t["vat_rate"])), t.get("authority_code"))
                for t in read_pack_data(__file__, "tax_codes.toml")["tax_code"]]


@provides("finance.chart_template")
class KenyaChart(ChartTemplate):
    countries = ("KE",)

    def accounts(self) -> list[AccountSeed]:
        return [AccountSeed(a["code"], a["name"], a["type"], a.get("subtype"), bool(a.get("is_control", False)))
                for a in read_pack_data(__file__, "chart.toml")["account"]]


@provides("people.statutory_table_seed")
class KenyaPayrollTables(StatutoryTables):
    countries = ("KE",)

    def tables(self) -> list[StatutoryTableSeed]:
        return [StatutoryTableSeed(t["code"], date.fromisoformat(str(t["effective_from"])), t["definition"],
                                   t["source_reference"])
                for t in read_pack_data(__file__, "payroll.toml")["table"]]
