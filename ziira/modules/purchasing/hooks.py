"""Sockets the Purchasing module plugs into (declared under [extends] in manifest.toml)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_ACTION, INTEL_CHECK
from ziira.modules.purchasing.action_providers import DraftPurchaseRequest, ProposePriceUpdate
from ziira.modules.purchasing.importers import SupplierBalanceImporter, SupplierImporter
from ziira.modules.purchasing.intel_checks import (
    BillMismatchWaiting,
    DuplicateSupplierBill,
    DuplicateSupplierPayment,
    MarginSqueeze,
    OrderAboveUsualPrice,
    OverdueSupplierBills,
    PaidWithoutReceipt,
    SupplierBankChanged,
    SupplierPriceRise,
)
from ziira.modules.purchasing.pulse import PurchasingPulse
from ziira.sdk import IntegrityCheck, Session, provides

for _check in (SupplierPriceRise, OrderAboveUsualPrice, MarginSqueeze, DuplicateSupplierBill, DuplicateSupplierPayment,
               SupplierBankChanged, PaidWithoutReceipt, OverdueSupplierBills, BillMismatchWaiting):
    provides(INTEL_CHECK)(_check)
provides(INTEL_ACTION)(DraftPurchaseRequest)
provides(INTEL_ACTION)(ProposePriceUpdate)


@provides("kernel.integrity_check")
class SupplierLedgerCheck(IntegrityCheck):
    """What is owed to each supplier on their bills (opening bills included) must equal what the supplier's account
    in the books says, and every opening bill still standing has its entry in the books."""

    name = "supplier ledger"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = 'finance' and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).first()
        if enabled is None:
            return []
        from ziira.modules.finance.public import party_balances, posted_for_sources

        problems: list[str] = []
        for company_id in [r.company_id for r in session.execute(text(
                "select distinct company_id from purchasing.supplier_bill"))]:
            owed: dict[UUID | None, Decimal] = {
                r.supplier_id: Decimal(r.owed) for r in session.execute(text(
                    "select supplier_id, sum(total - amount_paid - credited + refunded) as owed "
                    "from purchasing.supplier_bill where company_id = :c and status in ('posted', 'part_paid', 'paid') "
                    "group by supplier_id"), {"c": str(company_id)}) if Decimal(r.owed) != 0}
            ledger = {k: -v for k, v in party_balances(session, company_id, "2000").items()}      # credit balances
            for supplier in sorted({*owed, *ledger}, key=str):
                if owed.get(supplier, Decimal(0)) != ledger.get(supplier, Decimal(0)):
                    problems.append(f"Supplier {supplier}: bills say {owed.get(supplier, 0)} is owed but the books "
                                    f"say {ledger.get(supplier, 0)}")
            openings = {r.id: r.number for r in session.execute(text(
                "select id, number from purchasing.supplier_bill where company_id = :c and kind = 'opening_balance' "
                "and status <> 'reversed'"), {"c": str(company_id)})}
            missing = set(openings) - posted_for_sources(session, company_id, "opening_payable", set(openings))
            problems += [f"Opening bill {openings[i]} has not been posted to the books"
                         for i in sorted(missing, key=str)]
        return problems


provides(COMMAND_PULSE_SOURCE)(PurchasingPulse)
provides(IMPORTS_IMPORTER)(SupplierImporter)
provides(IMPORTS_IMPORTER)(SupplierBalanceImporter)

from ziira.modules.purchasing import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider

from ziira.modules.purchasing import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools
