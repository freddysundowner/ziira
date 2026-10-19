"""Custom fields: the validation matrix, record types from units, permissions with scope, isolation between
businesses, the audit trail, privacy requests, concurrent writes, and the rule that money and stock are not fields."""

import threading
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import custom_fields
from ziira.kernel.custom_fields import FieldDef
from ziira.kernel.errors import ValidationFailed

CF, ET = "/api/v1/custom-fields", "products.product"


def definition(kind: str, key: str = "f", **extra):  # type: ignore[no-untyped-def]
    return FieldDef(id=uuid4(), company_id=None, entity_type=ET, key=key, label=key.title(), kind=kind,
                    choices=tuple(extra.pop("choices", ())), required=extra.pop("required", False),
                    searchable=False, sort_order=0, active=extra.pop("active", True), source="business")


# --------------------------------------------------------------------------- the validation matrix (no database)
@pytest.mark.parametrize(("kind", "value", "stored"), [
    ("text", "  hello  ", "hello"), ("text", "x" * 500, "x" * 500),
    ("number", 12, "12"), ("number", "12.50", "12.5"), ("number", "-0.0", "0"), ("number", 3.25, "3.25"),
    ("number", "1e2", "100"),
    ("date", "2026-02-28", "2026-02-28"), ("date", " 2026-03-01 ", "2026-03-01"),
    ("bool", True, True), ("bool", False, False),
    ("choice", "Senior", "Senior"),
])
def test_good_values_are_stored_in_one_form(kind: str, value: object, stored: object) -> None:
    d = definition(kind, choices=["Junior", "Senior"] if kind == "choice" else ())
    assert custom_fields.validate_values([d], {"f": value}) == {"f": stored}


@pytest.mark.parametrize(("kind", "value"), [
    ("text", 5), ("text", "x" * 501), ("text", "bad\x00char"),
    ("number", "abc"), ("number", True), ("number", "NaN"), ("number", "Infinity"), ("number", "1" * 19),
    ("date", "2026-02-30"), ("date", "28/02/2026"), ("date", 20260228),
    ("bool", "yes"), ("bool", 1),
    ("choice", "Expert"), ("choice", 3),
])
def test_bad_values_are_refused_naming_the_field(kind: str, value: object) -> None:
    d = definition(kind, key="grade", choices=["Junior", "Senior"] if kind == "choice" else ())
    with pytest.raises(ValidationFailed, match="Grade"):
        custom_fields.validate_values([d], {"grade": value})


def test_unknown_or_hidden_keys_are_refused_and_empty_clears() -> None:
    d = definition("text", "note")
    with pytest.raises(ValidationFailed, match="not a custom field"):
        custom_fields.validate_values([d], {"other": "x"})
    with pytest.raises(ValidationFailed, match="not a custom field"):
        custom_fields.validate_values([definition("text", "note", active=False)], {"note": "x"})
    assert custom_fields.validate_values([d], {"note": "   "}) == {"note": None}
    assert custom_fields.validate_values([d], {"note": None}) == {"note": None}


def test_required_fields_count_what_is_already_saved() -> None:
    d = definition("text", "plate", required=True)
    with pytest.raises(ValidationFailed, match="Plate"):
        custom_fields.validate_values([d], {})
    assert custom_fields.validate_values([d], {}, existing={"plate": "KAA 1"}) == {}
    with pytest.raises(ValidationFailed, match="Plate"):                       # clearing a required field is refused
        custom_fields.validate_values([d], {"plate": ""}, existing={"plate": "KAA 1"})
    assert custom_fields.validate_values([d], {}, check_required=False) == {}


def test_numbers_are_exact_decimals_not_floats() -> None:
    d = definition("number")
    assert Decimal(custom_fields.validate_values([d], {"f": "0.1"})["f"]) + Decimal(
        custom_fields.validate_values([d], {"f": "0.2"})["f"]) == Decimal("0.3")


# --------------------------------------------------------------------------- definitions through the API
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Fields Shop")


def add(client, shop, who="owner", **body):  # type: ignore[no-untyped-def]
    payload = {"entity_type": ET, "key": "brand", "label": "Brand", "kind": "text", **body}
    return client.post(CF, headers=shop[who] if who != "owner" else shop["owner"], json=payload)


def test_units_offer_their_record_types_and_only_managers_see_the_list(client, shop) -> None:  # type: ignore[no-untyped-def]
    listed = client.get(f"{CF}/entities", headers=shop["owner"])
    assert listed.status_code == 200
    assert ET in {e["entity_type"] for e in listed.json()}
    assert client.get(f"{CF}/entities", headers=shop["cashier"]).status_code == 403


