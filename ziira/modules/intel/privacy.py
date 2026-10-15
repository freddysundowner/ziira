"""Intelligence's personal data for data subject requests: what people asked Ask Ziira, and the answers.

An answer stores the rows the tools returned (names of customers, suppliers and employees, balances), so a request
about a person must be able to find it, export it and remove it. The AI call log and the usage and consent tables
hold only hashes, counts and user ids and are not searched. Plugged into the "kernel.personal_data" socket
(docs/privacy.md, docs/ai.md).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.jobs import CONVERSATION_DAYS
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
    like_pattern,
    provides,
    sql_digits,
)

REMOVED = "[removed]"


@provides("kernel.personal_data")
class IntelPersonalData(PersonalDataProvider):
    name = "intel"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        haystack = "lower(m.content || ' ' || m.sources::text)"
        conditions: list[tuple[str, dict[str, Any], str]] = []
        if subject.email:
            conditions.append((f"{haystack} like :e", {"e": like_pattern(subject.email.lower())}, "exact"))
        if subject.phone:
            conditions.append((f"{sql_digits('m.content || m.sources::text')} like :p", {"p": f"%{subject.phone}%"},
                               "exact"))
        if subject.identifier:
            conditions.append((f"upper({haystack}) like :i", {"i": like_pattern(subject.identifier)}, "exact"))
        if subject.name:
            conditions.append((f"{haystack} like :n", {"n": like_pattern(subject.name.lower())}, "possible"))
        found: dict[UUID, PersonalRecord] = {}
        for condition, params, match in conditions:
            rows = session.execute(text(
                "select m.id, m.created_at, m.role, u.full_name from intel.ask_message m "
                "join intel.ask_session s on s.id = m.session_id join kernel.app_user u on u.id = s.user_id "
                f"where s.company_id = :c and m.content <> :removed and {condition}"),
                {"c": str(company_id), "removed": REMOVED, **params})
            for row in rows:
                previous = found.get(row.id)
                if previous is None or (previous.match == "possible" and match == "exact"):
                    label = f"Ask Ziira {row.role} of {row.created_at:%Y-%m-%d} by {row.full_name}"
                    found[row.id] = PersonalRecord("intel", "ask_message", row.id, label, match, company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        data = json_one(session, (
            "select jsonb_build_object('asked_at', m.created_at, 'role', m.role, 'text', m.content, "
            "'based_on', m.sources, 'tools', m.tools_used, 'conversation', s.title) "
            "from intel.ask_message m join intel.ask_session s on s.id = m.session_id where m.id = :i"),
            i=str(record.record_id))
        return {"ask_message": data}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        row = session.execute(text(
            "select m.session_id from intel.ask_message m where m.id = :i for update"),
            {"i": str(record.record_id)}).first()
        if row is None:
            return Outcome("refused", message="The message no longer exists")
        session.execute(text(
            "update intel.ask_message set content = :r, sources = '[]'::jsonb, flag_reason = null, "
            "tools_used = (select coalesce(jsonb_agg(jsonb_build_object('tool', t ->> 'tool', "
            "'status', t ->> 'status')), '[]'::jsonb) from jsonb_array_elements(intel.ask_message.tools_used) t) "
            "where id = :i"),
            {"r": REMOVED, "i": str(record.record_id)})
        session.execute(text("update intel.ask_session set title = :r where id = :s"),
                        {"r": f"{PLACEHOLDER} question", "s": str(row.session_id)})
        return Outcome("anonymised", changed=["text of the question or answer removed",
                                              "rows the answer was based on removed"],
                       kept=[Kept("who asked, when, which tools were called and the token counts",
                                  "the record of how the assistant was used; it names no one but the asker")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        eligible = int(session.execute(text(
            "select count(*) from intel.ask_session where company_id = :c "
            "and last_at < now() - make_interval(days => :d)"),
            {"c": str(company_id), "d": CONVERSATION_DAYS}).scalar_one())
        return [RetentionRule("intel", "ask_conversations",
                              "Questions to Ask Ziira and the answers with the rows they used",
                              "Letting a person read back what they asked",
                              period=f"{CONVERSATION_DAYS} days after the last message", at_end="mask",
                              eligible=eligible)]
