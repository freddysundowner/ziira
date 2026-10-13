"""Robustness: no input, however hostile, may cause a server error (HTTP 5xx) or an unhandled exception.

A schema-driven fuzzer (tests/fuzz.py) takes every endpoint from the OpenAPI description, builds a valid request
for it and then changes one value at a time: huge and non-finite numbers, NUL bytes, odd Unicode, wrong types,
missing and unknown fields, bad ids, negative and enormous paging values. Hand-written cases below cover the
specific failures this found (numeric overflow, paging, NUL characters).
"""

import random
from collections import Counter
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.conftest import sign_in
from tests.fuzz import Spec, mutations, operations
from tests.stock_helpers import INV, P, make_stock_shop, system

# Not fuzzed: they would end the fuzzer's own session or change the owner's credentials.
SKIP = ("/auth/sign-out", "/auth/change-password", "/auth/password", "/health", "/docs", "/openapi", "/redoc")


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Fuzz Co")
    registry.enable(s["tenant_id"], "catalog_stats")
    registry.enable(s["tenant_id"], "finance")
    registry.enable(s["tenant_id"], "payments")
    owner, co = s["owner"], str(s["company_id"])
    reasons = client.get("/api/v1/settings/reason-codes", headers=owner).json()
    s["reason"] = next(x["id"] for x in reasons if x["category"] == "stock_adjustment")
    adjustment = client.post(f"{INV}/adjustments", headers=owner, json={
        "company_id": co, "location_id": s["main"], "reason_code_id": s["reason"],
        "lines": [{"product_id": s["cement"], "qty_change": "1"}]}).json()
    transfer = client.post(f"{INV}/transfers", headers=owner, json={
        "company_id": co, "from_location_id": s["main"], "to_location_id": s["juja_store"],
        "lines": [{"product_id": s["cement"], "quantity": "1"}]}).json()
    count = client.post(f"{INV}/counts", headers=owner, json={"company_id": co, "location_id": s["juja_store"]}).json()
    series = client.get("/api/v1/settings/document-series", headers=owner).json()
    other = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Other", "email": "other@fuzz-co.test", "password": "other-pass-123"}).json()
    rule = client.post("/api/v1/approvals/rules", headers=owner, json={
        "company_id": co, "doc_type": "stock_adjustment", "approver_role_id": s["roles"]["Branch Manager"],
        "min_amount": "100000"}).json()
    books = client.post(f"/api/v1/finance/companies/{co}/books", headers=owner).json()
    s["acc"] = {a["code"]: a["id"] for a in books}
    manual = client.post("/api/v1/finance/manual-journals", headers=owner, json={
        "company_id": co, "entry_date": "2026-10-13", "description": "Fuzz", "lines": [
            {"account_id": s["acc"]["6000"], "debit": "5"}, {"account_id": s["acc"]["1020"], "credit": "5"}]}).json()
    posted = client.post(f"/api/v1/finance/manual-journals/{manual['id']}/submit", headers=owner).json()
    period = client.post("/api/v1/finance/periods", headers=owner, json={"company_id": co, "day": "2026-10-13"}).json()
    rules = client.get("/api/v1/finance/posting-rules", headers=owner, params={"company_id": co}).json()
    pay = "/api/v1/payments"
    till = client.post(f"{pay}/accounts", headers=owner, json={
        "company_id": co, "branch_id": str(s["branch_id"]), "kind": "mpesa_till", "name": "Fuzz till",
        "shortcode": "600638", "provider": "fake"}).json()
    client.put(f"{pay}/accounts/{till['id']}/credentials", headers=owner, json={
        "consumer_key": "a", "consumer_secret": "b", "passkey": "c"})
    bank = client.post(f"{pay}/accounts", headers=owner, json={"company_id": co, "kind": "bank", "name": "Fuzz bank"}).json()
    payment = client.post(f"{pay}/payments", headers=owner, json={
        "company_id": co, "branch_id": str(s["branch_id"]), "method": "mpesa", "amount": "10",
        "payment_account_id": till["id"], "external_ref": "FUZZREF1"}).json()
    intent = client.post(f"{pay}/intents", headers=owner, json={
        "payment_account_id": till["id"], "amount": "10", "phone": "0712345678"}).json()
    s["pay_ids"] = {"till": till["id"], "bank": bank["id"]}
    s["ids"] = {
        "payment_id": payment["id"], "intent_id": intent["id"],
        "account_id": s["acc"]["6000"], "manual_id": manual["id"], "entry_id": posted["entry_id"],
        "period_id": period["id"], "posting_rule_id": rules[0]["id"],
        "company_id": co, "location_id": s["main"], "product_id": s["cement"], "from_location_id": s["main"],
        "to_location_id": s["juja_store"], "base_uom_id": s["uom"], "tax_code_id": s["tax"],
        "branch_id": str(s["branch_id"]), "role_id": s["roles"]["Cashier"], "reason_code_id": s["reason"],
        "approver_role_id": s["roles"]["Branch Manager"], "adjustment_id": adjustment["id"],
        "transfer_id": transfer["id"], "count_id": count["id"],
        "series_id": series[0]["id"] if series else str(uuid4()),
        "user_id": other["id"], "rule_id": rule["id"], "line_id": transfer["lines"][0]["id"],
    }
    return s


