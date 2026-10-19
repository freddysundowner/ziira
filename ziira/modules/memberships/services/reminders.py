"""Reminders to customers: a membership about to renew and a package about to expire.

Messages are queued through the notification layer from the recurring task (never in a request), use the shipped
templates in English and Swahili, skip quiet hours (they go out at the next run after) and anyone who asked not to be
contacted (the notification layer enforces that). Each renewal date and each expiry date is reminded once."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from ziira.modules.crm.public import CustomerView
from ziira.modules.memberships.domain.quiet import is_quiet
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, notify
from ziira.sdk import (
    Event,
    Session,
    company_setting,
    format_day,
    publish,
    send_templated,
)

BATCH = 500


def _route(session: Session, company_id: UUID, customer: CustomerView) -> list[tuple[str, str]]:
    """Where to reach the customer, best first (see notify.route)."""
    return notify.route(session, company_id, customer)


def _send(session: Session, company_id: UUID, customer: CustomerView, template: str, variables: dict[str, str],
          language: str, ref_type: str, ref_id: UUID, key: str) -> bool:
    route = _route(session, company_id, customer)
    if not route:
        return False
    (channel, recipient), rest = route[0], route[1:]
    send_templated(session, company_id=company_id, channel=channel, recipient=recipient, template=template,
                   variables=variables, language=language,
                   fallbacks=[{"channel": c, "recipient": r} for c, r in rest], ref_type=ref_type, ref_id=ref_id,
                   dedupe_key=key)
    return True


def send_due(session: Session, company_id: UUID, now: datetime | None = None) -> dict[str, int]:
    """Queue the reminders that are due for a company. Returns how many of each kind were queued."""
    settings = repo.get_settings(session, company_id)
    zone = ZoneInfo(str(company_setting(session, company_id, "timezone")))
    local = (now or datetime.now(UTC)).astimezone(zone)
    today = local.date()
    queued = {"renewals": 0, "packages": 0}
    if is_quiet(local.hour, int(settings["quiet_start"]), int(settings["quiet_end"])):
        return queued
    row = common.one_company(session, company_id)
    currency, business, language = row["base_currency"], row["name"], str(settings["message_language"])
    sending = bool(settings["reminders_enabled"])

    days = int(settings["renewal_reminder_days"])
    if sending and days > 0:
        due = repo.many(session, "select * from memberships.member where company_id = :c and status = 'active' "
                                 "and cancel_at is null and next_renewal_date >= :t and next_renewal_date <= :u "
                                 "and (reminded_for is null or reminded_for <> next_renewal_date) "
                                 "order by next_renewal_date, id limit :n",
                        c=company_id, t=today, u=today + timedelta(days=days), n=BATCH)
        customers = common.customer_names(session, {m["customer_id"] for m in due})
        for member in due:
            customer = customers.get(member["customer_id"])
            if customer is None:
                continue
            sent = _send(session, company_id, customer, "membership_renewal", {
                "customer": customer.name, "plan": member["plan_name"],
                "amount": f"{currency} {Decimal(member['price']):,.2f}", "business": business,
                "date": format_day(member["next_renewal_date"])}, language, "memberships.member", member["id"],
                f"memberships:renewal:{member['id']}:{member['next_renewal_date']}")
            if sent:
                repo.update(session, "member", member["id"], {"reminded_for": member["next_renewal_date"]})
                queued["renewals"] += 1

    days = int(settings["expiry_reminder_days"])
    if days > 0:
        soon = repo.many(session, "select * from memberships.sold_package where company_id = :c and status = 'active' "
                                  "and expires_on >= :t and expires_on <= :u "
                                  "and (expiry_notice_for is null or expiry_notice_for <> expires_on) "
                                  "order by expires_on, id limit :n",
                         c=company_id, t=today, u=today + timedelta(days=days), n=BATCH)
        balance = repo.balances(session, [p["id"] for p in soon])
        customers = common.customer_names(session, {p["customer_id"] for p in soon})
        for sold in soon:
            left = balance[sold["id"]]
            if left <= 0:
                continue
            publish(session, Event("package.expiring", "memberships.sold_package", sold["id"], {
                "company_id": company_id, "branch_id": sold["branch_id"], "customer_id": sold["customer_id"],
                "sold_package_id": sold["id"], "expires_on": sold["expires_on"], "balance": left}))
            repo.update(session, "sold_package", sold["id"], {"expiry_notice_for": sold["expires_on"]})
            customer = customers.get(sold["customer_id"])
            if sending and customer is not None and _send(
                    session, company_id, customer, "package_expiring", {
                        "customer": customer.name, "package": sold["name"], "credits": f"{left:g}",
                        "business": business, "date": format_day(sold["expires_on"])}, language,
                    "memberships.sold_package", sold["id"],
                    f"memberships:expiry:{sold['id']}:{sold['expires_on']}"):
                queued["packages"] += 1
    return queued
