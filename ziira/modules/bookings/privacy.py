"""Bookings' personal data for data subject requests: who was booked, their contact details and notes.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). An appointment is kept (the business's record
of what it did and billed); the identifying fields are replaced. Appointments still to come keep the name and contact
details they need, so the person is not stood up; ask again after they are done or cancelled.
"""

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
    json_rows,
    like_pattern,
    provides,
    sql_phone_matches,
)

LIVE = "('requested', 'confirmed', 'checked_in', 'in_service')"


@provides("kernel.personal_data")
class BookingsPersonalData(PersonalDataProvider):
    name = "bookings"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[tuple[str, UUID], PersonalRecord] = {}
        tables = (("appointment", "client_name", "client_phone", "client_email", "number", "starts_at"),
                  ("waitlist_entry", "client_name", "client_phone", "client_email", "client_name", "wanted_from"),
                  ("appointment_attendee", "name", "phone", "email", "name", "created_at"),
                  ("session_waitlist", "name", "phone", "email", "name", "created_at"))
        digits = subject.phone or (subject.identifier if subject.identifier and subject.identifier.isdigit() else None)
        for table, name_col, phone_col, email_col, label_col, when_col in tables:
            scope = "company_id = :c" if table not in ("appointment_attendee",) else (
                "appointment_id in (select id from bookings.appointment where company_id = :c)")
            queries: list[tuple[str, dict[str, Any], str]] = []
            if subject.email:
                queries.append((f"lower({email_col}) = :e", {"e": subject.email}, "exact"))
            if digits:
                queries.append((sql_phone_matches(phone_col, "p"), {"p": digits}, "exact"))
            if subject.name:
                queries.append((f"{name_col} ilike :n", {"n": like_pattern(subject.name)}, "possible"))
            for condition, extra, match in queries:
                for row in session.execute(text(
                        f"select id, {label_col} as label, {name_col} as who, {when_col} as moment "
                        f"from bookings.{table} where {scope} and {condition}"), {"c": str(company_id), **extra}):
                    if (row.who or "").startswith(PLACEHOLDER):
                        continue
                    key = (table, row.id)
                    previous = found.get(key)
                    if previous is None or (previous.match == "possible" and match == "exact"):
                        found[key] = PersonalRecord("bookings", table, row.id, f"{row.who or 'Client'} ({row.label}, "
                                                    f"{str(row.moment)[:10]})", match, company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        strip = "- 'tenant_id' - 'created_by' - 'updated_by'"
        table = {"appointment": "appointment", "waitlist_entry": "waitlist_entry",
                 "appointment_attendee": "appointment_attendee", "session_waitlist": "session_waitlist"}[record.kind]
        return {record.kind: json_rows(
            session, f"select to_jsonb(t) {strip} from bookings.{table} t where id = :i", i=i)}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        if record.kind == "appointment":
            row = session.execute(text(f"select number, status in {LIVE} and ends_at > now() as live "
                                       "from bookings.appointment where id = :i for update"), {"i": i}).first()
            if row is None:
                return Outcome("refused", message="The appointment no longer exists")
            if row.live:
                return Outcome("partial", kept=[Kept("name and contact details",
                                                     "the appointment has not happened yet and the client must be "
                                                     "reachable")],
                               message="Cancel or finish the appointment, then raise a new request")
            session.execute(text(
                "update bookings.appointment set client_name = :n, client_phone = null, client_email = null, "
                "note = null, cancel_note = null, updated_at = now() where id = :i"),
                {"n": f"{PLACEHOLDER} client", "i": i})
            return Outcome("anonymised", changed=["name replaced", "phone, email and notes removed"],
                           kept=[Kept("the appointment, its service, time, price and invoice link",
                                      "the business's record of what it did and billed")])
        if record.kind == "waitlist_entry":
            session.execute(text("delete from bookings.waitlist_entry where id = :i"), {"i": i})
            return Outcome("anonymised", changed=["waitlist entry deleted"])
        if record.kind == "session_waitlist":
            session.execute(text("delete from bookings.session_waitlist where id = :i"), {"i": i})
            return Outcome("anonymised", changed=["class waitlist entry deleted"])
        session.execute(text(
            "update bookings.appointment_attendee set name = :n, phone = null, email = null, customer_id = null, "
            "updated_at = now() where id = :i"), {"n": f"{PLACEHOLDER} client", "i": i})
        return Outcome("anonymised", changed=["name replaced", "phone and email removed"])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("bookings", "appointments", "Client name, phone, email and notes on appointments, "
                              "class lists, waitlists, bills and fees",
                              "Running the business's appointments and reminding clients",
                              period="while the appointment history is useful; erased on request once it is over",
                              at_end="review")]