def valid_body(shop):  # type: ignore[no-untyped-def]
    """Business-valid bodies for operations whose generic sample (strings like "x") cannot pass the rules."""
    co, counter = str(shop["company_id"]), iter(range(1_000_000))

    def fix(method: str, path: str, body):  # type: ignore[no-untyped-def]
        n = next(counter)
        if path.endswith("/users") and method == "POST":
            return {"full_name": "Fuzz User", "email": f"fuzz{n}@fuzz-co.test", "phone": None,
                    "password": "fuzz-pass-123"}
        if path.endswith("/roles") and method == "POST":
            return {"name": f"Fuzz role {n}", "permissions": ["products.view"]}
        if path.endswith("/permissions"):
            return {"permissions": ["products.view"]}
        if path.endswith("/opening-stock"):
            return {**body, "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "1"}]}
        if path.endswith("/adjustments") and method == "POST":
            return {**body, "reason_code_id": shop["reason"],
                    "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}
        if path.endswith("/transfers") and method == "POST":
            return {**body, "lines": [{"product_id": shop["cement"], "quantity": "1"}]}
        if path.endswith("/counts") and method == "POST":
            return {"company_id": co, "location_id": shop["juja_store"]}
        if path.endswith("/entries"):
            return {"entries": [{"product_id": shop["cement"], "counted_qty": "1"}]}
        if path.endswith("/settings/reason-codes") and method == "POST":
            return {**body, "category": "stock_adjustment", "code": f"FUZZ{n}", "label": "Fuzz"}
        if path.endswith("/finance/accounts") and method == "POST":
            return {"company_id": co, "code": f"F{n}", "name": "Fuzz account", "type": "expense"}
        if path.endswith("/finance/manual-journals") and method == "POST":
            return {"company_id": co, "entry_date": "2026-10-13", "description": "Fuzz", "lines": [
                {"account_id": shop["acc"]["6000"], "debit": "1"}, {"account_id": shop["acc"]["1020"], "credit": "1"}]}
        if path.endswith("/finance/posting-rules") and method == "POST":
            return {"company_id": co, "doc_type": "stock_movement", "line_role": "cogs",
                    "account_id": shop["acc"]["5000"], "side": "debit", "conditions": {"movement_type": "sale"}}
        if path.endswith("/finance/periods") and method == "POST":
            return {"company_id": co, "day": "2026-10-13"}
        if path.endswith("/payments/payments") and method == "POST":
            return {"company_id": co, "branch_id": str(shop["branch_id"]), "method": "mpesa", "amount": "5",
                    "payment_account_id": shop["pay_ids"]["till"], "external_ref": f"FZ{n}"}
        if path.endswith("/payments/intents") and method == "POST":
            return {"payment_account_id": shop["pay_ids"]["till"], "amount": "5", "phone": "0712345678"}
        if path.endswith("/payments/settlements"):
            return {"from_account_id": shop["pay_ids"]["till"], "to_account_id": shop["pay_ids"]["bank"],
                    "amount": "1", "reference": f"FZS{n}"}
        if path.endswith("/payments/cash-deposits"):
            return {"company_id": co, "branch_id": str(shop["branch_id"]), "bank_account_id": shop["pay_ids"]["bank"],
                    "amount": "1", "reference": f"FZD{n}"}
        if path.endswith("/payments/closes") and method == "POST":
            return {"company_id": co, "branch_id": str(shop["branch_id"]), "business_date": "2026-01-01",
                    "cash_banked": "0"}
        if path.endswith("/reverse"):
            return {"reason": "Fuzz"}
        if path.endswith("/products/uoms"):
            return {"code": f"U{n}", "name": "Fuzz unit"}
        if path.endswith("/tax-codes"):
            return {"code": f"T{n}", "name": "Fuzz tax", "vat_rate": "8", "etims_tax_type": "A"}
        return body

    return fix


def test_no_request_causes_a_server_error(client, shop) -> None:  # type: ignore[no-untyped-def]
    spec = Spec(client.get("/openapi.json").json(), shop["ids"])
    fix, rng = valid_body(shop), random.Random(20261013)
    seen: Counter[int] = Counter()
    problems: list[str] = []
    for method, path, operation in operations(spec, SKIP):
        for url, query, body, label in mutations(spec, method, path, operation, rng, 5, fix):
            try:
                r = client.request(method, url, headers=shop["owner"], params=query, json=body)
            except Exception as error:                              # an exception escaped the application
                problems.append(f"{method} {path} [{label}] raised {type(error).__name__}: {str(error)[:150]}")
                continue
            seen[r.status_code] += 1
            if r.status_code >= 500:
                problems.append(f"{method} {path} [{label}] -> {r.status_code} {r.text[:120]}")
            if r.status_code == 401:                                # a mutation ended our session: sign in again
                shop["owner"] = sign_in(client, shop["code"], f"owner@{shop['code']}.test").headers
    assert not problems, "\n".join(problems[:20])
    assert sum(seen.values()) > 1500 and seen[200] + seen[201] > 200      # it really exercised the endpoints


# --------------------------------------------------------------------------- the specific failures it found
@pytest.mark.parametrize("value", ["1e20", "1e300", "NaN", "Infinity", "-Infinity", "99999999999999.9999",
                                   "0.00001", "abc", "", None, True])
def test_numbers_that_cannot_be_stored_are_refused_with_422(client, shop, value) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    for url, body in (
            (f"{INV}/opening-stock", {"company_id": co, "location_id": shop["main"],
                                      "lines": [{"product_id": shop["cement"], "quantity": value, "unit_cost": "1"}]}),
            (f"{INV}/opening-stock", {"company_id": co, "location_id": shop["main"],
                                      "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": value}]}),
            (f"{INV}/transfers", {"company_id": co, "from_location_id": shop["main"],
                                  "to_location_id": shop["juja_store"],
                                  "lines": [{"product_id": shop["cement"], "quantity": value}]}),
            (f"{P}/tax-codes", {"code": f"T{uuid4().hex[:6]}", "name": "x", "vat_rate": value, "etims_tax_type": "B"})):
        r = client.post(url, headers=shop["owner"], json=body)
        assert r.status_code in (201, 409, 422), (url, value, r.status_code)      # never a server error


