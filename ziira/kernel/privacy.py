"""Data protection: data subject requests and retention.

Ziira is a processor of each business's data. A person (a customer, an employee, a supplier) can ask a business what it
holds about them (access), to correct it (correction) or to erase it (erasure). The business, as the controller, tracks
each request here and works it in steps:

    create  ->  search (every unit that holds personal data looks)  ->  export (access / correction)
                                                                    ->  erase  (needs `privacy.manage`, a typed
                                                                        confirmation, a reason and, by default, a second
                                                                        person's approval)
                                                                    ->  close

What each unit finds, exports and anonymises is the unit's own business, supplied through the "kernel.personal_data"
socket (personal_data.py). The rules are data, not code: retention periods are company settings, and a unit refuses (or
partly anonymises) a record the business has said it must keep. Nothing here depends on any country's law; see
docs/privacy.md.

Rules kept here:
- Every request, search, export and erasure is audited; an export is marked `data_export` in the audit log.
- The audit log carries no personal data of the subject: only a masked form of what was searched for.
- Erasure is irreversible. It never touches the immutable tables (journal, stock movements, audit log).
"""

import json
import logging
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, company_settings, privacy_providers  # noqa: F401 - the providers register themselves
from ziira.kernel import custom_fields as _custom_fields  # noqa: F401 - its provider registers itself
from ziira.kernel import files as _files  # noqa: F401 - its provider and integrity check register themselves
from ziira.kernel.approvals import submit_for_approval
from ziira.kernel.context import get_context
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.events import Event, subscribe
from ziira.kernel.exceptions_inbox import flag
from ziira.kernel.extensions import implementations
from ziira.kernel.jobs import periodic
from ziira.kernel.numbering import next_document_number
from ziira.kernel.personal_data import (
    PERSONAL_DATA,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    parse_subject,
)

log = logging.getLogger("ziira.privacy")
PERMISSION = "privacy.manage"
ERASURE_DOCUMENT = "privacy.erasure"
TYPES = ("access", "correction", "erasure")
OPEN_STATUSES = ("open", "in_progress")
RETENTION_SETTINGS = ("retention_notifications_days", "retention_audit_years", "retention_employee_records_years",
                      "retention_inactive_customers_years")
COLUMNS = ("id, created_at, created_by, company_id, number, request_type, subject, subject_masked, status, "
           "received_on, due_date, handled_by, notes, found, erase_plan, outcome, completed_at")


# --------------------------------------------------------------------------- helpers
def _providers(session: Session) -> dict[str, PersonalDataProvider]:
    return {p.name: p for p in implementations(session, PERSONAL_DATA)}


def _jsonable(value: Any) -> Any:
    """Plain JSON types (dates, decimals and ids as text) so a bundle can be stored and sent as it is."""
    return json.loads(json.dumps(value, default=str))


def _record_dict(record: PersonalRecord) -> dict[str, Any]:
    return dict(_jsonable(asdict(record)))


def _record_from(entry: dict[str, Any]) -> PersonalRecord:
    return PersonalRecord(source=entry["source"], kind=entry["kind"], record_id=UUID(entry["record_id"]),
                          label=entry["label"], match=entry["match"],
                          company_id=UUID(entry["company_id"]) if entry.get("company_id") else None,
                          ref=entry.get("ref") or "")


def _actor() -> str | None:
    user_id = get_context().user_id
    return str(user_id) if user_id else None


def _public(row: Any) -> dict[str, Any]:
    """A request as the API shows it. The providers' private pointers (`ref`) are not shown."""
    found = [{k: v for k, v in entry.items() if k != "ref"} for entry in (row.found or [])]
    plan = row.erase_plan
    return {"id": row.id, "number": row.number, "company_id": row.company_id, "request_type": row.request_type,
            "subject": row.subject, "subject_masked": row.subject_masked, "status": row.status,
            "received_on": row.received_on, "due_date": row.due_date, "overdue": row.status in OPEN_STATUSES
            and row.due_date < date.today(), "handled_by": row.handled_by, "notes": row.notes, "found": found,
            "awaiting_approval": plan is not None, "outcome": row.outcome, "completed_at": row.completed_at,
            "created_at": row.created_at}


