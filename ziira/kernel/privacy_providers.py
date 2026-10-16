"""The kernel's own personal data: the people who sign in (users) and the messages sent to people (notifications).

Both plug into "kernel.personal_data" like any unit does (see personal_data.py).
"""

import re
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import directory, notifications
from ziira.kernel.context import get_context
from ziira.kernel.db import master_session
from ziira.kernel.extensions import provides
from ziira.kernel.personal_data import (
    PERSONAL_DATA,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Subject,
    sql_phone_matches,
)

REDACTED_BODY = "[removed after retention period]"
ERASED_BODY = "[erased on request]"
PLACEHOLDER_USER = "Erased user"
DIGITS = "regexp_replace({col}, '[^0-9]', '', 'g')"


def _row_json(session: Session, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r[0]) for r in session.execute(text(sql), params)]


# --------------------------------------------------------------------------- users
@provides(PERSONAL_DATA)
class UserData(PersonalDataProvider):
    """The people who sign in: name, email, phone, devices. Their sign-in is closed when they are anonymised."""

    name = "kernel.users"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        if subject.email:
            rows = session.execute(text("select id, full_name from kernel.app_user where lower(email) = :e"),
                                   {"e": subject.email})
            found.update({r.id: PersonalRecord(self.name, "user", r.id, r.full_name, "exact") for r in rows})
        for phone in {p for p in (subject.phone, subject.identifier) if p and p.isdigit()}:
            rows = session.execute(text(
                f"select id, full_name from kernel.app_user where {sql_phone_matches('phone', 'p')}"), {"p": phone})
            found.update({r.id: PersonalRecord(self.name, "user", r.id, r.full_name, "exact") for r in rows})
        if subject.name:
            rows = session.execute(text(
                "select id, full_name from kernel.app_user where full_name ilike :n and full_name <> :ph"),
                {"n": f"%{_like(subject.name)}%", "ph": PLACEHOLDER_USER})
            for r in rows:
                found.setdefault(r.id, PersonalRecord(self.name, "user", r.id, r.full_name, "possible"))
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        profile = _row_json(session, "select to_jsonb(u) - 'password_hash' - 'tenant_id' - 'created_by' - 'updated_by' "
                                     "from kernel.app_user u where id = :i", i=str(record.record_id))
        return {
            "profile": profile[0] if profile else None,
            "phones": _row_json(session, "select to_jsonb(p) - 'tenant_id' - 'created_by' - 'updated_by' "
                                         "from kernel.user_phone p where user_id = :i", i=str(record.record_id)),
            "roles": _row_json(session, "select jsonb_build_object('role', r.name, 'scope', ur.scope, "
                                        "'company_id', ur.company_id, 'branch_id', ur.branch_id) "
                                        "from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
                                        "where ur.user_id = :i", i=str(record.record_id)),
            "sign_in_devices": _row_json(
                session, "select jsonb_build_object('channel', channel, 'device_id', device_id, "
                         "'device_name', device_name, 'signed_in_at', created_at, 'last_used_at', last_used_at, "
                         "'revoked_at', revoked_at) from kernel.user_session where user_id = :i order by created_at",
                i=str(record.record_id)),
        }

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        ctx = get_context()
        user = session.execute(text("select id, email, phone, status from kernel.app_user where id = :i for update"),
                               {"i": str(record.record_id)}).first()
        if user is None:
            return Outcome("refused", message="The user no longer exists")
        if ctx.user_id == user.id:
            return Outcome("refused", message="You cannot erase the account you are signed in with: ask another "
                                              "person with the permission")
        is_owner = session.execute(text(
            "select 1 from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
            "where ur.user_id = :u and r.is_system and r.name = 'Owner' and ur.scope = 'tenant'"),
            {"u": str(user.id)}).first()
        if is_owner and user.status == "active":
            others = session.execute(text(
                "select count(*) from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
                "join kernel.app_user u on u.id = ur.user_id where r.is_system and r.name = 'Owner' "
                "and ur.scope = 'tenant' and u.status = 'active' and u.id <> :u"), {"u": str(user.id)}).scalar_one()
            if others < 1:
                return Outcome("refused", message="This is the business's only owner. Make someone else an owner "
                                                  "first, then erase this account")
        logins = [x for x in (user.email, user.phone) if x]
        session.execute(text(
            "update kernel.app_user set full_name = :n, email = null, phone = null, password_hash = null, "
            "status = 'disabled', mfa_enabled = false, updated_at = now() where id = :i"),
            {"n": PLACEHOLDER_USER, "i": str(user.id)})
        session.execute(text("delete from kernel.user_phone where user_id = :i"), {"i": str(user.id)})
        if session.execute(text("select to_regclass('kernel.user_mfa')")).scalar_one() is not None:
            session.execute(text("delete from kernel.user_mfa where user_id = :i"), {"i": str(user.id)})
        session.execute(text(
            "update kernel.user_session set revoked_at = coalesce(revoked_at, now()), device_name = null, "
            "device_id = 'erased' where user_id = :i"), {"i": str(user.id)})
        if logins:
            with master_session() as master:
                for login in logins:
                    master.execute(text("delete from master.login_directory where tenant_id = :t "
                                        "and identifier_hash = :h"),
                                   {"t": str(ctx.tenant_id), "h": directory.hash_login(login)})
        return Outcome(
            "anonymised",
            changed=["name replaced", "email removed", "phone removed", "password removed (the account can no longer "
                     "sign in)", "authenticator secret removed", "sign-in devices closed and their names removed"],
            kept=[Kept("the user's id on records they created or approved",
                       "documents and the audit trail say who acted by id only; the id no longer names anyone"),
                  Kept("audit trail entries", "the audit log is immutable and kept for the retention period; it "
                                              "records ids, and the email or phone typed when the account was made")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("kernel", "users", "Name, email, phone and sign-in devices of people who sign in",
                              "Needed to let them work, and to show who did what", period="while the account exists",
                              at_end="review"),
                RetentionRule("kernel", "audit", "The audit trail (who did what, when, from which device and address)",
                              "Accountability and the business's record-keeping duties; immutable by design",
                              setting="retention_audit_years", period="the business's stated period", at_end="keep")]


def _like(value: str) -> str:
    return re.sub(r"([\\%_])", r"\\\1", value)


# --------------------------------------------------------------------------- notifications
@provides(PERSONAL_DATA)
class NotificationData(PersonalDataProvider):
    """The messages sent to a person (email, SMS): who they went to and what they said."""

    name = "kernel.notifications"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        recipients: set[str] = set()
        if subject.email:
            rows = session.execute(text(
                "select distinct recipient from kernel.notification where company_id = :c and redacted_at is null "
                "and lower(recipient) = :e"), {"c": str(company_id), "e": subject.email})
            recipients.update(r.recipient for r in rows)
        for digits in {p for p in (subject.phone, subject.identifier) if p and p.isdigit()}:
            rows = session.execute(text(
                "select distinct recipient from kernel.notification where company_id = :c and redacted_at is null "
                f"and recipient not like '%@%' and {DIGITS.format(col='recipient')} = :p"),
                {"c": str(company_id), "p": digits})
            recipients.update(r.recipient for r in rows)
        found = []
        for recipient in sorted(recipients):
            count = session.execute(text(
                "select count(*) from kernel.notification where company_id = :c and recipient = :r "
                "and redacted_at is null"), {"c": str(company_id), "r": recipient}).scalar_one()
            key = uuid.uuid5(uuid.NAMESPACE_URL, f"{company_id}:{recipient}")
            found.append(PersonalRecord(self.name, "message_history", key,
                                        f"{count} message(s) to {notifications.mask(recipient)}", "exact", company_id,
                                        ref=recipient))
        return found

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        rows = session.execute(text(
            "select created_at, channel, recipient, subject, body, status, sent_at, error from kernel.notification "
            "where company_id = :c and recipient = :r and redacted_at is null order by created_at"),
            {"c": str(record.company_id), "r": record.ref})
        return {"messages": [{"queued_at": r.created_at, "channel": r.channel, "to": r.recipient,
                              "subject": r.subject, "text": r.body, "status": r.status, "sent_at": r.sent_at,
                              "error": r.error} for r in rows]}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        # A message still waiting is cancelled first: it could not be delivered to a masked address.
        session.execute(text(
            "update kernel.notification set status = 'skipped', error = 'The recipient was erased' "
            "where company_id = :c and recipient = :r and status = 'queued' and redacted_at is null"),
            {"c": str(record.company_id), "r": record.ref})
        assert record.company_id is not None
        count = redact_recipient(session, record.company_id, record.ref, ERASED_BODY)
        kept = [Kept("the fact that messages were sent (date, channel, status, document reference)",
                     "a record of what the business sent; it names nobody once the recipient is masked")]
        opted_out = session.execute(text(
            "select 1 from kernel.notification_optout where company_id = :c and recipient = :r"),
            {"c": str(record.company_id), "r": record.ref}).first()
        if opted_out:
            kept.append(Kept("the do-not-contact entry for this address",
                             "keeping it is how the business makes sure the person is never messaged again"))
        return Outcome("anonymised", changed=[f"{count} message(s): recipient masked, subject and text removed"],
                       kept=kept)

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        days = int(session.execute(text(
            "select coalesce((settings->>'retention_notifications_days')::int, 0) from kernel.company "
            "where id = :c"), {"c": str(company_id)}).scalar_one())
        eligible = 0
        if days > 0:
            eligible = session.execute(text(
                "select count(*) from kernel.notification where company_id = :c and redacted_at is null "
                "and recipient is not null and status <> 'queued' "
                "and created_at < now() - make_interval(days => :d)"), {"c": str(company_id), "d": days}).scalar_one()
        return [RetentionRule("kernel", "notifications", "Who each message went to and what it said",
                              "Proof of what was sent to customers and suppliers",
                              setting="retention_notifications_days",
                              period=f"{days} days" if days else "indefinitely (no period set)",
                              at_end="mask" if days else "keep", eligible=int(eligible))]


def redact_recipient(session: Session, company_id: UUID, recipient: str, body: str,
                     older_than_days: int | None = None) -> int:
    """Mask one recipient's notifications: the address is masked and the subject and text replaced (the one change a
    notification allows). With `older_than_days` only finished messages older than that are changed. Returns the
    number changed."""
    older = "" if older_than_days is None else (" and status <> 'queued' "
                                                "and created_at < now() - make_interval(days => :d)")
    result = session.execute(text(
        "update kernel.notification set recipient = :mask, "
        "subject = case when subject is null then null else :body end, body = :body, payload = '{}', "
        "redacted_at = now() "
        "where company_id = :c and recipient = :r and redacted_at is null" + older),
        {"mask": notifications.mask(recipient), "body": body, "c": str(company_id), "r": recipient,
         "d": older_than_days})
    return int(result.rowcount)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- webhook deliveries
@provides(PERSONAL_DATA)
class WebhookDeliveryData(PersonalDataProvider):
    """What outgoing webhooks sent while their content is still kept. Payloads carry ids and figures, not names, phone
    numbers or emails (docs/webhooks.md), so this finds a person only where an id or code they gave appears in one."""

    name = "kernel.webhooks"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        terms = [t for t in (subject.email, subject.identifier) if t]
        if not terms:
            return []
        count = session.execute(text(
            "select count(*) from kernel.webhook_delivery where body is not null and body ilike any(:p) "
            "and body like :c"), {"p": [f"%{_like(t)}%" for t in terms], "c": f"%{company_id}%"}).scalar_one()
        if not count:
            return []
        key = uuid.uuid5(uuid.NAMESPACE_URL, f"webhooks:{company_id}:{'|'.join(terms)}")
        return [PersonalRecord(self.name, "webhook_deliveries", key, f"{count} webhook delivery(ies) mentioning it",
                               "exact", company_id, ref="|".join(terms))]

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        rows = session.execute(text(
            "select created_at, event_type, status, body_preview from kernel.webhook_delivery "
            "where body is not null and body ilike any(:p) and body like :c order by created_at"),
            {"p": [f"%{_like(t)}%" for t in record.ref.split("|")], "c": f"%{record.company_id}%"})
        return {"deliveries": [{"at": r.created_at, "event": r.event_type, "status": r.status,
                                "first_bytes": r.body_preview} for r in rows]}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        count = session.execute(text(
            "update kernel.webhook_delivery set body = null, body_preview = :b "
            "where body is not null and body ilike any(:p) and body like :c"),
            {"b": ERASED_BODY, "p": [f"%{_like(t)}%" for t in record.ref.split("|")],
             "c": f"%{record.company_id}%"}).rowcount  # type: ignore[attr-defined]
        return Outcome("anonymised", changed=[f"{count} webhook delivery(ies): content removed (they cannot be sent "
                                              "again)"],
                       kept=[Kept("the fact that a delivery happened (time, event type, result, the content's hash)",
                                  "a log of what was sent to the business's own systems; it names nobody")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("kernel", "webhooks", "The content of outgoing webhook deliveries (ids and figures)",
                              "Needed to retry a failed delivery and to send it again on request",
                              period="a few days, then only the hash and first bytes remain", at_end="mask")]


# --------------------------------------------------------------------------- subscription payments (master database)
@provides(PERSONAL_DATA)
class PaymentPayerData(PersonalDataProvider):
    """The payer details kept on the business's subscription payment attempts (the vendor's billing records): the last
    four digits of the payer's phone number, a keyed hash of it, and the receipt email. The number is not kept."""

    name = "kernel.payment_payers"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        from ziira.kernel.platform.payments import phone_hash

        tenant_id = session.execute(text("select kernel.current_tenant()")).scalar_one()
        hashes = [phone_hash(p) for p in {x for x in (subject.phone, subject.identifier) if x and x.isdigit()}]
        with master_session() as master:
            rows = master.execute(text(
                "select id, provider, amount, currency, created_at from master.payment_attempt where tenant_id = :t "
                "and ((payer_phone_hash = any(:h)) or (cast(:e as text) is not null and lower(payer_email) = :e))"),
                {"t": str(tenant_id), "h": hashes, "e": subject.email}).all()
        return [PersonalRecord(self.name, "payment_attempt", r.id,
                               f"Payment attempt of {r.amount} {str(r.currency).strip()} on {r.created_at:%Y-%m-%d}",
                               "exact", company_id) for r in rows]

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        with master_session() as master:
            r = master.execute(text(
                "select provider, amount, currency, status, payer_phone_last4, payer_email, payment_reference, "
                "created_at from master.payment_attempt where id = :i"), {"i": str(record.record_id)}).first()
        return dict(r._mapping) if r else {}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        with master_session() as master:
            master.execute(text(
                "update master.payment_attempt set payer_phone_last4 = null, payer_phone_hash = null, "
                "payer_email = null where id = :i"), {"i": str(record.record_id)})
        return Outcome("anonymised", changed=["phone digits, phone hash and receipt email removed"],
                       kept=[Kept("the payment record (amount, date, invoice, provider reference)",
                                  "the vendor's billing and tax records must be kept")])
