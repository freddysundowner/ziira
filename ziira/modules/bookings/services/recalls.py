"""Recalls: "due again" lists and the reminders that bring clients back.

A service can say when its client is due again (`recall_days`: a cut every 6 weeks, a check-up every 6 months). The list
shows clients whose last finished visit for that service is older than that and who have nothing booked; an outcome
logged against a client (messaged, phoned, declined, snoozed) keeps the list honest. Reminders and the rebooking prompt
after a visit are only ever **queued** (the worker sends them), respect quiet hours, the do-not-contact list and the
business's switch.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import access, clients, notify
from ziira.modules.bookings.services.common import now, unit_enabled, user_id
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, company_today

DUE_SQL = """
with last_visit as (
  select distinct on (a.customer_id, a.offer_id) a.customer_id, a.offer_id, a.id as appointment_id, a.branch_id,
         a.client_name, a.client_phone, a.client_email, a.completed_at,
         (a.completed_at at time zone :tz)::date as visited_on
  from bookings.appointment a
  where a.company_id = :c and a.status = 'completed' and a.kind = 'appointment' and a.customer_id is not null
    and (cast(:b as uuid) is null or a.branch_id = :b)
  order by a.customer_id, a.offer_id, a.completed_at desc
)
select v.customer_id, v.offer_id, v.appointment_id, v.branch_id, v.client_name, v.client_phone, v.client_email,
       o.name as service, o.recall_days, v.visited_on, v.visited_on + o.recall_days as due_on,
       (select max(l.created_at) from bookings.recall_log l where l.company_id = :c and l.customer_id = v.customer_id
          and l.offer_id = v.offer_id and l.created_at > v.completed_at) as last_contacted_at,
       (select l.outcome from bookings.recall_log l where l.company_id = :c and l.customer_id = v.customer_id
          and l.offer_id = v.offer_id and l.created_at > v.completed_at
        order by l.created_at desc limit 1) as last_outcome
from last_visit v
join bookings.service_offer o on o.id = v.offer_id and o.recall_days is not null and o.is_active
where v.visited_on + o.recall_days <= :today
  and not exists (select 1 from bookings.appointment f where f.company_id = :c and f.customer_id = v.customer_id
        and f.status in ('requested', 'confirmed', 'checked_in', 'in_service') and f.starts_at >= now())
  and not exists (select 1 from bookings.recall_log s where s.company_id = :c and s.customer_id = v.customer_id
        and s.offer_id = v.offer_id and s.outcome in ('declined', 'booked') and s.created_at > v.completed_at)
  and not exists (select 1 from bookings.recall_log s where s.company_id = :c and s.customer_id = v.customer_id
        and s.offer_id = v.offer_id and s.outcome = 'snoozed' and s.snooze_until > :today
        and s.created_at > v.completed_at)
order by v.visited_on + o.recall_days, v.client_name
limit :lim"""


def due_list(session: Session, company_id: UUID, *, branch_id: UUID | None = None,
             limit: int = 200) -> list[dict[str, Any]]:
    """Clients due again, most overdue first. Each row: who, which service, last visit, due date, days overdue, and
    when (and how) they were last contacted since that visit."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    today = company_today(session, company_id)
    tz = str(repo_zone(session, company_id))
    rows = raw.many(session, DUE_SQL, tz=tz, c=company_id, b=branch_id, today=today, lim=min(limit, 500))
    for r in rows:
        r["overdue_days"] = (today - r["due_on"]).days
    return rows


def repo_zone(session: Session, company_id: UUID) -> Any:
    from ziira.modules.bookings.services.common import zone

    return zone(session, company_id)


def _customer_contact(session: Session, customer_id: UUID, row: dict[str, Any]) -> tuple[str | None, str | None, str]:
    phone, email, name = row.get("client_phone"), row.get("client_email"), row.get("client_name") or ""
    if (not phone and not email) and unit_enabled(session, "crm"):
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, customer_id)
        if found is not None:
            phone, email, name = found.phone, found.email, name or found.name
    return phone, email, name


def send_recall(session: Session, company_id: UUID, customer_id: UUID, offer_id: UUID, *,
                automatic: bool = False) -> dict[str, Any]:
    """Message a client who is due again (once per last visit) and note it. Needs 'bookings.manage' unless the
    worker is doing it. Raises when the client has no way to be reached."""
    if not automatic:
        clients._manage_in_company(company_id)
    today = company_today(session, company_id)
    tz = str(repo_zone(session, company_id))
    row = next((r for r in raw.many(session, DUE_SQL, tz=tz, c=company_id, b=None, today=today, lim=500)
                if r["customer_id"] == customer_id and r["offer_id"] == offer_id), None)
    if row is None:
        raise ValidationFailed("That client is not due again")
    return _send(session, company_id, row, automatic)


