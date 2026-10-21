"""The subscribers directory: every business with its plan, usage, money and history, and the actions on it.

Reads the master database and (through the operator console's one-pass scan) each business's database for counts only;
it never reads a business's records. Deleting a business is deliberate: typed confirmation, refused while the
subscription is live, held for a cooling-off period, then done by the worker, and it leaves a trail
(docs/platform-admin.md).
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import operator_console as console
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.operators import Operator
from ziira.kernel.platform import billing, contacts, entitlements, settings, subscriptions, unit_addons
from ziira.kernel.tenants import drop_tenant

log = logging.getLogger("ziira.subscribers")
SYSTEM = Operator(
    id=UUID(int=0),
    name="system",
    email="",
    session_id=UUID(int=0),
    mfa_verified_at=datetime.fromtimestamp(0, UTC),
    role="superadmin",
)
FLAGS = ("trial_ending", "past_due", "churned", "unmanaged")


def _now() -> datetime:
    return datetime.now(UTC)


def tenant_by_code(code: str) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(
            text("select id, code, name, status, created_at from master.tenant where code = :c"),
            {"c": code.strip().lower()},
        ).first()
    if row is None:
        raise NotFound("No such subscriber")
    return dict(row._mapping)


def _outstanding() -> dict[UUID, dict[str, Decimal]]:
    with master_session() as m:
        rows = m.execute(
            text(
                "select tenant_id, currency, sum(total - amount_paid) as owed from master.billing_invoice "
                "where status = 'issued' and tenant_id is not null and kind <> 'addon' group by tenant_id, currency"
            )
        )
        out: dict[UUID, dict[str, Decimal]] = {}
        for r in rows:
            out.setdefault(r.tenant_id, {})[r.currency.strip()] = r.owed
    return out


def list_subscribers(
    *,
    search: str | None = None,
    status: str | None = None,
    plan: str | None = None,
    edition: str | None = None,
    country: str | None = None,
    flag: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
    scans: list[console.BusinessScan] | None = None,
) -> dict[str, Any]:
    """The directory: filtered rows (newest first) and the total that matched."""
    moment = now or _now()
    if flag is not None and flag not in FLAGS:
        raise ValidationFailed("Flag is one of: " + ", ".join(FLAGS))
    with master_session() as m:
        subs = {r.tenant_id: dict(r._mapping) for r in m.execute(text("select * from master.subscription"))}
    owed = _outstanding()
    needle = (search or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for scan in scans if scans is not None else console.scan_businesses():
        sub = subs.get(scan.id)
        if needle and needle not in scan.name.lower() and needle not in scan.code.lower():
            continue
        state = sub["status"] if sub else "unmanaged"
        if status and state != status:
            continue
        if plan and (sub is None or sub["plan_code"] != plan):
            continue
        if edition and scan.edition != edition:
            continue
        if country and (scan.country or "").upper() != country.upper():
            continue
        if flag == "trial_ending" and not (
            sub and sub["status"] == "trialing" and sub["trial_end"] and sub["trial_end"] <= moment + timedelta(days=7)
        ):
            continue
        if flag == "past_due" and state not in ("past_due", "grace", "suspended"):
            continue
        if flag == "churned" and state not in ("cancelled", "expired"):
            continue
        if flag == "unmanaged" and sub is not None:
            continue
        rows.append(_row(scan, sub, owed.get(scan.id, {})))
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"total": len(rows), "items": rows[offset : offset + limit]}


def _row(scan: console.BusinessScan, sub: dict[str, Any] | None, owed: dict[str, Decimal]) -> dict[str, Any]:
    ent = entitlements.for_tenant(scan.id, use_cache=False)
    return {
        "id": scan.id,
        "code": scan.code,
        "name": scan.name,
        "tenant_status": scan.status,
        "created_at": scan.created_at,
        "edition": scan.edition,
        "country": scan.country,
        "status": sub["status"] if sub else "unmanaged",
        "plan_code": sub["plan_code"] if sub else None,
        "plan_name": sub["plan_name"] if sub else None,
        "interval": sub["interval"] if sub else None,
        "currency": sub["currency"] if sub else None,
        "unit_amount": sub["unit_amount"] if sub else None,
        "period_end": sub["period_end"] if sub else None,
        "trial_end": sub["trial_end"] if sub else None,
        "cancel_at_period_end": bool(sub and sub["cancel_at_period_end"]),
        "is_comp": bool(sub and sub["is_comp"]),
        "tags": list(sub["tags"]) if sub else [],
        "users": scan.users,
        "max_users": ent.max_users,
        "branches": scan.branches,
        "max_branches": ent.max_branches,
        "last_activity": scan.last_activity,
        "outstanding": {k: v for k, v in owed.items() if v > 0},
    }


def detail(operator: Operator, code: str) -> dict[str, Any]:
    """One subscriber in full."""
    tenant = tenant_by_code(code)
    tenant_id: UUID = tenant["id"]
    scan = console.scan_business(tenant["code"])
    if scan is None:
        raise NotFound("No such subscriber")
    sub = subscriptions.get(tenant_id)
    ent = entitlements.for_tenant(tenant_id, use_cache=False)
    business = console.business_detail(operator, code)
    with master_session() as m:
        payments = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select p.id, p.invoice_id, i.number as invoice_number, p.method, p.reference, p.amount, "
                    "p.currency, "
                    "p.paid_on, p.recorded_by, p.reversed_at from master.billing_payment p join "
                    "master.billing_invoice i "
                    "on i.id = p.invoice_id where p.tenant_id = :t order by p.created_at desc limit 50"
                ),
                {"t": str(tenant_id)},
            )
        ]
        trail = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select id, occurred_at, operator_name, action, target, outcome, reason, detail from "
                    "master.operator_action_log where target = :c or target like :p order by id desc limit 100"
                ),
                {"c": tenant["code"], "p": tenant["code"] + ":%"},
            )
        ]
        deletion = m.execute(
            text(
                "select requested_at, requested_by, execute_after, reason from master.subscriber_deletion "
                "where tenant_id = :t and cancelled_at is null and executed_at is null"
            ),
            {"t": str(tenant_id)},
        ).first()
    return {
        **_row(scan, sub, _outstanding().get(tenant_id, {})),
        "owners": contacts.owner_contacts(tenant_id),
        "subscription": sub,
        "timeline": subscriptions.timeline(tenant_id),
        "invoices": billing.list_invoices(tenant_id=tenant_id),
        "payments": payments,
        "requests": billing.list_requests(tenant_id=tenant_id),
        "addons": unit_addons.list_for_tenant(tenant_id),
        "usage": {
            "users": scan.users,
            "branches": scan.branches,
            "companies": scan.companies,
            "storage_bytes": scan.storage_bytes,
            "failed_jobs": scan.failed_jobs,
        },
        "limits": {"users": ent.max_users, "branches": ent.max_branches, "companies": ent.max_companies},
        "units": business["units"],
        "grants": business["grants"],
        "sessions": business["sessions"],
        "audit_trail": trail,
        "deletion": dict(deletion._mapping) if deletion else None,
        "access": ent.access,
        "message": ent.message,
    }


# --------------------------------------------------------------------------- export of the platform's records
def export_records(code: str) -> dict[str, Any]:
    """What the platform itself holds about a subscriber (not the business's own data, which `ziira backup --tenant
    CODE`
    or the business's own exports cover): the subscription and its history, invoices, payments, requests, contacts."""
    tenant = tenant_by_code(code)
    tenant_id: UUID = tenant["id"]
    with master_session() as m:
        payments = [
            dict(r._mapping)
            for r in m.execute(
                text("select * from master.billing_payment where tenant_id = :t order by created_at"),
                {"t": str(tenant_id)},
            )
        ]
    return {
        "exported_at": _now().isoformat(),
        "business": {k: tenant[k] for k in ("code", "name", "status", "created_at")},
        "owners": contacts.owner_contacts(tenant_id),
        "subscription": subscriptions.get(tenant_id),
        "timeline": subscriptions.timeline(tenant_id, 1000),
        "invoices": billing.list_invoices(tenant_id=tenant_id),
        "payments": payments,
        "plan_requests": billing.list_requests(tenant_id=tenant_id),
    }


# --------------------------------------------------------------------------- personal data held by the platform
def find_contact(email: str) -> dict[str, Any]:
    """Where a person's email appears in the platform's own records (invoice bill-to details, registrations)."""
    address = email.strip().lower()
    if "@" not in address:
        raise ValidationFailed("Give an email address")
    with master_session() as m:
        invoices = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select id, number, bill_to, status, total, currency, issue_date from master.billing_invoice "
                    "where lower(bill_to->>'email') = :e order by created_at"
                ),
                {"e": address},
            )
        ]
        registrations = m.execute(
            text("select count(*) from master.registration where lower(email) = :e"), {"e": address}
        ).scalar_one()
    return {"email": address, "invoices": invoices, "registrations": int(registrations)}


def erase_contact(email: str) -> dict[str, int]:
    """Remove a person's contact details from the platform's records. Invoices must be kept (tax and accounting), so
    only the person's name and email on them are replaced; the business and the money stay. Registrations are
    deleted."""
    address = email.strip().lower()
    if "@" not in address:
        raise ValidationFailed("Give an email address")
    with master_session() as m:
        changed = m.execute(
            text(
                "update master.billing_invoice set bill_to = bill_to || cast(:b as jsonb) where "
                "lower(bill_to->>'email') = :e "
                "returning id"
            ),
            {"e": address, "b": json.dumps({"contact": "[erased]", "email": ""})},
        ).all()
        removed = m.execute(
            text("delete from master.registration where lower(email) = :e returning id"), {"e": address}
        ).all()
    return {"invoices_anonymised": len(changed), "registrations_deleted": len(removed)}


# --------------------------------------------------------------------------- deleting a business
def request_deletion(
    operator: Operator, code: str, confirm: str, reason: str, *, early: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    """Schedule a business for deletion after the cooling-off period. Refused while its subscription is live, before the
    retention window after it ended (unless `early`, which the operator must justify), and unless the code is typed."""
    moment = now or _now()
    tenant = tenant_by_code(code)
    if confirm.strip() != tenant["code"]:
        raise ValidationFailed(f"Type the business's code '{tenant['code']}' to confirm")
    if len(reason.strip()) < 10:
        raise ValidationFailed("Say why in a sentence: it is kept in the trail")
    sub = subscriptions.get(tenant["id"])
    if sub is not None:
        if sub["status"] in subscriptions.LIVE:
            raise Conflict("This business has a live subscription: cancel it first")
        keep = timedelta(days=int(settings.get("billing.retention_days")))
        if not early and moment < sub["status_changed_at"] + keep:
            raise Conflict(
                f"The data is kept until {sub['status_changed_at'] + keep:%Y-%m-%d} (the retention period "
                "after a subscription ends). Use 'early' only for a request from the business itself."
            )
    after = moment + timedelta(days=int(settings.get("billing.cooling_off_days")))
    with master_session() as m:
        if m.execute(
            text(
                "select 1 from master.subscriber_deletion where tenant_id = :t and cancelled_at is null "
                "and executed_at is null"
            ),
            {"t": str(tenant["id"])},
        ).first():
            raise Conflict("A deletion is already scheduled for this business")
        m.execute(
            text(
                "insert into master.subscriber_deletion (tenant_id, tenant_code, requested_by, execute_after, "
                "reason) values (:t, :c, :b, :a, :r)"
            ),
            {"t": str(tenant["id"]), "c": tenant["code"], "b": operator.name, "a": after, "r": reason.strip()},
        )
    return {"code": tenant["code"], "execute_after": after}


def cancel_deletion(code: str) -> None:
    tenant = tenant_by_code(code)
    with master_session() as m:
        done = m.execute(
            text(
                "update master.subscriber_deletion set cancelled_at = now() where tenant_id = :t and "
                "cancelled_at is null and executed_at is null returning id"
            ),
            {"t": str(tenant["id"])},
        ).first()
    if done is None:
        raise NotFound("No deletion is scheduled for this business")


def run_due_deletions(*, now: datetime | None = None) -> int:
    """Carry out deletions whose cooling-off ended (the worker calls this). A business that came back to life
    meanwhile is
    left alone and the request is cancelled."""
    moment = now or _now()
    with master_session() as m:
        due = list(
            m.execute(
                text(
                    "select id, tenant_id, tenant_code, reason from master.subscriber_deletion where "
                    "cancelled_at is null and executed_at is null and execute_after <= :n"
                ),
                {"n": moment},
            )
        )
    done = 0
    for row in due:
        sub = subscriptions.get(row.tenant_id)
        if sub is not None and sub["status"] in subscriptions.LIVE:
            with master_session() as m:
                m.execute(
                    text("update master.subscriber_deletion set cancelled_at = now() where id = :i"), {"i": str(row.id)}
                )
            console.log_action(
                SYSTEM,
                "subscriber.delete_cancelled",
                target=row.tenant_code,
                detail={"why": "subscription became live again"},
            )
            continue
        try:
            drop_tenant(row.tenant_id)
        except Exception:  # noqa: BLE001
            log.exception("Could not delete business %s", row.tenant_code)
            continue
        with master_session() as m:
            m.execute(
                text("update master.subscriber_deletion set executed_at = now() where id = :i"), {"i": str(row.id)}
            )
        console.log_action(SYSTEM, "subscriber.deleted", target=row.tenant_code, reason=row.reason)
        done += 1
    return done
