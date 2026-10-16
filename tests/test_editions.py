"""Editions: named bundles of units. Definitions are valid; registering with an edition switches on exactly its units;
the older `mode` still works; switching later only adds."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import system
from ziira.kernel import editions
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.manifest import CATEGORIES
from ziira.kernel.registry import discover, install_order

REGISTER, VERIFY = "/api/v1/register", "/api/v1/register/verify"


def register(client, name: str, **extra):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    body = {"business_name": name, "owner_name": "Ada Owner", "email": f"o-{uuid4().hex[:8]}@ed.test",
            "password": "a-good-password-1", "currency": "usd", "phone_country_code": "44", "country": "gb", **extra}
    asked = client.post(REGISTER, json=body)
    assert asked.status_code == 202, asked.text
    done = client.post(VERIFY, json={"token": asked.json()["dev_token"], "device_id": "dev-1"})
    assert done.status_code == 200, done.text
    out = done.json()
    return out, {"Authorization": f"Bearer {out['access_token']}"}


def enabled(tenant_id) -> set[str]:  # type: ignore[no-untyped-def]
    with system({"tenant_id": tenant_id}) as s:
        return {r.unit_name for r in s.execute(text("select unit_name from kernel.tenant_unit where status = 'enabled'"))
            if not r.unit_name.startswith("pack_")}                  # country packs follow the country, not the edition


def expected(edition: str) -> set[str]:
    units = discover()
    return {u for u in install_order(units, list(editions.get(edition).units)) if not units[u].core}


def test_the_built_in_editions_are_valid() -> None:
    all_editions = editions.load_editions()
    assert set(all_editions) == {"retail", "distribution", "books", "intelligence", "full"}
    units = discover()
    for e in all_editions.values():
        assert e.title and e.pitch and e.checklist, e.id
        assert set(e.units) <= set(units), e.id
        assert all(s.unit == "" or s.unit in e.units or s.unit in expected(e.id) for s in e.checklist), e.id
        assert all(c in CATEGORIES for c in e.plugin_categories)
    assert editions.get("full").units == tuple(get_settings().registration_units.split(","))
    assert editions.get("intelligence").units == ("connect", "intel", "command", "imports")
    assert set(editions.get("retail").units) < set(editions.get("distribution").units)


def test_aliases_and_unknown_editions() -> None:
    assert editions.resolve() == "full"
    assert editions.resolve(mode="core") == "full" and editions.resolve(mode="standalone") == "intelligence"
    assert editions.resolve("books", "standalone") == "books"            # an edition wins over the older mode
    with pytest.raises(Exception, match="Edition is one of"):
        editions.resolve("sparkly")


def test_every_manifest_names_a_known_category_and_plugins_only_have_countries() -> None:
    for m in discover().values():
        if not m.core:
            assert m.category in CATEGORIES, m.name
        assert not (m.countries and m.kind != "plugin")


def test_registering_with_an_edition_switches_on_exactly_its_units(client, registry) -> None:  # type: ignore[no-untyped-def]
    for edition in ("retail", "books"):
        out, headers = register(client, f"{edition} traders", edition=edition)
        assert enabled(out["tenant_id"]) - {"kernel"} == expected(edition), edition
        mine = client.get("/api/v1/edition", headers=headers).json()
        assert mine["edition"]["id"] == edition and mine["done"] == [] and mine["dismissed"] is False
    assert "purchasing" not in expected("retail") and "pos" not in expected("books")


def test_the_older_mode_and_the_default_map_to_editions(client, registry) -> None:  # type: ignore[no-untyped-def]
    out, headers = register(client, "Old Mode Ltd", mode="standalone")
    assert enabled(out["tenant_id"]) - {"kernel"} == expected("intelligence")
    assert client.get("/api/v1/edition", headers=headers).json()["edition"]["id"] == "intelligence"
    out, headers = register(client, "Default Ltd")
    assert enabled(out["tenant_id"]) - {"kernel"} == expected("full")
    assert client.get("/api/v1/edition", headers=headers).json()["edition"]["id"] == "full"
    bad = client.post(REGISTER, json={"business_name": "Nope Ltd", "owner_name": "A B", "email": "x@y.test",
                                      "password": "a-good-password-1", "currency": "usd", "edition": "sparkly"})
    assert bad.status_code == 422


def test_the_list_is_public_and_switching_only_adds(client, registry) -> None:  # type: ignore[no-untyped-def]
    listed = client.get("/api/v1/editions")
    assert listed.status_code == 200
    assert {e["id"] for e in listed.json()} == {"retail", "distribution", "books", "intelligence", "full"}
    out, headers = register(client, "Grows Ltd", edition="retail")
    before = enabled(out["tenant_id"])
    switched = client.post("/api/v1/edition", headers=headers, json={"edition": "distribution"})
    assert switched.status_code == 200, switched.text
    after = enabled(out["tenant_id"])
    assert before < after and after - {"kernel"} == expected("distribution")
    assert set(switched.json()["enabled"]) == after - before
    assert switched.json()["mine"]["edition"]["id"] == "distribution"
    # switching to a smaller edition takes nothing away
    client.post("/api/v1/edition", headers=headers, json={"edition": "books"})
    assert enabled(out["tenant_id"]) >= after
    assert client.post("/api/v1/edition", headers=headers, json={"edition": "nope"}).status_code == 422


def test_first_steps_can_be_ticked_and_hidden(client, registry) -> None:  # type: ignore[no-untyped-def]
    out, headers = register(client, "Steps Ltd", edition="retail")
    step = editions.get("retail").checklist[0].id
    done = client.put(f"/api/v1/edition/steps/{step}", headers=headers, json={"done": True})
    assert done.json()["done"] == [step]
    client.put(f"/api/v1/edition/steps/{step}", headers=headers, json={"done": True})        # twice: still once
    assert client.get("/api/v1/edition", headers=headers).json()["done"] == [step]
    assert client.put(f"/api/v1/edition/steps/{step}", headers=headers, json={"done": False}).json()["done"] == []
    assert client.put("/api/v1/edition/steps/nope", headers=headers, json={"done": True}).status_code == 404
    hidden = client.put("/api/v1/edition/checklist", headers=headers, json={"dismissed": True})
    assert hidden.json()["dismissed"] is True


def test_the_catalog_carries_category_and_countries(client, registry) -> None:  # type: ignore[no-untyped-def]
    _, headers = register(client, "Catalog Ltd")
    cards = {c["name"]: c for c in client.get("/api/v1/units/catalog", headers=headers).json()}
    assert cards["pos"]["category"] == "sales" and cards["messaging"]["category"] == "messaging"
    assert cards["messaging"]["countries"] == []
