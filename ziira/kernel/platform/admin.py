"""Super Admin actions: each platform service wrapped so that it needs a fresh second-factor code, leaves a line in the
operator trail (whether it worked or was refused) and, for a subscriber, is filed under that subscriber's code.

The routes call these; the services in this package never know who the operator is.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import operator_console as console
from ziira.kernel import operators
from ziira.kernel.db import master_session
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.operators import Operator
from ziira.kernel.platform import billing, licences, plans, settings, subscribers, subscriptions


def act[T](
    operator: Operator,
    action: str,
    target: str | None,
    ip: str | None,
    work: Callable[[], T],
    *,
    summary: Callable[[T], dict[str, Any]] | None = None,
    reason: str | None = None,
) -> T:
    """Run `work` as a logged change; the trail keeps `summary(result)` (never the whole result)."""
    box: list[T] = []

    def run() -> dict[str, Any]:
        box.append(work())
        return summary(box[0]) if summary else {}

    console._change(operator, action, target or "", ip, run, reason=reason)
    return box[0]


def _tenant(code: str) -> dict[str, Any]:
    return subscribers.tenant_by_code(code)


def _name(op: Operator) -> str:
    return op.name


# --------------------------------------------------------------------------- settings
def set_setting(op: Operator, key: str, value: Any, ip: str | None) -> Any:
    return act(
        op,
        "platform.setting",
        key,
        ip,
        lambda: settings.set_value(key, value, _name(op)),
        summary=lambda _: {"key": key},
    )


# --------------------------------------------------------------------------- plans, add-ons, coupons
def plan_detail(code: str) -> dict[str, Any]:
    plan = plans.get_plan(code)
    return {
        **plan,
        "units_included": plans.plan_units(plan),
        "prices": plans.price_history("plan", plan["id"]),
        "current_prices": [vars(p) for p in plans.current_prices("plan", plan["id"])],
    }


def create_plan(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    out = act(
        op,
        "plan.create",
        str(data.get("code")),
        ip,
        lambda: plans.create_plan(data),
        summary=lambda r: {"code": r["code"]},
    )
    plans.invalidate_public_cache()
    return plan_detail(out["code"])


def update_plan(op: Operator, code: str, changes: dict[str, Any], ip: str | None) -> dict[str, Any]:
    act(
        op,
        "plan.update",
        code,
        ip,
        lambda: plans.update_plan(code, changes),
        summary=lambda _: {"fields": sorted(changes)},
    )
    plans.invalidate_public_cache()
    return plan_detail(code)


def set_plan_price(op: Operator, code: str, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    plan = plans.get_plan(code)
    act(
        op,
        "plan.price",
        code,
        ip,
        lambda: plans.set_price("plan", plan["id"], by=_name(op), **data),
        summary=lambda r: {
            "currency": r["currency"],
            "interval": r["interval"],
            "amount": r["amount"],
            "withdrawn": r["withdrawn"],
            "effective_from": r["effective_from"],
        },
    )
    plans.invalidate_public_cache()
    return plan_detail(code)


def remove_plan_price(op: Operator, code: str, price_id: UUID, ip: str | None) -> dict[str, Any]:
    act(op, "plan.price_remove", code, ip, lambda: plans.remove_scheduled_price("plan", price_id))
    plans.invalidate_public_cache()
    return plan_detail(code)


def create_addon(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    out = act(
        op,
        "addon.create",
        str(data.get("code")),
        ip,
        lambda: plans.create_addon(data),
        summary=lambda r: {"code": r["code"]},
    )
    plans.invalidate_public_cache()
    return addon_detail(out["code"])


def addon_detail(code: str) -> dict[str, Any]:
    addon = plans.get_addon(code)
    return {
        **addon,
        "prices": plans.price_history("addon", addon["id"]),
        "current_prices": [vars(p) for p in plans.current_prices("addon", addon["id"])],
    }


def update_addon(op: Operator, code: str, changes: dict[str, Any], ip: str | None) -> dict[str, Any]:
    act(
        op,
        "addon.update",
        code,
        ip,
        lambda: plans.update_addon(code, changes),
        summary=lambda _: {"fields": sorted(changes)},
    )
    plans.invalidate_public_cache()
    return addon_detail(code)


def set_addon_price(op: Operator, code: str, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    addon = plans.get_addon(code)
    act(
        op,
        "addon.price",
        code,
        ip,
        lambda: plans.set_price("addon", addon["id"], by=_name(op), **data),
        summary=lambda r: {"currency": r["currency"], "interval": r["interval"], "amount": r["amount"]},
    )
    plans.invalidate_public_cache()
    return addon_detail(code)


def remove_addon_price(op: Operator, code: str, price_id: UUID, ip: str | None) -> dict[str, Any]:
    act(op, "addon.price_remove", code, ip, lambda: plans.remove_scheduled_price("addon", price_id))
    plans.invalidate_public_cache()
    return addon_detail(code)


def create_coupon(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "coupon.create",
        str(data.get("code")),
        ip,
        lambda: plans.create_coupon(data),
        summary=lambda r: {"code": r["code"]},
    )


def set_coupon_status(op: Operator, code: str, status: str, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "coupon.status",
        code,
        ip,
        lambda: plans.set_coupon_status(code, status),
        summary=lambda r: {"status": r["status"]},
    )


# --------------------------------------------------------------------------- subscribers
def _sub_act[T](
    op: Operator,
    action: str,
    code: str,
    ip: str | None,
    work: Callable[[UUID], T],
    *,
    reason: str | None = None,
    summary: Callable[[T], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tenant = _tenant(code)
    act(op, action, tenant["code"], ip, lambda: work(tenant["id"]), reason=reason, summary=summary)
    return subscribers.detail(op, tenant["code"])


def start_subscription(op: Operator, code: str, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.start",
        code,
        ip,
        lambda t: subscriptions.start(
            t,
            data["plan_code"],
            currency=data.get("currency"),
            interval=data.get("interval"),
            mode=data.get("mode", "trial"),
            comp_until=data.get("comp_until"),
            by=_name(op),
        ),
        summary=lambda r: {"plan": r["plan_code"], "status": r["status"]},
    )


def change_plan(op: Operator, code: str, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    def work(tenant_id: UUID) -> dict[str, Any]:
        res = subscriptions.change_plan(
            tenant_id,
            data["plan_code"],
            interval=data.get("interval"),
            currency=data.get("currency"),
            effective=data.get("effective", "auto"),
            by=_name(op),
        )
        if data.get("bill_prorated", True) and res["prorated_due"] > 0:
            sub = res["subscription"]
            billing.create_invoice(
                tenant_id=tenant_id,
                currency=sub["currency"],
                kind="upgrade",
                tax_inclusive=sub["tax_inclusive"],
                lines=[
                    {
                        "description": f"Upgrade to {sub['plan_name']}: rest of period to "
                        f"{sub['period_end']:%Y-%m-%d}, pro rata",
                        "quantity": 1,
                        "unit_amount": res["prorated_due"],
                    }
                ],
                created_by=_name(op),
                issue=True,
            )
        return res

    return _sub_act(
        op,
        "subscription.change_plan",
        code,
        ip,
        work,
        summary=lambda r: {
            "plan": data["plan_code"],
            "effective": r["effective"],
            "prorated_due": r["prorated_due"],
            "disabled_units": r["disabled_units"],
        },
    )


def extend_trial(op: Operator, code: str, days: int, ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.extend_trial",
        code,
        ip,
        lambda t: subscriptions.extend_trial(t, days, by=_name(op)),
        summary=lambda r: {"days": days, "trial_end": r["trial_end"]},
    )


def comp(op: Operator, code: str, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.comp",
        code,
        ip,
        lambda t: subscriptions.make_comp(
            t, data.get("plan_code"), until=data.get("until"), reason=data["reason"], by=_name(op)
        ),
        reason=data["reason"],
        summary=lambda r: {"until": r["period_end"]},
    )


def apply_coupon(op: Operator, code: str, coupon: str, ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.coupon",
        code,
        ip,
        lambda t: subscriptions.apply_coupon(t, coupon, by=_name(op)),
        summary=lambda _: {"coupon": coupon},
    )


def suspend(op: Operator, code: str, reason: str, ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op, "subscription.suspend", code, ip, lambda t: subscriptions.suspend(t, reason, by=_name(op)), reason=reason
    )


def reactivate(op: Operator, code: str, reason: str | None, ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.reactivate",
        code,
        ip,
        lambda t: subscriptions.reactivate(t, reason=reason, by=_name(op)),
        reason=reason,
    )


def cancel(op: Operator, code: str, at_period_end: bool, reason: str | None, ip: str | None) -> dict[str, Any]:
    return _sub_act(
        op,
        "subscription.cancel",
        code,
        ip,
        lambda t: subscriptions.cancel(t, at_period_end=at_period_end, reason=reason, by=_name(op)),
        reason=reason,
        summary=lambda r: {"at_period_end": at_period_end, "status": r["status"]},
    )


def uncancel(op: Operator, code: str, ip: str | None) -> dict[str, Any]:
    return _sub_act(op, "subscription.uncancel", code, ip, lambda t: subscriptions.uncancel(t, by=_name(op)))


def sync_plan(op: Operator, code: str, ip: str | None) -> dict[str, Any]:
    return _sub_act(op, "subscription.sync_plan", code, ip, lambda t: subscriptions.sync_to_plan(t, by=_name(op)))


def set_notes(op: Operator, code: str, notes: str | None, tags: list[str] | None, ip: str | None) -> dict[str, Any]:
    return _sub_act(op, "subscriber.notes", code, ip, lambda t: subscriptions.set_notes(t, notes, tags, _name(op)))


def request_deletion(op: Operator, code: str, confirm: str, reason: str, early: bool, ip: str | None) -> dict[str, Any]:
    act(
        op,
        "subscriber.delete_request",
        code,
        ip,
        lambda: subscribers.request_deletion(op, code, confirm, reason, early=early),
        reason=reason,
        summary=lambda r: {"execute_after": r["execute_after"], "early": early},
    )
    return subscribers.detail(op, code)


def cancel_deletion(op: Operator, code: str, ip: str | None) -> dict[str, Any]:
    act(op, "subscriber.delete_cancel", code, ip, lambda: subscribers.cancel_deletion(code))
    return subscribers.detail(op, code)


def erase_contact(op: Operator, email: str, ip: str | None) -> dict[str, int]:
    result: dict[str, int] = act(
        op, "privacy.erase_contact", "", ip, lambda: subscribers.erase_contact(email), summary=lambda r: dict(r)
    )
    return result


# --------------------------------------------------------------------------- invoices and payments
def create_invoice(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    target = data.get("tenant_code") or str(data.get("licence_id"))

    def work() -> dict[str, Any]:
        tenant_id = _tenant(data["tenant_code"])["id"] if data.get("tenant_code") else None
        sub = subscriptions.get(tenant_id) if tenant_id else None
        currency = data.get("currency") or (sub["currency"] if sub else None)
        if not currency:
            raise ValidationFailed("Give the invoice's currency")
        return billing.create_invoice(
            tenant_id=tenant_id,
            licence_id=data.get("licence_id"),
            currency=currency,
            lines=data["lines"],
            kind="licence" if data.get("licence_id") else "manual",
            tax_inclusive=bool(data.get("tax_inclusive")),
            notes=data.get("notes", ""),
            due_date=data.get("due_date"),
            created_by=_name(op),
            issue=bool(data.get("issue")),
        )

    return act(
        op,
        "invoice.create",
        target,
        ip,
        work,
        summary=lambda r: {"id": r["id"], "number": r["number"], "total": r["total"]},
    )


def update_draft(op: Operator, invoice_id: UUID, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return act(op, "invoice.update", str(invoice_id), ip, lambda: billing.update_draft(invoice_id, **data))


def issue_invoice(op: Operator, invoice_id: UUID, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "invoice.issue",
        str(invoice_id),
        ip,
        lambda: billing.issue_invoice(invoice_id, by=_name(op)),
        summary=lambda r: {"number": r["number"], "total": r["total"]},
    )


def void_invoice(op: Operator, invoice_id: UUID, reason: str, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "invoice.void",
        str(invoice_id),
        ip,
        lambda: billing.void_invoice(invoice_id, reason, by=_name(op)),
        reason=reason,
    )


def record_payment(op: Operator, invoice_id: UUID, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "payment.record",
        str(invoice_id),
        ip,
        lambda: billing.record_payment(invoice_id, by=_name(op), **data),
        summary=lambda r: {"number": r["number"], "amount": data["amount"], "status": r["status"]},
    )


def reverse_payment(op: Operator, payment_id: UUID, reason: str, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "payment.reverse",
        str(payment_id),
        ip,
        lambda: billing.reverse_payment(payment_id, reason, by=_name(op)),
        reason=reason,
    )


def decide_request(op: Operator, request_id: UUID, approve: bool, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "plan_request.approve" if approve else "plan_request.decline",
        str(request_id),
        ip,
        lambda: billing.decide_request(request_id, approve, by=_name(op)),
    )


def run_billing(op: Operator, ip: str | None) -> dict[str, int]:
    result: dict[str, int] = act(op, "billing.run", "", ip, lambda: billing.run_due(), summary=lambda r: dict(r))
    return result


# --------------------------------------------------------------------------- licences
def issue_licence(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "licence.issue",
        data.get("customer", ""),
        ip,
        lambda: licences.issue(issued_by=_name(op), **data),
        summary=lambda r: {"licence_no": r["licence_no"], "customer": r["customer"]},
    )


def revoke_licence(op: Operator, licence_id: UUID, reason: str, ip: str | None) -> dict[str, Any]:
    return act(
        op,
        "licence.revoke",
        str(licence_id),
        ip,
        lambda: licences.revoke(licence_id, reason),
        reason=reason,
        summary=lambda r: {"licence_no": r["licence_no"]},
    )


# --------------------------------------------------------------------------- operators
def _operator_row(operator_id: UUID) -> Any:
    with master_session() as m:
        row = m.execute(
            text("select id, name, email, status, role from master.operator where id = :i"), {"i": str(operator_id)}
        ).first()
    if row is None:
        raise NotFound("No such operator")
    return row


def create_operator(op: Operator, data: dict[str, Any], ip: str | None) -> dict[str, Any]:
    """The new operator must choose their own password at the first sign-in. Without a password a temporary one is made
    and returned once; with the second factor on, the secret is returned once too. Neither is ever logged."""
    out: dict[str, Any] = {}
    chosen = data.get("password")
    temporary = None if chosen else operators.temporary_password()

    def work() -> dict[str, Any]:
        operator_id, secret, uri = operators.create_operator(
            data["name"], data["email"], chosen or temporary or "", data.get("role", "readonly"),
            must_change_password=True)
        out.update({"id": operator_id, "mfa_secret": secret or None, "otpauth_uri": uri or None,
                    "temporary_password": temporary})
        return {"email": data["email"], "role": data.get("role", "readonly")}

    console._change(op, "operator.create", data["email"], ip, work)
    return out


def update_operator(op: Operator, operator_id: UUID, changes: dict[str, Any], ip: str | None) -> dict[str, Any]:
    row = _operator_row(operator_id)
    if row.id == op.id:
        raise ValidationFailed("You cannot change your own role or status: ask another superadmin")

    def work() -> dict[str, Any]:
        if "role" in changes:
            operators.set_role(row.email, changes["role"])
        if "status" in changes:
            operators.set_status(row.email, changes["status"])
        return {"email": row.email, **changes}

    console._change(op, "operator.update", row.email, ip, work)
    return dict(_operator_row(operator_id)._mapping)


def reset_operator_mfa(op: Operator, operator_id: UUID, ip: str | None) -> dict[str, str]:
    row = _operator_row(operator_id)
    out: dict[str, str] = {}

    def work() -> dict[str, Any]:
        secret, uri = operators.reset_mfa(row.email)
        out.update({"mfa_secret": secret, "otpauth_uri": uri})
        return {"email": row.email}

    console._change(op, "operator.reset_mfa", row.email, ip, work)
    return out


def reset_operator_password(op: Operator, operator_id: UUID, ip: str | None) -> dict[str, str]:
    """A random temporary password, returned once, that its owner must change at the next sign-in (their sign-ins
    end). Not for your own account: use "Change my password"."""
    row = _operator_row(operator_id)
    if row.id == op.id:
        raise ValidationFailed("Change your own password with Change my password")
    out: dict[str, str] = {}

    def work() -> dict[str, Any]:
        out["temporary_password"] = operators.reset_password(row.email, actor=op)
        return {"email": row.email}

    console._change(op, "operator.reset_password", row.email, ip, work)
    return out
