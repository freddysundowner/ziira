"""Extension points and validation hooks: contracts, per-tenant activation, blocking, manifests."""

from abc import ABC, abstractmethod

import pytest

from tests.conftest import make_tenant, sign_in
from ziira.kernel import extensions
from ziira.kernel.errors import DependencyError

P = "/api/v1/products"


# --------------------------------------------------------------------------- contracts (no database)
class Greeter(ABC):
    @abstractmethod
    def greet(self) -> str: ...


def test_contract_must_be_abstract() -> None:
    class NotAContract:
        pass

    with pytest.raises(TypeError, match="abstract base class"):
        extensions.define_extension_point("test.not_abstract", NotAContract)


def test_implementations_are_checked_against_the_contract() -> None:
    extensions.define_extension_point("test.greeter", Greeter)

    with pytest.raises(TypeError, match="must subclass Greeter"):
        @extensions.provides("test.greeter")
        class Stranger:
            def greet(self) -> str:
                return "hi"

    with pytest.raises(TypeError, match="does not implement: greet"):
        @extensions.provides("test.greeter")
        class Lazy(Greeter):
            pass


def test_registration_before_the_socket_exists_waits_for_it() -> None:
    @extensions.provides("test.later")
    class Early(Greeter):
        def greet(self) -> str:
            return "early"

    assert any("test.later" in m for m in extensions.undefined_registrations())
    point = extensions.define_extension_point("test.later", Greeter)
    assert [impl for _, impl in point.implementations] == [Early]
    assert not any("test.later" in m for m in extensions.undefined_registrations())


def test_units_may_plug_only_into_sockets_they_can_reach(registry) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    from ziira.kernel.registry import check_socket_declarations

    units = registry.units
    check_socket_declarations(units, units["catalog_stats"])            # requires products: fine
    stranger = replace(units["catalog_stats"], name="stranger", requires=(), optional=())
    with pytest.raises(DependencyError, match="products.product.before_create"):
        check_socket_declarations(units, stranger)


# --------------------------------------------------------------------------- in use (database)
@pytest.fixture(scope="module")
def shops(client, registry):  # type: ignore[no-untyped-def]
    """Two businesses: one with the catalog_stats plugin (which plugs into Products), one without."""
    out = {}
    for name, plugin in (("Hook Shop", True), ("Plain Shop", False)):
        t = make_tenant(name)
        registry.enable(t["tenant_id"], "products")
        if plugin:
            registry.enable(t["tenant_id"], "catalog_stats")
        code = name.lower().replace(" ", "-")
        headers = sign_in(client, code, f"owner@{code}.test").headers
        uom = client.post(f"{P}/uoms", headers=headers, json={"code": "PCS", "name": "Pieces"}).json()
        tax = client.post(f"{P}/tax-codes", headers=headers,
                          json={"code": "VAT16", "name": "VAT", "vat_rate": "16", "etims_tax_type": "B"}).json()
        out[name] = {**t, "headers": headers, "uom": uom["id"], "tax": tax["id"]}
    return out


def _create(client, shop, sku: str, name: str):  # type: ignore[no-untyped-def]
    return client.post(f"{P}/products", headers=shop["headers"],
                       json={"company_id": str(shop["company_id"]), "sku": sku, "name": name,
                             "base_uom_id": shop["uom"], "tax_code_id": shop["tax"]})


def test_validation_hook_blocks_only_where_the_plugin_is_enabled(client, shops) -> None:  # type: ignore[no-untyped-def]
    hook, plain = shops["Hook Shop"], shops["Plain Shop"]
    assert _create(client, hook, "CEM-1", "Cement 50kg").status_code == 201
    r = _create(client, hook, "CEM-2", "  cement 50KG ")
    assert r.status_code == 422 and "already exists" in r.json()["message"]
    # Same action in a business without the plugin: nobody blocks it
    assert _create(client, plain, "CEM-1", "Cement 50kg").status_code == 201
    assert _create(client, plain, "CEM-2", "Cement 50kg").status_code == 201


def test_a_crashing_validator_blocks_and_names_its_unit(client, shops) -> None:  # type: ignore[no-untyped-def]
    def broken(_session, _draft) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("bug in plugin")

    validators = extensions.validation_hooks()["products.product.before_create"].validators
    validators.append(("catalog_stats", broken))
    try:
        r = _create(client, shops["Hook Shop"], "BOLT-1", "Bolt M8")
        assert r.status_code == 422 and "catalog_stats" in r.json()["message"]
        assert _create(client, shops["Plain Shop"], "BOLT-1", "Bolt M8").status_code == 201
    finally:
        validators.remove(("catalog_stats", broken))


def test_extension_point_collects_from_enabled_units(client, shops) -> None:  # type: ignore[no-untyped-def]
    hook, plain = shops["Hook Shop"], shops["Plain Shop"]
    url = f"{P}/sku-suggestions?company_id={hook['company_id']}&name=Roofing sheet 3m"
    assert client.get(url, headers=hook["headers"]).json() == ["ROOFING-SHEET-3M", "ROO-SHEET-3M"]
    _create(client, hook, "ROO-SHEET-3M", "Roofing sheet 3m blue")
    assert client.get(url, headers=hook["headers"]).json() == ["ROOFING-SHEET-3M"]     # used SKUs dropped
    url = f"{P}/sku-suggestions?company_id={plain['company_id']}&name=Roofing sheet 3m"
    assert client.get(url, headers=plain["headers"]).json() == []                       # no suggester enabled


def test_sockets_listed_for_the_platform(registry) -> None:  # type: ignore[no-untyped-def]
    points, hooks = extensions.extension_points(), extensions.validation_hooks()
    assert points["products.sku_suggester"].owner == "products"
    assert [u for u, _ in points["products.sku_suggester"].implementations] == ["catalog_stats"]
    assert hooks["products.product.before_create"].owner == "products"
