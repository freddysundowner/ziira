"""A short message to the people who can decide something, through the business's alert channel (the same channel and
rules as alerts: the notification layer respects opt-outs and retries). Used by actions that nudge an approver."""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from ziira.sdk import Session, company_setting, recipients_with_permission, send_notification


@dataclass
class Nudged:
    """Who was messaged now, and who had already been messaged about this today."""

    told: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)


def nudge_people(session: Session, *, company_id: UUID, branch_id: UUID | None, permission: str, text: str,
                 finding_id: UUID, today: date) -> Nudged:
    """Queue `text` to every active person who holds `permission` where the company or branch is. Nothing is queued
    when the business has no alert channel, nobody holds the permission there, or nobody has an address on file. Asking
    twice on the same day queues nothing new."""
    channel = str(company_setting(session, company_id, "intel_alert_channel"))
    out = Nudged()
    if channel not in ("sms", "email"):
        return out
    for person in recipients_with_permission(session, permission):
        if not person.covers(permission, company_id, branch_id):
            continue
        address = person.phone if channel == "sms" else person.email
        if not address:
            continue
        queued = send_notification(
            session, company_id=company_id, channel=channel, recipient=address, body=text[:480],
            subject="A reminder from Ziira" if channel == "email" else None, ref_type="intel.finding",
            ref_id=finding_id, dedupe_key=f"intel-nudge:{finding_id}:{permission}:{person.user_id}:{today}")
        (out.told if queued is not None else out.already).append(person.full_name)
    return out
