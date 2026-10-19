"""Memberships' personal data for data subject requests: the free-text notes written about members and package
buyers. A membership names its customer only by an id (the name, phone and email live in Customers, which has its own
provider), so what is found here are the notes that mention the person. Anonymising clears those notes and keeps every
membership, package, credit entry and invoice record, because the business's financial records point at them."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import (
    PLACEHOLDER,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Session,
    Subject,
    json_one,
    json_rows,
    like_pattern,
    provides,
    sql_phone_matches,
)

STRIP = "- 'tenant_id' - 'created_by' - 'updated_by'"
KEEP = Kept("the membership or package, its credits ledger and invoices",
            "the business's records of what was sold and paid for; they name the customer only by an id")


@provides("kernel.personal_data")
class MembershipsPersonalData(PersonalDataProvider):
    name = "memberships"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: list[PersonalRecord] = []
        if subject.phone:
            for r in session.execute(text(
                    "select id, number from memberships.profile where company_id = :c and "
                    + sql_phone_matches("emergency_phone", "p")), {"c": str(company_id), "p": subject.phone}):
                found.append(PersonalRecord("memberships", "profile", r.id, f"Member {r.number} (emergency contact)",
                                            "possible", company_id))
            for r in session.execute(text(
                    "select id, guest_name from memberships.guest_visit where company_id = :c and "
                    + sql_phone_matches("guest_phone", "p")), {"c": str(company_id), "p": subject.phone}):
                found.append(PersonalRecord("memberships", "guest", r.id, f"Guest {r.guest_name}", "exact", company_id))
        if not subject.name:
            return found
        pattern = like_pattern(subject.name)
        for r in session.execute(text(
                "select id, number from memberships.profile where company_id = :c and (emergency_name ilike :n "
                "or notes ilike :n)"), {"c": str(company_id), "n": pattern}):
            found.append(PersonalRecord("memberships", "profile", r.id, f"Member {r.number}", "possible", company_id))
        for r in session.execute(text(
                "select id, guest_name from memberships.guest_visit where company_id = :c and guest_name ilike :n"),
                {"c": str(company_id), "n": pattern}):
            found.append(PersonalRecord("memberships", "guest", r.id, f"Guest {r.guest_name}", "possible", company_id))
        for kind, table, label in (("member", "member", "number"), ("package", "sold_package", "number")):
            extra = " or cancel_note ilike :n" if kind == "member" else ""
            for r in session.execute(text(
                    f"select id, {label} as label from memberships.{table} where company_id = :c "
                    f"and (notes ilike :n{extra})"), {"c": str(company_id), "n": pattern}):
                found.append(PersonalRecord("memberships", kind, r.id, str(r.label), "possible", company_id))
        return found

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        if record.kind == "profile":
            customer = session.execute(text("select customer_id from memberships.profile where id = :i"),
                                       {"i": i}).scalar_one_or_none()
            return {
                "profile": json_one(session, f"select to_jsonb(p) {STRIP} from memberships.profile p where id = :i",
                                    i=i),
                "waiver_acceptances": json_rows(session, f"select to_jsonb(a) {STRIP} from "
                                                         "memberships.waiver_acceptance a where customer_id = :c "
                                                         "order by accepted_at", c=str(customer)),
                "measurements": json_rows(session, f"select to_jsonb(m) {STRIP} from memberships.measurement m "
                                                   "where customer_id = :c order by taken_on", c=str(customer)),
                "visits": json_rows(session, f"select to_jsonb(k) {STRIP} from memberships.checkin k "
                                             "where customer_id = :c order by occurred_at desc limit 5000",
                                    c=str(customer))}
        if record.kind == "guest":
            return {"guest_visit": json_one(session, f"select to_jsonb(g) {STRIP} from memberships.guest_visit g "
                                                     "where id = :i", i=i)}
        if record.kind == "member":
            return {"membership": json_one(session, f"select to_jsonb(m) {STRIP} from memberships.member m "
                                                    "where id = :i", i=i),
                    "history": json_rows(session, f"select to_jsonb(h) {STRIP} - 'member_id' "
                                                  "from memberships.member_history h where member_id = :i "
                                                  "order by seq", i=i)}
        return {"package": json_one(session, f"select to_jsonb(p) {STRIP} from memberships.sold_package p "
                                             "where id = :i", i=i)}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        if record.kind == "profile":
            row = session.execute(text("select customer_id from memberships.profile where id = :i for update"),
                                  {"i": i}).first()
            if row is None:
                return Outcome("refused", message="The member no longer exists")
            session.execute(text(
                "update memberships.profile set emergency_name = null, emergency_phone = null, emergency_relation = null, "  # noqa: E501
                "date_of_birth = null, notes = null, source = null, tags = '[]', card_number = null, "
                "photo_file_id = null, block_reason = null, updated_at = now() where id = :i"), {"i": i})
            session.execute(text("delete from memberships.measurement where customer_id = :c"),
                            {"c": str(row.customer_id)})
            session.execute(text("update memberships.guest_visit set guest_name = :m, guest_phone = null, note = null "
                                 "where host_customer_id = :c"), {"m": PLACEHOLDER, "c": str(row.customer_id)})
            return Outcome("anonymised", changed=["emergency contact, birth date, card, notes and photo link removed",
                                                  "measurements removed"],
                           kept=[KEEP, Kept("waiver acceptances and check-ins",
                                            "the record that the terms were accepted and when the person came in; "
                                            "they cannot be changed and name no one but the customer id")])
        if record.kind == "guest":
            session.execute(text("update memberships.guest_visit set guest_name = :m, guest_phone = null, note = null "
                                 "where id = :i"), {"m": PLACEHOLDER, "i": i})
            return Outcome("anonymised", changed=["guest name and phone removed"])
        if record.kind == "member":
            held = session.execute(text("select 1 from memberships.member where id = :i for update"), {"i": i})
            if held.first() is None:
                return Outcome("refused", message="The membership no longer exists")
            session.execute(text("update memberships.member set notes = null, cancel_note = null, updated_at = now() "
                                 "where id = :i"), {"i": i})
            session.execute(text("update memberships.member_history set note = null where member_id = :i "
                                 "and note is not null"), {"i": i})
            return Outcome("anonymised", changed=["notes and cancellation note removed", "history notes removed"],
                           kept=[KEEP])
        held = session.execute(text("select 1 from memberships.sold_package where id = :i for update"), {"i": i})
        if held.first() is None:
            return Outcome("refused", message="The package no longer exists")
        session.execute(text("update memberships.sold_package set notes = null, updated_at = now() where id = :i"),
                        {"i": i})
        return Outcome("anonymised", changed=["notes removed"], kept=[KEEP])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("memberships", "members", "Notes about members and package buyers",
                              "Looking after members and their packages",
                              period="while the membership or package exists; erased on request", at_end="review"),
                RetentionRule("memberships", "profile", "Emergency contact, birth date, card number and photo link",
                              "Safety at the gym, check-in and birthday messages",
                              period="while the person is a member; erased on request", at_end="review"),
                RetentionRule("memberships", "checkin", "When members came in",
                              "Entry control, attendance reports and fraud checks",
                              period="kept with the business's records; the person is named only by an id",
                              at_end="review"),
                RetentionRule("memberships", "guest_visit", "Guests a member brought in",
                              "Guest passes and following up an enquiry",
                              period="erased on request", at_end="review")]

