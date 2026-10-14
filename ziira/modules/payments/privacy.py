"""Payments' personal data for data subject requests: who paid by mobile money, and the payments made to or by a party.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). The payer's phone number is never stored in
the clear (only masked, plus a one-way fingerprint used to match a payment to a prompt), so a payer is found by
fingerprint: the number the person gives is turned into the same fingerprint. The payer's name as the provider reported
it is stored and is removed on erasure. Amounts, dates and provider receipt numbers are the business's records and stay.
"""

import hashlib
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
    Subject,
    json_rows,
    like_pattern,
    provides,
)

ERASED = "erased"
PARTY_SOURCES = {("crm", "customer"): "customer", ("purchasing", "supplier"): "supplier",
                 ("people", "employee"): "employee"}


def _fingerprint(digits: str) -> str:
    """The same one-way fingerprint payments stores for a number written as international digits."""
    return hashlib.sha256(digits.encode()).hexdigest()


def _key(kind: str, ref: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"payments:{kind}:{ref}")


@provides("kernel.personal_data")
class PaymentsPersonalData(PersonalDataProvider):
    name = "payments"

    # ------------------------------------------------------------------ find
    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: list[PersonalRecord] = []
        digits = [d for d in (subject.phone, subject.identifier if subject.identifier and subject.identifier.isdigit()
                              else None) if d]
        for fingerprint in dict.fromkeys(_fingerprint(d) for d in digits):
            count = self._count(session, company_id, "phone_hash = :h", {"h": fingerprint})
            if count:
                found.append(PersonalRecord("payments", "mobile_money_payer", _key("hash", fingerprint),
                                            f"{count} mobile money transaction(s) from this number", "exact",
                                            company_id, ref=f"hash:{fingerprint}"))
        if subject.name:
            names = session.execute(text(
                "select distinct t.counterparty_name from payments.external_transaction t "
                "join payments.payment_account a on a.id = t.payment_account_id "
                "where a.company_id = :c and t.counterparty_name ilike :n and t.counterparty_name <> :e"),
                {"c": str(company_id), "n": like_pattern(subject.name), "e": ERASED}).scalars().all()
            for name in names:
                count = self._count(session, company_id, "counterparty_name = :n", {"n": name})
                found.append(PersonalRecord("payments", "mobile_money_payer", _key("name", name),
                                            f"{count} transaction(s) paid in by '{name}'", "possible", company_id,
                                            ref=f"name:{name}"))
        return found

    def linked(self, session: Session, company_id: UUID, found: list[PersonalRecord]) -> list[PersonalRecord]:
        records = []
        for parent in found:
            party = PARTY_SOURCES.get((parent.source, parent.kind))
            if party is None:
                continue
            count = session.execute(text(
                "select count(*) from payments.payment where company_id = :c and party_type = :t and party_id = :i"),
                {"c": str(company_id), "t": party, "i": str(parent.record_id)}).scalar_one()
            if count:
                direction = "from" if party == "customer" else "to"
                records.append(PersonalRecord(
                    "payments", "party_payments", _key("party", str(parent.record_id)),
                    f"{count} payment(s) {direction} this {party}", parent.match, company_id,
                    ref=f"party:{party}:{parent.record_id}"))
        return records

    @staticmethod
    def _count(session: Session, company_id: UUID, condition: str, params: dict[str, Any]) -> int:
        return int(session.execute(text(
            "select count(*) from payments.external_transaction t "
            f"join payments.payment_account a on a.id = t.payment_account_id where a.company_id = :c and {condition}"),
            {"c": str(company_id), **params}).scalar_one())

    # ------------------------------------------------------------------ export
    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        kind, _, value = record.ref.partition(":")
        c = str(record.company_id)
        if kind == "party":
            party, _, party_id = value.partition(":")
            return {"payments": json_rows(
                session, "select jsonb_build_object('number', number, 'direction', direction, 'method', method, "
                         "'amount', amount, 'date', business_date, 'reference', external_ref, 'status', status) "
                         "from payments.payment where company_id = :c and party_type = :t and party_id = :i "
                         "order by business_date", c=c, t=party, i=party_id)}
        column = "phone_hash" if kind == "hash" else "counterparty_name"
        return {
            "transactions": json_rows(
                session, "select jsonb_build_object('reference', t.external_ref, 'time', t.txn_time, "
                         "'direction', t.direction, 'amount', t.amount, 'fee', t.fee, 'account_reference', t.bill_ref, "
                         "'name', t.counterparty_name, 'phone', t.counterparty_phone_masked, "
                         "'match_status', t.match_status) from payments.external_transaction t "
                         f"join payments.payment_account a on a.id = t.payment_account_id where a.company_id = :c "
                         f"and t.{column} = :v order by t.txn_time", c=c, v=value),
            "payment_prompts": json_rows(
                session, "select jsonb_build_object('kind', i.kind, 'amount', i.amount, 'phone', i.phone_masked, "
                         "'status', i.status, 'requested_at', i.created_at) from payments.payment_intent i "
                         "join payments.payment_account a on a.id = i.payment_account_id "
                         "where a.company_id = :c and i.phone_hash = :v order by i.created_at", c=c, v=value)
            if kind == "hash" else [],
        }

    # ------------------------------------------------------------------ anonymise
    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        kind, _, value = record.ref.partition(":")
        c = str(record.company_id)
        if kind == "party":
            party, _, party_id = value.partition(":")
            ids = session.execute(text(
                "select id from payments.payment where company_id = :c and party_type = :t and party_id = :i"),
                {"c": c, "t": party, "i": party_id}).scalars().all()
            txns = self._scrub_transactions(
                session, "t.id in (select m.external_transaction_id from payments.match m "
                         "where m.payment_id = any(:ids))", {"ids": ids}, c)
            payments = int(session.execute(text(
                "update payments.payment set phone_hash = null where id = any(:ids) and phone_hash is not null"),
                {"ids": ids}).rowcount)  # type: ignore[attr-defined]
        else:
            column = "phone_hash" if kind == "hash" else "counterparty_name"
            txns = self._scrub_transactions(session, f"t.{column} = :v", {"v": value}, c)
            payments = 0
            if kind == "hash":
                payments = int(session.execute(text(
                    "update payments.payment set phone_hash = null where company_id = :c and phone_hash = :v"),
                    {"c": c, "v": value}).rowcount)  # type: ignore[attr-defined]
                session.execute(text(
                    "update payments.payment_intent set phone_hash = null, phone_masked = :e where phone_hash = :v "
                    "and payment_account_id in (select id from payments.payment_account where company_id = :c)"),
                    {"e": ERASED, "v": value, "c": c})
        return Outcome(
            "anonymised",
            changed=[f"{txns} transaction(s): payer name and phone fingerprint removed, phone mask replaced",
                     f"{payments} payment(s): phone fingerprint removed"],
            kept=[Kept("provider receipt numbers, amounts, fees, times and the account reference the payer typed",
                       "the business's payment and bank-reconciliation records"),
                  Kept("the payments themselves (numbers, amounts, dates, methods) and the ledger entries made from "
                       "them", "accounting records; with the name and number gone they identify nobody")])

    @staticmethod
    def _scrub_transactions(session: Session, condition: str, params: dict[str, Any], company_id: str) -> int:
        result = session.execute(text(
            "update payments.external_transaction t set counterparty_name = null, "
            f"counterparty_phone_masked = case when t.counterparty_phone_masked is null then null else '{ERASED}' end, "
            "phone_hash = null, updated_at = now() from payments.payment_account a "
            f"where a.id = t.payment_account_id and a.company_id = :c and {condition}"), {"c": company_id, **params})
        return int(result.rowcount)  # type: ignore[attr-defined]

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("payments", "payers", "Payer name, masked phone number and a one-way phone fingerprint "
                                                    "on mobile money transactions and payments",
                              "Matching payments to what they pay for, and the business's payment records",
                              period="kept with the transaction; erased on request", at_end="review")]
