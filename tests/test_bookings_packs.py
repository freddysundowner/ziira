"""The salon and clinic packs as data: what switching them on gives a business, that nothing is overwritten or brought back, that
example prices are marked as examples until the business sets its own, the first-run steps tick themselves and the sample
week loads once and goes away again."""

import pytest
from sqlalchemy import text

from tests.bookings_helpers import B
from tests.pos_helpers import make_sales_shop
from tests.stock_helpers import system
from ziira.kernel import industry
from ziira.kernel.registry import Registry
from ziira.sdk import check_pack


def rows(shop, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


def test_the_pack_files_are_valid() -> None:
    assert check_pack("pack_salon") == []
    assert check_pack("pack_clinic") == []


@pytest.fixture(scope="module")
def salon(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Pack Salon", stock="5")
    registry.enable(s["tenant_id"], "bookings")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "pack_salon")
    s["co"] = str(s["company_id"])
    return s


def test_switching_the_salon_pack_on_sets_up_a_working_salon(client, salon) -> None:  # type: ignore[no-untyped-def]
    offers = client.get(f"{B}/offers", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    by_name = {o["name"]: o for o in offers}
    assert len(offers) == 13
    colour = by_name["Colour"]
    assert (colour["duration_minutes"], colour["processing_start_minutes"], colour["processing_minutes"]) == (150, 45, 60)
    assert colour["price_is_example"] is True and colour["needs_patch_test"] is True and colour["deposit_percent"] == "30.00"
    assert colour["product_id"], "linked to the service item the pack made in Products"
    assert {v["label"] for v in by_name["Women's cut and style"]["variants"]} == {"Senior stylist", "Stylist"}
    assert by_name["Facial"]["resource_ids"] and len(by_name["Facial"]["resource_ids"]) == 1       # the treatment room
    resources = client.get(f"{B}/resources", headers=salon["owner"]).json()
    assert [r["name"] for r in resources] == ["Stylist 1", "Stylist 2", "Barber chair 1", "Treatment room 1"]
    assert all(r["is_template"] for r in resources) and resources[0]["hours"] and resources[0]["level"] == "Senior"
    settings = client.get(f"{B}/settings", params={"company_id": salon["co"]}, headers=salon["owner"]).json()
    assert settings["late_cancel_fee_percent"] == "50.00" and settings["pack_name"] == "pack_salon"
    rules = client.get(f"{B}/commission/rules", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    assert sorted(((r["applies_to"], r["level"], r["value"]) for r in rules), key=str) == [
        ("product", None, "10.0000"), ("service", "Senior", "40.0000"), ("service", None, "30.0000")]
    fields = {r[0] for r in rows(salon, "select key from kernel.custom_field_def where entity_type = 'bookings.client'")}
    assert {"preferred_staff", "allergies", "formula", "patch_test_date"} <= fields
    limits = rows(salon, "select check_code from intel.check_setting")
    assert ("bookings.no_show_rate",) in limits


def test_the_first_run_steps_tick_themselves(client, salon) -> None:  # type: ignore[no-untyped-def]
    steps = client.get(f"{B}/pack-steps", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    assert len(steps) == 7 and not any(s["done"] for s in steps if s["step_id"] in ("prices", "staff", "booking"))
    assert next(s for s in steps if s["step_id"] == "link")["done"] is True              # the pack linked them already
    offers = client.get(f"{B}/offers", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    for o in offers:
        assert client.patch(f"{B}/offers/{o['id']}", headers=salon["owner"],
                            json={"price": str(float(o["price"]) + 1)}).status_code == 200
    fixed = client.get(f"{B}/offers", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    assert not any(o["price_is_example"] for o in fixed)                                 # the business set its own
    steps = client.get(f"{B}/pack-steps", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    assert next(s for s in steps if s["step_id"] == "prices")["done"] is True
    assert client.put(f"{B}/pack-steps/visibility", headers=salon["cashier"],
                      json={"company_id": salon["co"], "hidden": True}).status_code == 403


def test_seeding_again_changes_nothing_and_keeps_what_was_removed_or_changed(client, salon) -> None:  # type: ignore[no-untyped-def]
    assert industry.apply_to_tenant(Registry(), salon["tenant_id"]) == {}
    resources = client.get(f"{B}/resources", headers=salon["owner"]).json()
    barber = next(r for r in resources if r["name"] == "Barber chair 1")
    assert client.patch(f"{B}/resources/{barber['id']}", headers=salon["owner"], json={"name": "Chair A"}).status_code == 200
    with system(salon) as db:
        db.execute(text("delete from bookings.pack_step where step_id = 'fees'"))
    assert industry.apply_to_tenant(Registry(), salon["tenant_id"]) == {}
    names = [r["name"] for r in client.get(f"{B}/resources", headers=salon["owner"]).json()]
    assert "Chair A" in names and "Barber chair 1" not in names                          # renamed stays renamed
    assert len(client.get(f"{B}/pack-steps", headers=salon["owner"], params={"company_id": salon["co"]}).json()) == 6


def test_the_sample_week_loads_once_and_goes_away(client, salon) -> None:  # type: ignore[no-untyped-def]
    made = client.post(f"{B}/sample-data", params={"company_id": salon["co"]}, headers=salon["owner"])
    assert made.status_code == 201, made.text
    assert made.json()["appointment"] >= 20 and made.json()["customer"] == 6
    again = client.post(f"{B}/sample-data", params={"company_id": salon["co"]}, headers=salon["owner"])
    assert again.json() == made.json()
    done = rows(salon, "select count(*) from bookings.appointment where status = 'completed'")[0][0]
    assert done >= 15
    assert rows(salon, "select count(*) from pos.sales_invoice")[0][0] == 0             # sample data bills nothing
    board = client.get(f"{B}/recalls", headers=salon["owner"], params={"company_id": salon["co"]}).json()
    assert isinstance(board, list)
    gone = client.delete(f"{B}/sample-data", params={"company_id": salon["co"]}, headers=salon["owner"])
    assert gone.status_code == 200 and gone.json()["appointments_removed"] >= 20
    assert rows(salon, "select count(*) from bookings.appointment")[0][0] == 0
    assert client.post(f"{B}/sample-data", params={"company_id": salon["co"]}, headers=salon["cashier"]).status_code == 403


def test_the_clinic_pack_is_administrative_only(client, registry) -> None:  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Pack Clinic", stock="5")
    registry.enable(s["tenant_id"], "bookings")
    registry.enable(s["tenant_id"], "pack_clinic")
    co = str(s["company_id"])
    offers = client.get(f"{B}/offers", headers=s["owner"], params={"company_id": co}).json()
    assert {"Consultation (new patient)", "Consultation (follow-up)", "Dental check-up", "Scale and polish"} <= {
        o["name"] for o in offers}
    assert next(o for o in offers if o["name"] == "Dental check-up")["recall_days"] == 180
    settings = client.get(f"{B}/settings", params={"company_id": co}, headers=s["owner"]).json()
    assert settings["reminder_template"] == "appointment_reminder_clinic" and settings["recall_template"] == "appointment_recall_clinic"
    keys = {r[0] for r in rows(s, "select entity_type || '.' || key from kernel.custom_field_def")}
    assert {"bookings.appointment.visit_type", "bookings.appointment.bill_to", "bookings.client.member_number"} <= keys
    forbidden = ("diagnosis", "prescription", "result", "treatment_notes", "medical", "allergy", "condition")
    assert not any(any(f in k for f in forbidden) for k in keys)                          # no clinical fields
    bad = client.patch(f"{B}/settings", params={"company_id": co}, headers=s["owner"], json={"recall_template": "nonsense"})
    assert bad.status_code == 422
