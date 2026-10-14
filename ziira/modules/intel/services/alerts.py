"""Telling people: urgent findings go to the people whose role covers them, by the channel the business chose.

Nothing is sent unless the business turned a channel on (company setting `intel_alert_channel`). The message is queued,
never sent in the caller's request; opt-outs are honoured by the notification layer.
"""

import logging
from uuid import UUID

from ziira.modules.intel.domain.messages import alert_subject, alert_text
from ziira.modules.intel.domain.rules import at_least
from ziira.modules.intel.permissions import FINDINGS_VIEW
from ziira.modules.intel.repository import findings_repo as repo
from ziira.sdk import Session, company_setting, recipients_with_permission, send_notification

log = logging.getLogger("ziira.intel")


def currency_of(session: Session, company_id: UUID) -> str:
    from sqlalchemy import text

    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar() or "")


def send_alerts(session: Session, company_id: UUID) -> int:
    """Queue alerts for new findings at or above the company's alert severity. Returns how many were alerted."""
    channel = str(company_setting(session, company_id, "intel_alert_channel"))
    if channel == "off":
        return 0
    minimum = str(company_setting(session, company_id, "intel_alert_min_severity"))
    people = recipients_with_permission(session, FINDINGS_VIEW)
    currency = currency_of(session, company_id)
    alerted = 0
    for f in repo.unalerted(session, company_id):
        if not at_least(f.severity, minimum):
            continue
        sent_to = 0
        for person in people:
            address = person.phone if channel == "sms" else person.email
            if not address or not person.covers(FINDINGS_VIEW, f.company_id, f.branch_id):
                continue
            body = alert_text(f.severity, f.summary or "", f.recommended_action, f.amount, currency)
            queued = send_notification(
                session, company_id=company_id, channel=channel, recipient=address, body=body,
                subject=alert_subject(f.severity, f.summary or "") if channel == "email" else None,
                ref_type="intel.finding", ref_id=f.id, dedupe_key=f"intel-alert:{f.id}:{person.user_id}")
            sent_to += 1 if queued else 0
            if queued:
                repo.add_event(session, f.id, "alert_sent", user_id=person.user_id, channel=channel)
        if sent_to:
            repo.mark_alerted(session, f.id)
            alerted += 1
    return alerted
