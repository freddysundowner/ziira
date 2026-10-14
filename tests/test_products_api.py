"""Products API end to end: tenancy, validation, events, audit and the example plugin."""

from sqlalchemy import text


def h(tenant: dict) -> dict[str, str]:  # type: ignore[type-arg]
    return {"X-Tenant-ID": str(tenant["tenant_id"])}


def test_create_and_read_product(client, tenants) -> None:  # type: ignore[no-untyped-def]
    a = tenants["A"]
    uom = client.post("/api/v1/products/uoms", json={"code": "bag", "name": "Bag"}, headers=h(a))
    assert uom.status_code == 201, uom.text
    assert uom.json()["code"] == "BAG"
    tax = client.post("/api/v1/products/tax-codes", headers=h(a),
                      json={"code": "VAT16", "name": "Standard VAT", "vat_rate": "16", "authority_code": "B"})
    assert tax.status_code == 201, tax.text
    body = {"company_id": str(a["company_id"]), "sku": "cem-50kg", "name": "Cement 50kg",
            "base_uom_id": uom.json()["id"], "tax_code_id": tax.json()["id"], "reorder_level": "20"}
    created = client.post("/api/v1/products/products", json=body, headers=h(a))
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["sku"] == "CEM-50KG"

    listed = client.get("/api/v1/products/products?search=cement", headers=h(a)).json()
    assert [p["id"] for p in listed] == [product["id"]]

    # Duplicate SKU in the same company
    dup = client.post("/api/v1/products/products", json=body, headers=h(a))
    assert dup.status_code == 409

    # Business rule: services cannot be batch-tracked
    bad = client.post("/api/v1/products/products", headers=h(a),
                      json={**body, "sku": "SVC-1", "product_type": "service", "is_batch_tracked": True,
                            "reorder_level": None})
    assert bad.status_code == 422
    assert "batch" in bad.json()["message"]

    # Tenant B cannot see tenant A's product
    b = tenants["B"]
    assert client.get("/api/v1/products/products", headers=h(b)).json() == []
    assert client.get(f"/api/v1/products/products/{product['id']}", headers=h(b)).status_code == 404


def test_event_audit_and_plugin(client, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.audit import verify_chain
    from ziira.kernel.context import RequestContext, set_context
    from ziira.kernel.db import tenant_session

    a = tenants["A"]
    set_context(RequestContext(tenant_id=a["tenant_id"]))
    with tenant_session(a["tenant_id"]) as s:
        events = s.execute(text(
            "select count(*) from kernel.event_outbox where event_type = 'product.created'")).scalar()
        assert events == 1
        assert s.execute(text(
            "select count(*) from kernel.audit_log where entity_type like 'products.%'")).scalar() == 3
        assert verify_chain(s)
    stats = client.get("/api/v1/plugins/catalog-stats", headers=h(a)).json()
    assert stats[0]["product_count"] == 1


def test_disabled_module_is_not_available(client, registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session  # noqa: F401

    a = tenants["A"]
    registry.disable(a["tenant_id"], "catalog_stats")
    r = client.get("/api/v1/plugins/catalog-stats", headers=h(a))
    assert r.status_code == 404
    assert r.json()["error"] == "unit_not_enabled"
    registry.enable(a["tenant_id"], "catalog_stats")
    assert client.get("/api/v1/plugins/catalog-stats", headers=h(a)).status_code == 200


def test_units_endpoint(client, tenants) -> None:  # type: ignore[no-untyped-def]
    units = {u["name"]: u for u in client.get("/api/v1/units", headers=h(tenants["A"])).json()}
    assert units["kernel"]["enabled"] and units["products"]["enabled"]
    assert units["finance"]["enabled"] is False
