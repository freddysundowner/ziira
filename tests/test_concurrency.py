"""Simultaneous users: documents, numbers, approvals and counts must stay correct when requests overlap.

Each test releases several requests at the same moment (a barrier) and checks that exactly the right number
succeed. Requests go through the real application (separate threads, separate database transactions)."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system

THREADS = 6


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Race Co")
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"}]})
    assert r.status_code == 201, r.text
    s["reason"] = next(x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
                       if x["category"] == "stock_adjustment" and x["code"] == "FOUND")
    return s


def together(app_client: TestClient, calls: list):  # type: ignore[no-untyped-def,type-arg]
    """Run the calls at the same moment on separate threads and return their responses."""
    barrier = threading.Barrier(len(calls))

    def run(call):  # type: ignore[no-untyped-def]
        barrier.wait()
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def statuses(responses) -> Counter[int]:  # type: ignore[no-untyped-def]
    return Counter(r.status_code for r in responses)


def stock(shop, product: str = "cement") -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p"),
                         {"p": shop[product]}).scalar_one()


def test_a_document_cannot_be_submitted_twice_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = client.post(f"{INV}/adjustments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "reason_code_id": shop["reason"],
        "lines": [{"product_id": shop["cement"], "qty_change": "-10"}]}).json()
    before = stock(shop)
    results = together(client, [lambda: client.post(f"{INV}/adjustments/{a['id']}/submit", headers=shop["owner"])
                                for _ in range(THREADS)])
    assert statuses(results) == {200: 1, 409: THREADS - 1}
    assert stock(shop) == before - 10                                   # applied once


def test_a_transfer_cannot_be_dispatched_twice_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = client.post(f"{INV}/transfers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": shop["cement"], "quantity": "5"}]}).json()
    before = stock(shop)
    results = together(client, [lambda: client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=shop["owner"])
                                for _ in range(THREADS)])
    assert statuses(results) == {200: 1, 409: THREADS - 1}
    with system(shop) as s:
        out = s.execute(text("select count(*) from inventory.stock_movement where source_id = :t "
                             "and movement_type = 'transfer_out'"), {"t": t["id"]}).scalar_one()
    assert out == 1 and stock(shop) == before                           # moved to in-transit once; company total same
    results = together(client, [lambda: client.post(f"{INV}/transfers/{t['id']}/receive", headers=shop["owner"])
                                for _ in range(THREADS)])
    assert statuses(results) == {200: 1, 409: THREADS - 1}


def test_document_numbers_are_unique_and_without_gaps_under_load(client, shop) -> None:  # type: ignore[no-untyped-def]
    def draft():  # type: ignore[no-untyped-def]
        return client.post(f"{INV}/adjustments", headers=shop["owner"], json={
            "company_id": str(shop["company_id"]), "location_id": shop["main"], "reason_code_id": shop["reason"],
            "lines": [{"product_id": shop["cement"], "qty_change": "1"}]})

    results = together(client, [draft for _ in range(10)])
    assert statuses(results) == {201: 10}
    numbers = sorted(int(r.json()["number"].rsplit("-", 1)[1]) for r in results)
    assert numbers == list(range(numbers[0], numbers[0] + 10))          # consecutive: no duplicates, no gaps


def test_only_one_count_can_be_started_at_once_per_location(client, shop) -> None:  # type: ignore[no-untyped-def]
    results = together(client, [lambda: client.post(f"{INV}/counts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["juja_store"]}) for _ in range(THREADS)])
    assert statuses(results) == {201: 1, 409: THREADS - 1}


def test_opening_stock_cannot_be_posted_twice_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    product = client.post("/api/v1/products/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": "ONCE", "name": "Once", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"]}).json()["id"]
    body = {"company_id": str(shop["company_id"]), "location_id": shop["main"],
            "lines": [{"product_id": product, "quantity": "10", "unit_cost": "5"}]}
    results = together(client, [lambda: client.post(f"{INV}/opening-stock", headers=shop["owner"], json=body)
                                for _ in range(THREADS)])
    assert statuses(results) == {201: 1, 409: THREADS - 1}
    with system(shop) as s:
        held = s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p"),
                         {"p": product}).scalar_one()
    assert held == 10


def test_an_approval_cannot_be_decided_twice_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "stock_adjustment",
        "approver_role_id": shop["roles"]["Branch Manager"], "min_amount": "1"})
    a = client.post(f"{INV}/adjustments", headers=shop["storekeeper"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], "reason_code_id": shop["reason"],
        "lines": [{"product_id": shop["cement"], "qty_change": "-3"}]}).json()
    assert client.post(f"{INV}/adjustments/{a['id']}/submit", headers=shop["storekeeper"]).json()["status"] == \
        "pending_approval"
    request = next(r for r in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                   if r["doc_id"] == a["id"])
    before = stock(shop)
    results = together(client, [lambda: client.post(f"/api/v1/approvals/{request['id']}/decision",
                                                    headers=shop["boss"], json={"approve": True})
                                for _ in range(THREADS)])
    assert statuses(results) == {200: 1, 409: THREADS - 1}
    assert stock(shop) == before - 3                                    # posted once


def test_sales_and_a_count_snapshot_do_not_corrupt_each_other(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Sales stream in while counts start: every balance still equals its movements afterwards."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement
    from ziira.sdk import ValidationFailed

    def sell() -> str:
        system_context(shop["tenant_id"])
        try:
            with tenant_session(shop["tenant_id"]) as s:
                post_movement(s, MovementRequest(
                    company_id=shop["company_id"], location_id=__import__("uuid").UUID(shop["main"]),
                    product_id=__import__("uuid").UUID(shop["cement"]), quantity=Dec("-1"), movement_type="sale",
                    source_type="race", source_id=uuid4()))
            return "sold"
        except ValidationFailed:
            return "refused"

    def start_and_cancel() -> str:
        r = client.post(f"{INV}/counts", headers=shop["owner"], json={
            "company_id": str(shop["company_id"]), "location_id": shop["main"], "product_ids": [shop["cement"]]})
        if r.status_code == 201:
            client.post(f"{INV}/counts/{r.json()['id']}/cancel", headers=shop["owner"])
        return "count"

    barrier = threading.Barrier(10)

    def run(job) -> str:  # type: ignore[no-untyped-def]
        barrier.wait()
        return job()

    with ThreadPoolExecutor(10) as pool:
        outcome = list(pool.map(run, [sell] * 7 + [start_and_cancel] * 3))
    assert outcome.count("sold") + outcome.count("refused") == 7
    from ziira.modules.inventory.services.verify import verify_stock

    with system(shop) as s:
        assert verify_stock(s) == []
