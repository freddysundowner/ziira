"""POS's personal data for data subject requests: what a customer bought, paid and was invoiced.

POS holds no names or numbers of its own: every sale, invoice, receipt and quotation points at a CRM customer by id.
So POS finds a person only through the customer another unit found (`linked`), shows their purchase history in an
export, and on erasure removes the free-text notes staff typed on their documents. Amounts, numbers and dates of posted
documents are the business's accounting records and stay; with the customer's name gone from CRM they name nobody.
"""

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import (
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Session,
    json_rows,
    provides,
)


def _key(customer_id: UUID) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pos:customer:{customer_id}")


@provides("kernel.personal_data")
class PosPersonalData(PersonalDataProvider):
    name = "pos"

    def find(self, session: Session, company_id: UUID, subject: Any) -> list[PersonalRecord]:
        return []                                  # POS has no names or contact details; see `linked`

    def linked(self, session: Session, company_id: UUID, found: list[PersonalRecord]) -> list[PersonalRecord]:
        records = []
        for parent in found:
            if parent.source != "crm" or parent.kind != "customer":
                continue
            i = str(parent.record_id)
            counts = session.execute(text(
                "select (select count(*) from pos.sale where customer_id = :i) as sales, "
                "(select count(*) from pos.sales_invoice where customer_id = :i) as invoices, "
                "(select count(*) from pos.sales_invoice where customer_id = :i and status in ('issued', 'part_paid')) "
                "as unpaid, (select count(*) from pos.customer_receipt where customer_id = :i) as receipts, "
                "(select count(*) from pos.sales_document where customer_id = :i) as documents"), {"i": i}).one()
            if not (counts.sales or counts.invoices or counts.receipts or counts.documents):
                continue
            label = (f"{counts.sales} sale(s), {counts.invoices} invoice(s) ({counts.unpaid} unpaid), "
                     f"{counts.receipts} receipt(s), {counts.documents} quotation/order(s)")
            records.append(PersonalRecord("pos", "customer_documents", _key(parent.record_id), label, parent.match,
                                          company_id, ref=i))
        return records

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = record.ref
        return {
            "sales": json_rows(session, "select jsonb_build_object('number', number, 'date', business_date, "
                                        "'total', total, 'paid', paid_total, 'status', status) from pos.sale "
                                        "where customer_id = :i order by sold_at", i=i),
            "invoices": json_rows(session, "select jsonb_build_object('number', number, 'issued', issue_date, "
                                           "'due', due_date, 'total', total, 'paid', amount_paid, 'credited', "
                                           "credited, 'status', status, 'notes', notes) from pos.sales_invoice "
                                           "where customer_id = :i order by issue_date", i=i),
            "receipts": json_rows(session, "select jsonb_build_object('number', number, 'received_on', received_on, "
                                           "'amount', amount, 'method', method, 'reference', reference, 'status', "
                                           "status) from pos.customer_receipt where customer_id = :i "
                                           "order by received_on", i=i),
            "quotations_and_orders": json_rows(
                session, "select jsonb_build_object('number', number, 'kind', doc_kind, 'date', doc_date, "
                         "'total', total, 'status', status, 'notes', notes) from pos.sales_document "
                         "where customer_id = :i order by doc_date", i=i),
            "refunds": json_rows(session, "select jsonb_build_object('number', number, 'amount', amount, 'date', "
                                          "refunded_on, 'method', method, 'reason', reason) from pos.customer_refund "
                                          "where customer_id = :i order by refunded_on", i=i),
        }

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = record.ref
        invoices = int(session.execute(text(
            "update pos.sales_invoice set notes = null, updated_at = now() where customer_id = :i "
            "and notes is not null and status <> 'cancelled'"), {"i": i}).rowcount)  # type: ignore[attr-defined]
        documents = int(session.execute(text(
            "update pos.sales_document set notes = null, updated_at = now() where customer_id = :i "
            "and notes is not null"), {"i": i}).rowcount)  # type: ignore[attr-defined]
        return Outcome(
            "anonymised",
            changed=[f"{invoices} invoice note(s) removed", f"{documents} quotation/order note(s) removed"],
            kept=[Kept("sales, invoices, receipts, returns and refunds: numbers, dates, amounts and payment methods",
                       "accounting records of what was sold and paid; they point at the customer's code, which no "
                       "longer names anyone once the customer is anonymised"),
                  Kept("notes on cancelled invoices and the reference on receipts",
                       "cancelled documents cannot be edited, and a receipt's reference is the payment's own "
                       "reference, needed to reconcile it")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("pos", "sales_documents", "Sales, invoices, receipts, returns and quotations (the "
                                                       "customer is a code; notes are free text)",
                              "The business's sales and tax records; posted documents are never edited",
                              setting="retention_audit_years", period="the business's stated record-keeping period",
                              at_end="keep")]