def test_a_quantity_that_fits_its_column_but_not_the_arithmetic_is_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    """99999999999999.9999 units at 999999999999.999999 each is worth far more than the value column holds."""
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement
    from ziira.sdk import ValidationFailed

    product = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": "HUGE", "name": "Huge", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"]}).json()["id"]
    from uuid import UUID

    for quantity, cost in ((Decimal("99999999999999.9999"), Decimal("999999999999.999999")),
                           (Decimal("1"), Decimal("1000000000000")), (Decimal("1E+20"), Decimal("1"))):
        with pytest.raises(ValidationFailed, match="too large"), system(shop) as s:
            post_movement(s, MovementRequest(
                company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(product),
                quantity=quantity, movement_type="receipt", source_type="test", source_id=uuid4(), unit_cost=cost))


@pytest.mark.parametrize("path", ["balances", "movements", "adjustments", "transfers", "counts", "locations"])
@pytest.mark.parametrize("query", ["limit=-1", "limit=0", "limit=501", "limit=99999999999999999999", "offset=-5",
                                   "offset=99999999999999999999", "limit=abc", "location_id=nope", "status=%00"])
def test_lists_refuse_bad_paging_and_filters(client, shop, path: str, query: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{INV}/{path}?{query}", headers=shop["owner"])
    assert r.status_code in (200, 422), r.text


@pytest.mark.parametrize("query", ["limit=-1", "offset=-1", "limit=501", "search=%00", "search=%25", "search=%27--"])
def test_the_product_list_refuses_bad_paging_and_search(client, shop, query: str) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{P}/products?{query}", headers=shop["owner"]).status_code in (200, 422)


def test_paging_works_within_limits(client, shop) -> None:  # type: ignore[no-untyped-def]
    everything = client.get(f"{INV}/movements?limit=500", headers=shop["owner"]).json()
    first = client.get(f"{INV}/movements?limit=1", headers=shop["owner"]).json()
    assert len(first) <= 1 and len(everything) <= 500
    assert client.get(f"{INV}/movements?offset=100000", headers=shop["owner"]).json() == []


def test_a_text_with_a_nul_character_is_refused_not_a_crash(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/locations", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "code": "OK1",
        "name": "bad\x00name"})
    assert r.status_code == 422 and r.json()["error"] == "validation_failed"


def test_a_very_large_request_is_refused_up_front(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/locations", headers=shop["owner"], content=b"x" * 2_100_000,
                    )
    assert r.status_code == 413


def test_malformed_json_and_wrong_content_types_are_client_errors(client, shop) -> None:  # type: ignore[no-untyped-def]
    for content, content_type in ((b"{not json", "application/json"), (b"", "application/json"),
                                  (b"[1,2", "application/json"), (b"a=b", "application/x-www-form-urlencoded"),
                                  (b"\xff\xfe", "application/json")):
        r = client.post(f"{INV}/locations", headers={**shop["owner"], "Content-Type": content_type}, content=content)
        assert 400 <= r.status_code < 500, (content, r.status_code)
