"""Sockets the POS module plugs into (declared under [extends] in manifest.toml)."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_ACTION, INTEL_BASELINE_METRIC, INTEL_CHECK
from ziira.modules.pos import intel_checks
from ziira.modules.pos.action_providers import HoldCredit, SendPaymentReminder
from ziira.modules.pos.importers import CustomerBalanceImporter
from ziira.modules.pos.public import RECEIPT_EXTRAS, ReceiptExtra
from ziira.modules.pos.pulse import PosPulse
from ziira.sdk import IntegrityCheck, Session, define_extension_point, provides

define_extension_point(RECEIPT_EXTRAS, ReceiptExtra,
                       "Adds lines to the foot of printed receipts and invoices (e.g. a tax-authority control code).")


@provides("kernel.integrity_check")
class CustomerLedgerCheck(IntegrityCheck):
    """What customers owe on their invoices (less money held for them in advance) must equal what each customer's
    account in the books says, and an invoice's paid amount must equal the live receipts allocated to it."""

    name = "customer ledger"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        problems = self._paid_amounts(session)
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = 'finance' and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).first()
        if enabled is None:
            return problems
        from ziira.modules.finance.public import party_balances, posted_for_sources

        companies = [r.company_id for r in session.execute(text("select distinct company_id from pos.sales_invoice"))]
        for company_id in companies:
            owed: dict[UUID | None, Decimal] = {
                r.customer_id: Decimal(r.owed) for r in session.execute(text(
                    "select customer_id, sum(total - amount_paid - credited) as owed from pos.sales_invoice "
                    "where company_id = :c and status in ('issued', 'part_paid') group by customer_id"),
                    {"c": str(company_id)}) if Decimal(r.owed) != 0}
            for r in session.execute(text(
                    "select customer_id, sum(unallocated) as held from pos.customer_receipt where company_id = :c and "
                    "status = 'posted' and unallocated > 0 group by customer_id"), {"c": str(company_id)}):
                owed[r.customer_id] = owed.get(r.customer_id, Decimal(0)) - Decimal(r.held)    # in credit
            problems += self._opening_documents_posted(session, company_id, posted_for_sources)
            ledger = party_balances(session, company_id, "1100")
            for customer in sorted({*owed, *ledger}, key=str):
                if owed.get(customer, Decimal(0)) != ledger.get(customer, Decimal(0)):
                    problems.append(f"Customer {customer}: invoices say {owed.get(customer, 0)} is owed but the books "
                                    f"say {ledger.get(customer, 0)}")
        return problems

    @staticmethod
    def _opening_documents_posted(session: Session, company_id: UUID, posted_for_sources: Any) -> list[str]:
        """Every opening invoice or credit still standing has its entry in the books (opening balances count on both
        sides of the check above)."""
        ids = {r.id: r.number for r in session.execute(text(
            "select id, number from pos.sales_invoice where company_id = :c and kind = 'opening_balance' and "
            "status <> 'cancelled' union all select id, number from pos.customer_receipt where company_id = :c and "
            "method = 'opening' and status = 'posted'"), {"c": str(company_id)})}
        missing = set(ids) - posted_for_sources(session, company_id, "opening_receivable", set(ids))
        return [f"Opening balance {ids[i]} has not been posted to the books" for i in sorted(missing, key=str)]

    @staticmethod
    def _paid_amounts(session: Session) -> list[str]:
        rows = session.execute(text(
            "select i.number, i.amount_paid, coalesce(sum(a.amount) filter (where r.status = 'posted'), 0) as live "
            "from pos.sales_invoice i left join pos.customer_receipt_allocation a on a.invoice_id = i.id "
            "left join pos.customer_receipt r on r.id = a.receipt_id group by i.id, i.number, i.amount_paid "
            "having i.amount_paid <> coalesce(sum(a.amount) filter (where r.status = 'posted'), 0)"))
        return [f"Invoice {r.number}: marked {r.amount_paid} paid but its receipts add up to {r.live}" for r in rows]


# Intelligence checks, the baselines they compare with, and the Command Center figures (all read-only)
for _check in (intel_checks.TillCashVariance, intel_checks.CashierVoidRate, intel_checks.CashierRefundRate,
               intel_checks.CashierDiscountRate, intel_checks.LargeExceptions, intel_checks.OutOfHoursSales,
               intel_checks.LateRecordedSales, intel_checks.BranchSalesLow, intel_checks.OverdueCustomers,
               intel_checks.SlowerPayers, intel_checks.CreditToOverdueCustomer, intel_checks.OverCreditLimit):
    provides(INTEL_CHECK)(_check)
for _metric in (intel_checks.CashierVoidRateMetric, intel_checks.CashierRefundRateMetric,
                intel_checks.CashierDiscountRateMetric, intel_checks.BranchDailySalesMetric):
    provides(INTEL_BASELINE_METRIC)(_metric)
provides(INTEL_ACTION)(SendPaymentReminder)
provides(INTEL_ACTION)(HoldCredit)
provides(COMMAND_PULSE_SOURCE)(PosPulse)
provides(IMPORTS_IMPORTER)(CustomerBalanceImporter)

from ziira.modules.pos import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider

from ziira.modules.pos import organisation as _organisation  # noqa: E402, F401, I001

from ziira.modules.pos import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools

from ziira.modules.connect.public import CORE_COVERAGE  # noqa: E402, I001
from ziira.modules.pos.core_coverage import PosCoverage  # noqa: E402, I001

provides(CORE_COVERAGE)(PosCoverage)  # tells Connectors what Core covers
