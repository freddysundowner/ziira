"""Briefs: a short account of what happened and what needs attention, composed for one person within their role."""

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ziira.modules.command.domain.compose import Brief, FindingLine, PulseLine, compose
from ziira.modules.command.domain.schedule import is_due
from ziira.modules.command.permissions import COMMAND_VIEW
from ziira.modules.command.repository import command_repo as repo
from ziira.modules.command.services import pulse
from ziira.sdk import (
    Recipient,
    Session,
    company_setting,
    flag_for_review,
    recipients_with_permission,
    send_notification,
)

log = logging.getLogger("ziira.command")
FINDINGS_IN_BRIEF = 5


def intel_enabled(session: Session) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'intel' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def company_info(session: Session, company_id: UUID) -> tuple[str, str]:
    row = session.execute(text("select name, base_currency from kernel.company where id = :c"),
                          {"c": str(company_id)}).one()
    return row.name, row.base_currency


def period_for(kind: str, today: date) -> tuple[date, date]:
    """Yesterday for a daily brief; the seven days before today for a weekly one."""
    return (today - timedelta(days=1), today - timedelta(days=1)) if kind == "daily" else (
        today - timedelta(days=7), today - timedelta(days=1))


def build(session: Session, person: Recipient, company_id: UUID, kind: str,
          today: date) -> tuple[Brief, dict[str, Any]]:
    """Compose the brief for a person and company. Nothing is stored or sent."""
    name, currency = company_info(session, company_id)
    date_from, date_to = period_for(kind, today)
    rows = pulse.summarise(session, person.context, company_id, date_from, date_to)
    company_wide = [r for r in rows if r.branch_id is None]
    shown = company_wide or rows
    lines = [PulseLine(r.label, r.kind, r.value, r.previous, r.branch_name if r.branch_id else None) for r in shown]
    findings: list[FindingLine] = []
    more = 0
    if intel_enabled(session):
        from ziira.modules.intel.public import findings_summary, top_findings

        top = top_findings(session, person.context, FINDINGS_IN_BRIEF)
        findings = [FindingLine(f.severity, f.summary, f.recommended_action) for f in top]
        more = max(sum(findings_summary(session, person.context).values()) - len(top), 0)
    brief = compose(business=name, day=today, kind=kind, currency=currency, pulse=lines, findings=findings,
                    more_findings=more)
    data = {"period": [date_from.isoformat(), date_to.isoformat()],
            "figures": [{"metric": r.metric, "value": str(r.value),
                         "branch_id": str(r.branch_id) if r.branch_id else None} for r in shown],
            "findings": [f.summary for f in findings]}
    return brief, data


def deliver(session: Session, person: Recipient, company_id: UUID, kind: str, today: date, channel: str,
            brief: Brief, data: dict[str, Any]) -> UUID | None:
    """Store the brief and send it by the person's channel. Falls back to the app when there is no contact for it."""
    via = "in_app"
    address = person.phone if channel == "sms" else person.email if channel == "email" else None
    brief_id = repo.save_brief(session, person.user_id, company_id, kind, today, brief.subject, brief.body, data, via)
    if brief_id is None:
        return None
    if address:
        queued = send_notification(
            session, company_id=company_id, channel=channel, recipient=address,
            body=brief.short if channel == "sms" else brief.body,
            subject=brief.subject if channel == "email" else None, ref_type="command.brief", ref_id=brief_id,
            dedupe_key=f"brief:{person.user_id}:{company_id}:{kind}:{today}")
        if queued:
            session.execute(text("update command.brief set delivered_via = :v where id = :i"),
                            {"v": channel, "i": str(brief_id)})
    return brief_id


def user_companies(session: Session, person: Recipient) -> list[UUID]:
    allowed = person.context.companies_with(COMMAND_VIEW)
    rows = session.execute(text("select id from kernel.company order by name")).scalars().all()
    return [c for c in rows if allowed is None or c in allowed]


def send_due(session: Session, now: datetime | None = None) -> int:
    """Send every brief that is due: the schedule's time has passed in the company's time zone and it has not been sent
    today. Returns how many were sent. One person's failure does not stop the rest."""
    people = {p.user_id: p for p in recipients_with_permission(session, COMMAND_VIEW)}
    sent = 0
    for schedule in repo.active_schedules(session):
        person = people.get(schedule.user_id)
        if person is None:
            continue
        for company_id in user_companies(session, person):
            zone = ZoneInfo(str(company_setting(session, company_id, "timezone")))
            local = (now or datetime.now(ZoneInfo("UTC"))).astimezone(zone)
            today = local.date()
            if not is_due(now_local=local, send_time=schedule.send_time, kind=schedule.kind, weekday=schedule.weekday,
                          already_sent=repo.brief_exists(session, person.user_id, company_id, schedule.kind, today)):
                continue
            try:
                with session.begin_nested():
                    brief, data = build(session, person, company_id, schedule.kind, today)
                    if deliver(session, person, company_id, schedule.kind, today, schedule.channel, brief, data):
                        sent += 1
            except Exception as error:
                log.exception("Brief for %s could not be sent", person.user_id)
                flag_for_review(session, unit="command", kind="brief_failed", severity="low", company_id=company_id,
                                message=f"A {schedule.kind} brief for {person.full_name} could not be sent: "
                                        f"{error}"[:500],
                                dedupe_key=f"brief-failed:{person.user_id}:{company_id}:{schedule.kind}:{today}")
    return sent
