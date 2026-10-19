"""Shared setup for the Bookings tests: a salon with two chairs, one bookable service and a customer."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tests.pos_helpers import credit_customer, make_sales_shop

B = "/api/v1/bookings"
ZONE = ZoneInfo("Africa/Nairobi")           # the zone make_tenant gives every test business (a fixture, not logic)
WEEK = [{"weekday": d, "start_time": "09:00", "end_time": "17:00"} for d in range(5)]


def workday(n: int) -> date:
    """The n-th working day (Monday to Friday) from the second Monday after today: far enough ahead for any notice."""
    day = date.today() + timedelta(days=14)
    day += timedelta(days=(7 - day.weekday()) % 7)
    for _ in range(n):
        day += timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
    return day


def when(n: int, hour: int, minute: int = 0) -> str:
    """ISO moment at this local time on the n-th working day."""
    return datetime.combine(workday(n), time(hour, minute), tzinfo=ZONE).isoformat()


def reason(client, shop, category: str, code: str) -> str:  # type: ignore[no-untyped-def]
    found = client.get("/api/v1/settings/reason-codes", headers=shop["owner"], params={"category": category}).json()
    return next(r["id"] for r in found if r["code"] == code)


def make_salon(client, registry, name: str, *, units: tuple[str, ...] = (), stock: str = "0"):  # type: ignore[no-untyped-def]
    """A sales shop with Bookings on; chairs `anna` and `brian` (Mon-Fri 09:00-17:00), the offer `cut` (60 minutes plus
    15 after, linked to the delivery service item, 58.00) and a customer. Users: manager, cashier (front desk)."""
    shop = make_sales_shop(client, registry, name, stock=stock)
    registry.enable(shop["tenant_id"], "bookings")
    for unit in units:
        registry.enable(shop["tenant_id"], unit)
    owner, co, branch = shop["owner"], str(shop["company_id"]), str(shop["branch_id"])
    chairs = {}
    for who in ("anna", "brian"):
        r = client.post(f"{B}/resources", headers=owner, json={
            "company_id": co, "branch_id": branch, "name": who.title(), "kind": "chair", "hours": WEEK})
        assert r.status_code == 201, r.text
        chairs[who] = r.json()["id"]
    offer = client.post(f"{B}/offers", headers=owner, json={
        "company_id": co, "product_id": shop["delivery"], "duration_minutes": 60, "buffer_after_minutes": 15,
        "resource_ids": list(chairs.values())})
    assert offer.status_code == 201, offer.text
    shop.update({"anna": chairs["anna"], "brian": chairs["brian"], "cut": offer.json()["id"],
                 "customer": credit_customer(client, shop, "Wanjiku Client", limit="100000", terms=14)})
    return shop


def book(client, shop, n: int, hour: int, minute: int = 0, who: str = "owner", **extra):  # type: ignore[no-untyped-def]
    body = {"offer_id": shop["cut"], "starts_at": when(n, hour, minute), "client_name": "Walk Client", **extra}
    return client.post(f"{B}/appointments", headers=shop[who], json=body)
