"""Sockets the POS module plugs into (declared under [extends] in manifest.toml)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import IntegrityCheck, Session, provides


@provides("kernel.integrity_check")
class CustomerLedgerCheck(IntegrityCheck):
    """What customers owe on their invoices must equal what each customer's account in the books says, and an invoice's
    paid amount must equal the live receipts allocated to it."""

    name = "customer ledger"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        problems = self._paid_amounts(session)
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = 'finance' and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).first()
        if enabled is None:
            return problems
        from ziira.modules.finance.public import party_balances

        companies = [r.company_id for r in session.execute(text("select distinct company_id from pos.sales_invoice"))]
        for company_id in companies:
            owed: dict[UUID | None, Decimal] = {
                r.customer_id: Decimal(r.owed) for r in session.execute(text(
                    "select customer_id, sum(total - amount_paid - credited) as owed from pos.sales_invoice "
                    "where company_id = :c and status in ('issued', 'part_paid') group by customer_id"),
                    {"c": str(company_id)}) if Decimal(r.owed) != 0}
            ledger = party_balances(session, company_id, "1100")
            for customer in sorted({*owed, *ledger}, key=str):
                if owed.get(customer, Decimal(0)) != ledger.get(customer, Decimal(0)):
                    problems.append(f"Customer {customer}: invoices say {owed.get(customer, 0)} is owed but the books "
                                    f"say {ledger.get(customer, 0)}")
        return problems

    @staticmethod
    def _paid_amounts(session: Session) -> list[str]:
        rows = session.execute(text(
            "select i.number, i.amount_paid, coalesce(sum(a.amount) filter (where r.status = 'posted'), 0) as live "
            "from pos.sales_invoice i left join pos.customer_receipt_allocation a on a.invoice_id = i.id "
            "left join pos.customer_receipt r on r.id = a.receipt_id group by i.id, i.number, i.amount_paid "
            "having i.amount_paid <> coalesce(sum(a.amount) filter (where r.status = 'posted'), 0)"))
        return [f"Invoice {r.number}: marked {r.amount_paid} paid but its receipts add up to {r.live}" for r in rows]