def _send(session: Session, company_id: UUID, row: dict[str, Any], automatic: bool) -> dict[str, Any]:
    phone, email, name = _customer_contact(session, row["customer_id"], row)
    if raw.one(session, "select 1 as x from bookings.recall_log where appointment_id = :a and kind = 'recall'",
               a=row["appointment_id"]):
        raise ValidationFailed("They were already messaged since their last visit")
    queued = notify.to_contact(
        session, company_id=company_id, phone=phone, email=email,
        template=repo.ensure_settings(session, company_id).recall_template or "appointment_recall",
        variables={"customer": name, "service": row["service"], "business": notify.business_name(session, company_id)},
        ref_type="bookings.appointment", ref_id=row["appointment_id"], dedupe_key=f"recall:{row['appointment_id']}")
    if queued is None:
        raise ValidationFailed("There is no way to reach this client: no phone or email, or no channel is set up")
    made = raw.insert(session, "recall_log", {
        "company_id": company_id, "customer_id": row["customer_id"], "offer_id": row["offer_id"],
        "appointment_id": row["appointment_id"], "kind": "recall", "outcome": "sent",
        "note": "automatic" if automatic else None}, user_id=user_id())
    audit_record(session, "recall", "bookings.appointment", row["appointment_id"], {"automatic": automatic})
    return made


def log_outcome(session: Session, company_id: UUID, customer_id: UUID, offer_id: UUID, outcome: str, *,
                snooze_until: date | None = None, note: str | None = None) -> dict[str, Any]:
    """Note what happened when staff phoned or spoke to a client: called, declined, snoozed until a date, booked."""
    clients._manage_in_company(company_id)
    if outcome not in ("called", "declined", "snoozed", "booked"):
        raise ValidationFailed("Outcome is called, declined, snoozed or booked")
    if outcome == "snoozed" and snooze_until is None:
        raise ValidationFailed("Say until when")
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    made = raw.insert(session, "recall_log", {
        "company_id": company_id, "customer_id": customer_id, "offer_id": offer_id, "kind": "recall",
        "outcome": outcome, "snooze_until": snooze_until, "note": (note or "").strip()[:300] or None},
        user_id=user_id())
    audit_record(session, "recall_outcome", "bookings.recall_log", made["id"], {"outcome": outcome})
    return made


# --------------------------------------------------------------------------- worker
def run_automatic(session: Session, *, limit: int = 100) -> int:
    """Queue recall reminders and rebooking prompts that are due, for every company that has them switched on, outside
    its quiet hours. Returns how many were queued."""
    from ziira.modules.bookings.services import notify as nt

    queued = 0
    moment = now()
    for c in raw.many(session, "select * from bookings.booking_settings "
                               "where recalls_enabled or rebook_prompt_hours > 0"):
        if nt.in_quiet_hours(session, c["company_id"], moment, c["quiet_start"], c["quiet_end"]):
            continue
        company_id = c["company_id"]
        if c["recalls_enabled"]:
            today = company_today(session, company_id)
            tz = str(repo_zone(session, company_id))
            for row in raw.many(session, DUE_SQL, tz=tz, c=company_id, b=None, today=today, lim=limit):
                if row["last_contacted_at"] is not None:
                    continue
                try:
                    with session.begin_nested():
                        _send(session, company_id, row, True)
                    queued += 1
                except ValidationFailed:
                    continue
        if c["rebook_prompt_hours"] > 0:
            queued += _rebook_prompts(session, company_id, c["rebook_prompt_hours"], limit)
    return queued


def _rebook_prompts(session: Session, company_id: UUID, hours: int, limit: int) -> int:
    """After a finished visit, invite the client to book again (once) if nothing is booked yet."""
    moment = now()
    rows = raw.many(session, """
        select a.id as appointment_id, a.customer_id, a.offer_id, a.client_name, a.client_phone, a.client_email,
               o.name as service
        from bookings.appointment a join bookings.service_offer o on o.id = a.offer_id
        where a.company_id = :c and a.status = 'completed' and a.kind = 'appointment' and a.customer_id is not null
          and a.completed_at between :lo and :hi
          and not exists (select 1 from bookings.recall_log l where l.appointment_id = a.id and l.kind = 'rebook')
          and not exists (select 1 from bookings.appointment f where f.company_id = :c and f.customer_id = a.customer_id
              and f.status in ('requested', 'confirmed', 'checked_in', 'in_service') and f.starts_at >= now())
        limit :lim""", c=company_id, lo=moment - timedelta(hours=hours + 24), hi=moment - timedelta(hours=hours),
                   lim=limit)
    sent = 0
    for r in rows:
        phone, email, name = _customer_contact(session, r["customer_id"], r)
        queued = notify.to_contact(
            session, company_id=company_id, phone=phone, email=email,
            template=repo.ensure_settings(session, company_id).rebook_template or "appointment_rebook",
            variables={"customer": name, "service": r["service"],
                       "business": notify.business_name(session, company_id)},
            ref_type="bookings.appointment", ref_id=r["appointment_id"], dedupe_key=f"rebook:{r['appointment_id']}")
        raw.insert(session, "recall_log", {
            "company_id": company_id, "customer_id": r["customer_id"], "offer_id": r["offer_id"],
            "appointment_id": r["appointment_id"], "kind": "rebook", "outcome": "sent" if queued else "declined",
            "note": None if queued else "no way to reach"})
        sent += 1 if queued else 0
    return sent
