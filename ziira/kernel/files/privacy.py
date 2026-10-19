"""Files as personal data: a photo can show a person, a caption can name one. Plugs into "kernel.personal_data".

* `find`: files whose caption, name or consent note contain the person's email, phone or id (a name matches loosely).
* `linked`: every file attached to a record another unit found for the person (their customer card, their jobs ...).
* `export`: the details of each file and where the staff member handling the request can download it.
* `anonymise`: a photo cannot be made anonymous, so the file is removed (the row keeps who removed it and why).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.extensions import provides
from ziira.kernel.files import service
from ziira.kernel.personal_data import (
    PERSONAL_DATA,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Subject,
    like_pattern,
)

_SUMMARY = ("select id, entity_type, entity_id, category, kind, created_at, company_id from kernel.attachment "
            "where status = 'active' and (company_id is null or company_id = :c) and ")


def _record(row: Any, company_id: UUID, match: str) -> PersonalRecord:
    return PersonalRecord("kernel.files", "file", row.id, f"{row.kind} ({row.category}) on a {row.entity_type}",
                          match, company_id)


@provides(PERSONAL_DATA)
class FileData(PersonalDataProvider):
    name = "kernel.files"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        terms = [(v, "exact") for v in (subject.email, subject.phone, subject.identifier) if v]
        if subject.name:
            terms.append((subject.name, "possible"))
        for value, match in terms:
            rows = session.execute(text(
                _SUMMARY + "(caption ilike :v escape '\\' or original_name ilike :v escape '\\' "
                "or consent_note ilike :v escape '\\')"), {"c": str(company_id), "v": like_pattern(value)})
            for row in rows:
                if row.id not in found or match == "exact":
                    found[row.id] = _record(row, company_id, match)
        return list(found.values())

    def linked(self, session: Session, company_id: UUID, found: list[PersonalRecord]) -> list[PersonalRecord]:
        by_id = {r.record_id: r for r in found if r.source != self.name}
        if not by_id:
            return []
        rows = session.execute(text(_SUMMARY + "entity_id = any(cast(:ids as uuid[]))"),
                               {"c": str(company_id), "ids": [str(i) for i in by_id]})
        return [_record(row, company_id, by_id[row.entity_id].match) for row in rows]

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        row = session.execute(text(
            "select id, entity_type, entity_id, category, caption, visibility, consent_note, kind, content_type, "
            "original_name, size_bytes, checksum, created_at, created_by from kernel.attachment where id = :i and "
            "status = 'active'"), {"i": str(record.record_id)}).first()
        if row is None:
            return {}
        data = dict(row._mapping)
        data["download_path"] = f"/api/v1/files/{row.id}/content?variant=original"
        data["note"] = "The picture or document itself is downloaded from download_path by whoever handles the request"
        return data

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        row = session.execute(text(f"select {service._COLUMNS} from {service._FROM} where f.id = :i "
                                   "and f.status = 'active' for update of f"), {"i": str(record.record_id)}).first()
        if row is None:
            return Outcome("refused", message="That file no longer exists")
        service._remove(session, row, f"data subject request: {reason}"[:300])
        return Outcome("anonymised", changed=["the file and its copies"],
                       kept=[Kept("who removed the file, when and why", "the business keeps a record of removals")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        from ziira.kernel import company_settings

        years = int(company_settings.get_setting(session, company_id, "retention_files_years"))
        eligible = 0
        if years > 0:
            eligible = int(session.execute(text(
                "select count(*) from kernel.attachment where status = 'active' and company_id = :c "
                "and created_at < now() - make_interval(years => :y)"),
                {"c": str(company_id), "y": years}).scalar_one())
        return [RetentionRule(
            unit="kernel", code="files", what="Photos and documents attached to records",
            basis="evidence of the work done and of what was agreed with the customer",
            setting="retention_files_years", period=f"{years} years" if years else "until removed",
            at_end="review", eligible=eligible)]
