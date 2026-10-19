"""Keeping members: messages that bring people back, queued by the recurring task (never in a request, never in quiet
hours, never to someone who asked not to be contacted): not seen for N weeks, birthday, and a follow-up after a
trial."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ziira.modules.memberships.domain.quiet import is_quiet
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, notify
from ziira.sdk import Session, company_setting

BATCH = 300


def send_due(session: Session, company_id: UUID, now: datetime | None = None) -> dict[str, int]:
    """Queue the retention messages that are due for a company. Returns how many of each kind were queued."""
    settings = repo.get_settings(session, company_id)
    done = {"inactive": 0, "birthday": 0, "trial": 0}
    if not settings["reminders_enabled"]:
        return done
    zone = ZoneInfo(str(company_setting(session, company_id, "timezone")))
    local = (now or datetime.now(UTC)).astimezone(zone)
    if is_quiet(local.hour, int(settings["quiet_start"]), int(settings["quiet_end"])):
        return done
    today = local.date()
    company = common.one_company(session, company_id)
    language, business = str(settings["message_language"]), company["name"]

    weeks = int(settings["inactive_weeks"])
    if weeks > 0:
        cutoff = today - timedelta(weeks=weeks)
        lapsed = repo.many(
            session,
            "select p.* from memberships.profile p join memberships.member m on m.customer_id = p.customer_id "
            "and m.status = 'active' where p.company_id = :c and coalesce(p.last_visit_on, m.start_date) <= :cut "
            "and (p.inactive_notice_for is null or p.inactive_notice_for < coalesce(p.last_visit_on, m.start_date)) "
            "group by p.id order by p.last_visit_on nulls first limit :n", c=company_id, cut=cutoff, n=BATCH)
        people = common.customer_names(session, {p["customer_id"] for p in lapsed})
        for p in lapsed:
            who = people.get(p["customer_id"])
            marker = p["last_visit_on"] or cutoff
            if who is not None and notify.send(
                    session, company_id, who, "membership_inactive",
                    {"customer": who.name, "business": business, "weeks": str(weeks)}, language,
                    "memberships.profile", p["id"], f"memberships:inactive:{p['id']}:{marker}"):
                done["inactive"] += 1
            repo.update(session, "profile", p["id"], {"inactive_notice_for": today})

    if settings["birthday_messages"]:
        due = repo.many(
            session,
            "select * from memberships.profile where company_id = :c and date_of_birth is not null "
            "and extract(month from date_of_birth) = :m and extract(day from date_of_birth) = :d "
            "and (birthday_notice_year is null or birthday_notice_year <> :y) and lifecycle in ('member', 'trial') "
            "limit :n", c=company_id, m=today.month, d=today.day, y=today.year, n=BATCH)
        people = common.customer_names(session, {p["customer_id"] for p in due})
        for p in due:
            who = people.get(p["customer_id"])
            if who is not None and notify.send(
                    session, company_id, who, "membership_birthday", {"customer": who.name, "business": business},
                    language, "memberships.profile", p["id"], f"memberships:birthday:{p['id']}:{today.year}"):
                done["birthday"] += 1
            repo.update(session, "profile", p["id"], {"birthday_notice_year": today.year})

    over = repo.many(
        session,
        "select p.* from memberships.profile p where p.company_id = :c and p.lifecycle in ('trial', 'former') "
        "and p.trial_ends_on is not null and p.trial_ends_on <= :d and not p.trial_notice_sent "
        "and not exists (select 1 from memberships.member m where m.customer_id = p.customer_id "
        "and m.status in ('active', 'paused', 'frozen') and not m.is_trial) limit :n", c=company_id, d=today, n=BATCH)
    people = common.customer_names(session, {p["customer_id"] for p in over})
    for p in over:
        who = people.get(p["customer_id"])
        if who is not None and notify.send(
                session, company_id, who, "membership_trial_followup", {"customer": who.name, "business": business},
                language, "memberships.profile", p["id"], f"memberships:trial:{p['id']}"):
            done["trial"] += 1
        repo.update(session, "profile", p["id"], {"trial_notice_sent": True})
    return done