def test_a_manager_adds_edits_hides_and_deletes_a_field(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = add(client, shop, key="brand", label="  Brand  ", searchable=True)
    assert made.status_code == 201, made.text
    field = made.json()
    assert (field["label"], field["source"], field["from_pack"], field["active"]) == ("Brand", "business", False, True)
    assert add(client, shop, key="brand").status_code == 409                       # the key is taken
    assert add(client, shop, key="Bad Key").status_code == 422
    assert add(client, shop, key="grade", kind="choice").status_code == 422         # a choice needs choices
    assert add(client, shop, kind="money", key="price").status_code == 422          # no money kind
    assert add(client, shop, entity_type="nothing.here", key="x").status_code == 404
    patched = client.patch(f"{CF}/{field['id']}", headers=shop["owner"],
                           json={"label": "Make", "required": False, "active": False})
    assert patched.status_code == 200 and (patched.json()["label"], patched.json()["active"]) == ("Make", False)
    assert [f["key"] for f in client.get(f"{CF}?entity_type={ET}", headers=shop["owner"]).json()] == []
    shown = client.get(f"{CF}?entity_type={ET}&include_inactive=true", headers=shop["owner"]).json()
    assert [f["key"] for f in shown] == ["brand"]
    assert client.delete(f"{CF}/{field['id']}", headers=shop["owner"]).status_code == 204
    assert client.delete(f"{CF}/{field['id']}", headers=shop["owner"]).status_code == 404


def test_nobody_without_the_permission_manages_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("cashier", "storekeeper", "boss"):
        assert add(client, shop, who=who, key="nope").status_code == 403, who
    assert client.get(CF, headers=shop["cashier"]).status_code == 403                   # needs an entity type
    assert client.get(f"{CF}?entity_type={ET}", headers=shop["cashier"]).status_code == 200   # may open products


def test_fields_can_be_reordered_and_pack_fields_cannot_be_deleted(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    one = add(client, shop, key="aa").json()["id"]
    two = add(client, shop, key="bb").json()["id"]
    done = client.put(f"{CF}/order", headers=shop["owner"], json={"entity_type": ET, "ids": [two, one]})
    assert done.status_code == 204
    keys = [f["key"] for f in client.get(f"{CF}?entity_type={ET}", headers=shop["owner"]).json()]
    assert keys.index("bb") < keys.index("aa")
    with system(shop) as s:
        s.execute(text("update kernel.custom_field_def set source = 'pack:pack_demo_services' where id = :i"),
                  {"i": two})
    refused = client.delete(f"{CF}/{two}", headers=shop["owner"])
    assert refused.status_code == 409 and "hide" in str(refused.json()).lower()
    assert client.patch(f"{CF}/{two}", headers=shop["owner"], json={"active": False}).status_code == 200


# --------------------------------------------------------------------------- values
def test_values_are_saved_checked_audited_and_merged(client, shop) -> None:  # type: ignore[no-untyped-def]
    for key, kind, extra in (("color", "choice", {"choices": ["Red", "Blue"]}), ("weight", "number", {}),
                             ("launched", "date", {}), ("fragile", "bool", {}), ("tag", "text", {"required": False})):
        assert add(client, shop, key=key, kind=kind, label=key.title(), **extra).status_code == 201
    pid = shop["cement"]
    url = f"{CF}/values/{ET}/{pid}"
    first = client.put(url, headers=shop["boss"], json={"values": {"color": "Red", "weight": "2.50", "tag": "a"}})
    assert first.status_code == 200, first.text
    assert first.json()["values"] == {"color": "Red", "weight": "2.5", "tag": "a"}
    second = client.put(url, headers=shop["boss"], json={"values": {"fragile": True, "tag": ""}})
    assert second.json()["values"] == {"color": "Red", "weight": "2.5", "fragile": True}      # others stay, tag cleared
    bad = client.put(url, headers=shop["boss"], json={"values": {"color": "Green"}})
    assert bad.status_code == 422 and "Color" in str(bad.json())
    assert client.put(url, headers=shop["boss"], json={"values": {"launched": "2026-13-01"}}).status_code == 422
    assert client.put(url, headers=shop["boss"], json={"values": {"nonsense": 1}}).status_code == 422
    read = client.get(url, headers=shop["cashier"])                          # may open products: may read the values
    assert read.status_code == 200 and read.json()["values"]["color"] == "Red"
    assert "color" in [f["key"] for f in read.json()["fields"]]
    with system(shop) as s:
        entries = s.execute(text("select changes from kernel.audit_log where entity_type = 'kernel.custom_field_value' "
                                 "and entity_id = :i order by id"), {"i": pid}).scalars().all()
    assert len(entries) == 2 and entries[0]["keys"] == ["color", "tag", "weight"]
    assert "Red" not in str(entries)                                          # keys only: values may be personal data


def test_who_may_read_and_write_values_follows_the_record(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"{CF}/values/{ET}/{shop['cement']}"
    assert client.put(url, headers=shop["cashier"], json={"values": {"tag": "x"}}).status_code == 403   # view only
    assert client.put(url, headers=shop["storekeeper"], json={"values": {"tag": "x"}}).status_code == 403
    assert client.get(url, headers=shop["storekeeper"]).status_code == 200
    assert client.get(f"{CF}/values/{ET}/{uuid4()}", headers=shop["owner"]).status_code == 404
    assert client.get(f"{CF}/values/nothing.here/{shop['cement']}", headers=shop["owner"]).status_code == 404
    assert client.put(url, headers=shop["owner"], json={"values": {"tag": "ok"}}).status_code == 200


def test_required_fields_block_saving_until_filled(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert add(client, shop, key="serial_no", label="Serial", required=True).status_code == 201
    url = f"{CF}/values/{ET}/{shop['paint']}"
    refused = client.put(url, headers=shop["owner"], json={"values": {"tag": "x"}})
    assert refused.status_code == 422 and "Serial" in str(refused.json())
    assert client.put(url, headers=shop["owner"], json={"values": {"serial_no": "S1"}}).status_code == 200
    serial = next(f for f in client.get(CF, headers=shop["owner"]).json() if f["key"] == "serial_no")
    assert client.delete(f"{CF}/{serial['id']}", headers=shop["owner"]).status_code == 204    # not for the others


def test_a_deleted_field_takes_its_values_with_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = add(client, shop, key="temp", label="Temp").json()
    url = f"{CF}/values/{ET}/{shop['delivery']}"
    client.put(url, headers=shop["owner"], json={"values": {"temp": "x"}})
    client.delete(f"{CF}/{made['id']}", headers=shop["owner"])
    assert "temp" not in client.get(url, headers=shop["owner"]).json()["values"]


def test_searchable_text_fields_can_be_found(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert add(client, shop, key="shelf", label="Shelf", searchable=True).status_code == 201
    client.put(f"{CF}/values/{ET}/{shop['cement']}", headers=shop["owner"], json={"values": {"shelf": "Aisle 7_B"}})
    with system(shop) as s:
        assert custom_fields.find_entity_ids(s, ET, "shelf", "aisle 7_") == [UUID(shop["cement"])]
        assert custom_fields.find_entity_ids(s, ET, "shelf", "9%") == []        # wildcards are not wildcards
        assert custom_fields.find_entity_ids(s, ET, "tag", "ok") == []          # not searchable


# --------------------------------------------------------------------------- isolation, privacy, concurrency
def test_another_business_sees_none_of_it(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    other = make_stock_shop(client, registry, "Fields Other")
    assert client.get(f"{CF}?entity_type={ET}", headers=other["owner"]).json() == []
    assert client.get(f"{CF}/values/{ET}/{shop['cement']}", headers=other["owner"]).status_code == 404
    with system(other) as s:
        assert s.execute(text("select count(*) from kernel.custom_field_def")).scalar() == 0
        assert s.execute(text("select count(*) from kernel.custom_field_value")).scalar() == 0


def test_privacy_requests_find_export_and_erase_text_values(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.personal_data import Subject

    assert add(client, shop, key="contact", label="Contact", searchable=False).status_code == 201
    assert add(client, shop, key="since", label="Since", kind="date").status_code == 201
    url = f"{CF}/values/{ET}/{shop['paint']}"
    client.put(url, headers=shop["owner"], json={"values": {"contact": "Jane.Doe@Example.com", "since": "2020-01-01"}})
    provider = custom_fields.CustomFieldData()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], Subject(raw="jane.doe@example.com", email="jane.doe@example.com"))
        assert len(found) == 1 and found[0].match == "exact"
        assert provider.find(s, shop["company_id"], Subject(raw="nobody@example.com", email="nobody@example.com")) == []
        exported = provider.export(s, found[0])
        assert exported["fields"]["Contact"] == "Jane.Doe@Example.com" and exported["fields"]["Since"] == "2020-01-01"
        outcome = provider.anonymise(s, found[0], "request")
        assert outcome.status == "anonymised"
    values = client.get(url, headers=shop["owner"]).json()["values"]
    assert values["contact"] == "[erased]" and "since" not in values


def test_writes_to_different_fields_at_the_same_time_both_survive(client, shop) -> None:  # type: ignore[no-untyped-def]
    for key in ("c1", "c2", "c3", "c4"):
        assert add(client, shop, key=key, label=key.upper()).status_code == 201
    entity = uuid4()
    with system(shop) as s:
        company = shop["company_id"]
        s.execute(text("select 1"))
    errors: list[Exception] = []

    def write(key: str) -> None:
        try:
            with system(shop) as s:
                custom_fields.write_values(s, ET, entity, {key: key * 3}, company_id=company)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(k,)) for k in ("c1", "c2", "c3", "c4")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    with system(shop) as s:
        assert custom_fields.read_values(s, ET, entity) == {"c1": "c1c1c1", "c2": "c2c2c2", "c3": "c3c3c3",
                                                             "c4": "c4c4c4"}
        assert s.execute(text("select count(*) from kernel.custom_field_value where entity_id = :e"),
                         {"e": entity}).scalar() == 1


def test_there_is_no_money_or_stock_kind() -> None:
    assert set(custom_fields.KINDS) == {"text", "number", "date", "bool", "choice"}