def _load(session: Session, request_id: UUID, *, lock: bool = False) -> Any:
    row = session.execute(text(f"select {COLUMNS} from kernel.privacy_request where id = :i"
                               + (" for update" if lock else "")), {"i": str(request_id)}).first()
    if row is None:
        raise NotFound("Data subject request not found")
    get_context().require(PERMISSION, company_id=row.company_id)
    return row


def _touch(session: Session, request_id: UUID, **columns: Any) -> None:
    sets = ", ".join(f"{c} = cast(:{c} as jsonb)" if c in ("found", "outcome", "erase_plan") else f"{c} = :{c}"
                     for c in columns)
    values = {c: (json.dumps(v, default=str) if c in ("found", "outcome", "erase_plan") and v is not None else v)
              for c, v in columns.items()}
    session.execute(text(f"update kernel.privacy_request set {sets}, updated_at = now(), "
                         "updated_by = cast(:actor as uuid), handled_by = coalesce(cast(:actor as uuid), handled_by) "
                         "where id = :id"),
                    {**values, "actor": _actor(), "id": str(request_id)})


def _selected(row: Any, record_ids: list[UUID] | None) -> list[PersonalRecord]:
    """The records an export or erasure covers: the exact matches, plus any possible match that was listed by id."""
    found = [_record_from(e) for e in (row.found or [])]
    if record_ids is None:
        chosen = [r for r in found if r.match == "exact"]
    else:
        known = {r.record_id: r for r in found}
        unknown = [str(i) for i in record_ids if i not in known]
        if unknown:
            raise ValidationFailed("These records were not found by this request's search: " + ", ".join(unknown))
        chosen = [known[i] for i in dict.fromkeys(record_ids)]
    if not chosen:
        raise ValidationFailed("No records selected. Search first; possible matches (by name) are included only when "
                               "you list their ids after checking they are the same person")
    return chosen


