"""Shared setup for the payments tests: a business with stock, a till-cash account, an M-Pesa till and a bank account."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system

PAY = "/api/v1/payments"
SHORTCODE = "600638"


def make_payments_shop(client, registry, name: str, *, finance: bool = False):  # type: ignore[no-untyped-def]
    """The stock shop plus Payments (and optionally Finance), with a till-cash account for HQ, an M-Pesa till (provider
    "fake", credentials and a callback token set up) and a bank account. Extra users: `collector` (a cashier)."""
    shop = make_stock_shop(client, registry, name)
    registry.enable(shop["tenant_id"], "payments")
    if finance:
        registry.enable(shop["tenant_id"], "finance")
    owner, co = shop["owner"], str(shop["company_id"])
    cash = client.post(f"{PAY}/accounts", headers=owner, json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "kind": "cash", "name": "HQ till cash"}).json()
    till = client.post(f"{PAY}/accounts", headers=owner, json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "kind": "mpesa_till", "name": "HQ M-Pesa till",
        "shortcode": SHORTCODE, "provider": "fake"})
    assert till.status_code == 201, till.text
    till = till.json()
    r = client.put(f"{PAY}/accounts/{till['id']}/credentials", headers=owner, json={
        "consumer_key": "ck-123", "consumer_secret": "cs-456", "passkey": "pk-789"})
    assert r.status_code == 204, r.text
    token = client.post(f"{PAY}/accounts/{till['id']}/callback-token", headers=owner).json()
    bank = client.post(f"{PAY}/accounts", headers=owner, json={
        "company_id": co, "kind": "bank", "name": "Main bank account", "bank_account_masked": "****4821"}).json()
    card = client.post(f"{PAY}/accounts", headers=owner, json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "kind": "card", "name": "HQ card terminal"}).json()
    shop.update({"cash": cash["id"], "till": till["id"], "bank": bank["id"], "card": card["id"],
                 "token": token["token"], "callback_urls": token["urls"]})
    return shop


def c2b(ref: str, amount: str = "116.00", bill: str = "", phone: str = "254712345678", when: str | None = None,
        shortcode: str = SHORTCODE) -> dict[str, str]:
    """A C2B confirmation as Safaricom sends it."""
    when = when or datetime.now(UTC).astimezone().strftime("%Y%m%d%H%M%S")
    return {"TransactionType": "Pay Bill", "TransID": ref, "TransTime": when, "TransAmount": amount,
            "BusinessShortCode": shortcode, "BillRefNumber": bill, "MSISDN": phone, "FirstName": "Jane",
            "MiddleName": "", "LastName": "Wanjiru"}


def eat_now() -> str:
    """Now as Daraja writes times (East Africa Time)."""
    from ziira.modules.payments.domain.mpesa import daraja_timestamp

    return daraja_timestamp()


def post_c2b(client, shop, payload):  # type: ignore[no-untyped-def]
    return client.post(f"{PAY}/callbacks/{shop['token']}/c2b/confirmation", json=payload)


def work(shop, jobs_only: bool = False) -> int:  # type: ignore[no-untyped-def]
    """Run the background jobs that are due for this business (what `ziira worker` does)."""
    from ziira.kernel import jobs

    total = 0
    for _ in range(5):
        done = jobs.run_due(shop["tenant_id"])
        total += done
        if not done:
            break
    return total


def due_now(shop) -> None:  # type: ignore[no-untyped-def]
    """Make every queued job due now (instead of waiting for its delay)."""
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))


def record(client, shop, **kw):  # type: ignore[no-untyped-def]
    """Record a payment through the API (defaults: an M-Pesa payment of 116 at HQ)."""
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "method": "mpesa",
            "amount": "116.00", "payment_account_id": shop["till"], **kw}
    return client.post(f"{PAY}/payments", headers=kw.pop("headers", None) or shop["owner"], json={
        k: v for k, v in body.items() if k != "headers"})


def one(shop, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(sql), params).scalar_one()


def fresh_ref() -> str:
    return "R" + uuid4().hex[:9].upper()


__all__ = ["Decimal"]