def _summary(records: list[PersonalRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        counts[r.source] = counts.get(r.source, 0) + 1
    return counts


# --------------------------------------------------------------------------- requests
def create_request(session: Session, *, company_id: UUID, request_type: str, subject: str,
                   notes: str | None = None, received_on: date | None = None) -> dict[str, Any]:
    """Record that a person has asked for access, correction or erasure. The due date is `privacy_response_days` after
    it was received."""
    ctx = get_context()
    ctx.require(PERMISSION, company_id=company_id)
    if request_type not in TYPES:
        raise ValidationFailed(f"The request type is one of: {', '.join(TYPES)}")
    exists = session.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first()
    if exists is None:
        raise ValidationFailed("Company not found")
    settings = company_settings.get_settings(session, company_id)
    parsed = parse_subject(subject, settings["phone_country_code"])
    received = received_on or date.today()
    if received > date.today():
        raise ValidationFailed("A request cannot be received in the future")
    number = next_document_number(session, company_id=company_id, branch_id=None, doc_type="privacy_request",
                                  prefix="DSR")
    due = received + timedelta(days=int(settings["privacy_response_days"]))
    request_id: UUID = session.execute(text(
        "insert into kernel.privacy_request (tenant_id, created_by, company_id, number, request_type, subject, "
        "subject_masked, received_on, due_date, notes, handled_by) values (kernel.current_tenant(), :u, :c, :n, :t, "
        ":s, :m, :r, :d, :notes, :u) returning id"),
        {"u": _actor(), "c": str(company_id), "n": number, "t": request_type, "s": parsed.raw, "m": parsed.masked,
         "r": received, "d": due, "notes": (notes or "").strip() or None}).scalar_one()
    audit.record(session, "create", "kernel.privacy_request", request_id,
                 {"number": number, "type": request_type, "subject": parsed.masked, "due_date": due})
    return _public(_load(session, request_id))


def get_request(session: Session, request_id: UUID) -> dict[str, Any]:
    """One request with what its search found."""
    return _public(_load(session, request_id))


def list_requests(session: Session, *, status: str | None = None, company_id: UUID | None = None,
                  limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Requests of the companies the user may handle them for, the oldest due first."""
    allowed = get_context().companies_with(PERMISSION)
    rows = session.execute(text(
        f"select {COLUMNS} from kernel.privacy_request where (cast(:s as text) is null or status = :s) "
        "and (cast(:c as uuid) is null or company_id = :c) order by due_date, created_at limit :l offset :o"),
        {"s": status, "c": str(company_id) if company_id else None, "l": limit, "o": offset})
    return [_public(r) for r in rows if allowed is None or r.company_id in allowed]


def search(session: Session, request_id: UUID) -> dict[str, Any]:
    """Ask every unit that holds personal data what it holds about the subject, and keep the answer on the request."""
    row = _load(session, request_id, lock=True)
    _require_open(row)
    settings = company_settings.get_settings(session, row.company_id)
    subject = parse_subject(row.subject, settings["phone_country_code"])
    found: list[PersonalRecord] = []
    providers = _providers(session).values()
    for provider in providers:
        found.extend(provider.find(session, row.company_id, subject))
    primary = list(found)
    for provider in providers:
        found.extend(provider.linked(session, row.company_id, primary))
    entries = [_record_dict(r) for r in found]
    _touch(session, row.id, found=entries, status="in_progress")
    audit.record(session, "search", "kernel.privacy_request", row.id,
                 {"subject": row.subject_masked, "found": _summary(found),
                  "possible_matches": sum(1 for r in found if r.match == "possible")})
    return get_request(session, request_id)


def export(session: Session, request_id: UUID, record_ids: list[UUID] | None = None) -> dict[str, Any]:
    """The data held about the subject, as one JSON bundle. Every export is written to the audit log as a data export
    (who took it, from where, how many records of which units); the bundle itself is not stored."""
    row = _load(session, request_id, lock=True)
    if row.status in ("completed", "refused") and row.request_type == "erasure":
        raise Conflict("This erasure is finished; the data it covered no longer exists")
    records = _selected(row, record_ids)
    providers = _providers(session)
    bundle = []
    for record in records:
        provider = providers.get(record.source)
        if provider is None:
            raise ValidationFailed(f"'{record.source}' is no longer enabled, so its records cannot be exported")
        bundle.append({"source": record.source, "kind": record.kind, "record_id": record.record_id,
                       "match": record.match, "data": provider.export(session, record)})
    ctx = get_context()
    now = datetime.now(UTC)
    outcome = dict(row.outcome or {})
    outcome.setdefault("exports", []).append({"at": now, "by": ctx.user_id, "records": len(records)})
    _touch(session, row.id, outcome=outcome, status="in_progress" if row.status == "open" else row.status)
    audit.record(session, "data_export", "kernel.privacy_request", row.id,
                 {"data_export": True, "subject": row.subject_masked, "records": len(records),
                  "sources": _summary(records), "channel": ctx.channel})
    return dict(_jsonable({"request": {"number": row.number, "type": row.request_type, "company_id": row.company_id,
                                       "received_on": row.received_on, "due_date": row.due_date},
                           "subject": row.subject, "generated_at": now, "generated_by": ctx.user_id,
                           "records": bundle}))


def close_request(session: Session, request_id: UUID, *, outcome: str, note: str) -> dict[str, Any]:
    """Finish a request by hand: 'completed' (a correction was made, the answer was sent) or 'refused' (with the reason
    the business gives the person)."""
    row = _load(session, request_id, lock=True)
    _require_open(row)
    if outcome not in ("completed", "refused"):
        raise ValidationFailed("Close a request as 'completed' or 'refused'")
    if not note.strip():
        raise ValidationFailed("Say what was done, or why the request is refused")
    if row.erase_plan is not None:
        raise Conflict("An erasure is waiting for approval; wait for the decision")
    result = dict(row.outcome or {})
    result["closing_note"] = note.strip()
    _touch(session, row.id, status=outcome, outcome=result, completed_at=datetime.now(UTC))
    audit.record(session, outcome, "kernel.privacy_request", row.id,
                 {"subject": row.subject_masked, "note": note.strip()})
    return get_request(session, request_id)


def _require_open(row: Any) -> None:
    if row.status not in OPEN_STATUSES:
        raise Conflict(f"This request is already {row.status}")


# --------------------------------------------------------------------------- erasure
def erase(session: Session, request_id: UUID, *, confirm_subject: str, reason: str,
          record_ids: list[UUID] | None = None) -> dict[str, Any]:
    """Anonymise the records found for the subject. The caller must repeat the subject (so the wrong request is never
    erased by a slip) and give a reason. When the company setting `privacy_erasure_needs_approval` is on (the default),
    a second person approves first: the request waits for the decision in the approval matrix (document type
    'privacy.erasure') and the erasure runs when it is approved."""
    row = _load(session, request_id, lock=True)
    _require_open(row)
    if row.request_type != "erasure":
        raise ValidationFailed("Only an erasure request can erase data. Record a new request of type 'erasure'")
    if " ".join(confirm_subject.split()).casefold() != " ".join(row.subject.split()).casefold():
        raise ValidationFailed("The confirmation does not match the subject of this request")
    if len(reason.strip()) < 5:
        raise ValidationFailed("Give the reason for the erasure (at least a few words)")
    if row.erase_plan is not None:
        raise Conflict("This erasure is already waiting for approval")
    records = _selected(row, record_ids)
    if company_settings.get_setting(session, row.company_id, "privacy_erasure_needs_approval"):
        decision = submit_for_approval(session, company_id=row.company_id, doc_type=ERASURE_DOCUMENT, doc_id=row.id)
        if decision.status == "approved":
            raise ValidationFailed(
                "Erasure needs a second person's approval, but the approval matrix has no rule for 'privacy.erasure'. "
                "Add one (a role that approves, for example Owner), or switch off the company setting "
                "'privacy_erasure_needs_approval'")
        plan = {"reason": reason.strip(), "record_ids": [str(r.record_id) for r in records], "requested_by": _actor()}
        _touch(session, row.id, erase_plan=plan, status="in_progress")
        audit.record(session, "erase_requested", "kernel.privacy_request", row.id,
                     {"subject": row.subject_masked, "records": len(records), "sources": _summary(records),
                      "reason": reason.strip()})
        return get_request(session, request_id)
    _execute_erasure(session, row, records, reason.strip(), requested_by=_actor(), approved_by=None)
    return get_request(session, request_id)


def _execute_erasure(session: Session, row: Any, records: list[PersonalRecord], reason: str, *,
                     requested_by: str | None, approved_by: str | None) -> None:
    providers = _providers(session)
    results = []
    for record in records:
        provider = providers.get(record.source)
        if provider is None:
            raise ValidationFailed(f"'{record.source}' is no longer enabled, so its records cannot be erased")
        outcome = provider.anonymise(session, record, reason)
        results.append({"source": record.source, "kind": record.kind, "record_id": record.record_id,
                        "status": outcome.status, "changed": outcome.changed,
                        "kept": [{"what": k.what, "why": k.why} for k in outcome.kept], "message": outcome.message})
    done = {r["record_id"] for r in results if r["status"] != "refused"}
    refused = [r for r in results if r["status"] == "refused"]
    fully = all(r["status"] == "anonymised" for r in results)
    found = [({**e, "label": "(erased)", "ref": ""} if UUID(e["record_id"]) in done else e) for e in (row.found or [])]
    outcome_json = dict(row.outcome or {})
    outcome_json["erasure"] = _jsonable({"at": datetime.now(UTC), "reason": reason, "requested_by": requested_by,
                                         "approved_by": approved_by, "results": results})
    status = "refused" if len(refused) == len(results) else "completed"
    _touch(session, row.id, status=status, outcome=outcome_json, found=found, erase_plan=None,
           completed_at=datetime.now(UTC), **({"subject": row.subject_masked} if fully else {}))
    audit.record(session, "erase", "kernel.privacy_request", row.id,
                 {"subject": row.subject_masked, "reason": reason, "requested_by": requested_by,
                  "approved_by": approved_by, "status": status,
                  "results": [{k: r[k] for k in ("source", "kind", "status", "changed", "kept", "message")}
                              for r in _jsonable(results)]})


@subscribe("approval.decided")
def erasure_decided(session: Session, event: Event) -> None:
    """The second person decided on an erasure: run it, or put the request back in the handler's hands."""
    if event.aggregate_type != ERASURE_DOCUMENT:
        return
    row = session.execute(text(f"select {COLUMNS} from kernel.privacy_request where id = :i for update"),
                          {"i": str(event.aggregate_id)}).first()
    if row is None or row.erase_plan is None or row.status not in OPEN_STATUSES:
        return
    plan = row.erase_plan
    approver = event.payload.get("decided_by")
    if event.payload.get("status") == "approved":
        records = _selected(row, [UUID(i) for i in plan["record_ids"]])
        _execute_erasure(session, row, records, plan["reason"], requested_by=plan.get("requested_by"),
                         approved_by=str(approver) if approver else None)
        return
    _touch(session, row.id, erase_plan=None)
    audit.record(session, "erase_rejected", "kernel.privacy_request", row.id,
                 {"subject": row.subject_masked, "rejected_by": approver, "note": event.payload.get("note")})


# --------------------------------------------------------------------------- retention
def retention_overview(session: Session, company_id: UUID) -> dict[str, Any]:
    """What each unit keeps about people and for how long, with the company's retention settings."""
    get_context().require(PERMISSION, company_id=company_id)
    if session.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise NotFound("Company not found")
    settings = company_settings.get_settings(session, company_id)
    rules: list[RetentionRule] = []
    for provider in _providers(session).values():
        rules.extend(provider.retention(session, company_id))
    return {"company_id": company_id, "settings": {k: settings[k] for k in RETENTION_SETTINGS},
            "rules": [asdict(r) for r in rules],
            "never_deleted": ["audit log", "journal entries and lines", "stock movements"]}


def apply_retention(session: Session) -> dict[str, int]:
    """Apply the retention periods of every company: mask the notifications past their period, flag what a person must
    review (inactive customers) and requests past their due date. Reports the counts in the audit log. Only mutable
    tables are touched: never the journal, stock movements or the audit log."""
    totals = {"notifications_masked": 0, "review_items": 0, "overdue_requests": 0}
    for company_id in session.execute(text("select id from kernel.company order by id")).scalars().all():
        days = int(company_settings.get_setting(session, company_id, "retention_notifications_days"))
        if days > 0:
            recipients = session.execute(text(
                "select distinct recipient from kernel.notification where company_id = :c and redacted_at is null "
                "and recipient is not null and status <> 'queued' and created_at < now() - make_interval(days => :d)"),
                {"c": str(company_id), "d": days}).scalars().all()
            masked = sum(privacy_providers.redact_recipient(session, company_id, r, privacy_providers.REDACTED_BODY,
                                                            older_than_days=days) for r in recipients)
            if masked:
                totals["notifications_masked"] += masked
                audit.record(session, "retention_mask", "kernel.notification", None,
                             {"company_id": company_id, "messages_masked": masked, "older_than_days": days})
        for provider in _providers(session).values():
            for rule in provider.retention(session, company_id):
                if rule.at_end == "review" and rule.eligible > 0:
                    created = flag(session, unit=rule.unit, kind="retention_review", severity="low",
                                   company_id=company_id, dedupe_key=f"retention:{company_id}:{rule.unit}:{rule.code}",
                                   message=f"{rule.eligible} record(s) are past the retention period ({rule.period}): "
                                           f"{rule.what}. Review them and erase through a data subject request if they "
                                           "are no longer needed")
                    totals["review_items"] += 1 if created else 0
    overdue = session.execute(text(
        "select id, company_id, number from kernel.privacy_request where status in ('open', 'in_progress') "
        "and due_date < current_date")).all()
    for r in overdue:
        created = flag(session, unit="kernel", kind="privacy_request_overdue", severity="high", company_id=r.company_id,
                       ref_type="privacy_request", ref_id=r.id, dedupe_key=f"privacy_overdue:{r.id}",
                       message=f"Data subject request {r.number} is past its due date")
        totals["overdue_requests"] += 1 if created else 0
    return totals


@periodic("privacy.apply_retention", every_seconds=86400)
def apply_retention_daily(session: Session) -> None:
    """Once a day for each business: mask old messages, flag records and requests that need a person."""
    counts = apply_retention(session)
    if any(counts.values()):
        log.info("Retention applied: %s", counts)
