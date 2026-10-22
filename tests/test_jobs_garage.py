"""Garages, body shops and repair shops on Jobs: intake details and the item's history, next-service dates, walk-ins,
additional work needing a fresh approval, work types and the flat-rate library, part classes and markups, parts ordered
for the job and the customer's own parts, unused-part returns, charges and storage, deposits, release on payment,
bays, courtesy cars and the technician report."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817

import pytest
from sqlalchemy import text

from tests.jobs_helpers import JOBS, make_jobs_shop, move, new_job, stock_on_hand
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    made = make_jobs_shop(client, registry, "Garage Wave Two")
    co = str(made["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=made["owner"], json={
        "default_warranty_days": 30})
    for code, name, rate in (("mechanical", "Mechanical", "100.00"), ("body", "Body", "150.00"),
                             ("paint", "Paint", "200.00")):
        r = client.post(f"{JOBS}/work-types", headers=made["owner"], json={
            "company_id": co, "code": code, "name": name, "hourly_rate": rate})
        assert r.status_code == 201, r.text
    return made


def get_job(client, shop, job, who="owner"):  # type: ignore[no-untyped-def]
    r = client.get(f"{JOBS}/jobs/{job['id']}", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def post(client, shop, path, body=None, who="owner", expect=(200, 201)):  # type: ignore[no-untyped-def]
    r = client.post(f"{JOBS}{path}", headers=shop[who], json=body or {})
    assert r.status_code in expect, r.text
    return r


# --------------------------------------------------------------------------- intake and the item's history
def test_intake_details_are_kept_and_the_odometer_follows_the_item(client, shop) -> None:  # type: ignore[no-untyped-def]
    first = new_job(client, shop, title="Full service", odometer_in="45120.5", fuel_level="3/4", key_tag="K-14",
                    belongings="Child seat, umbrella", acknowledged_by_name="Wanjiku", job_type_code=None,
                    new_asset={"label": "Subaru Forester KDA 456C", "kind": "vehicle",
                               "identifiers": {"plate": "KDA 456C"}})
    assert first["odometer_in"] == "45120.5" and first["fuel_level"] == "3/4" and first["key_tag"] == "K-14"
    assert first["belongings"] == "Child seat, umbrella" and first["acknowledged_by_name"] == "Wanjiku"
    assert first["acknowledged_at"] is not None
    assert first["asset_detail"]["odometer"] == "45120.5"
    shop["subaru"] = first["asset"]["id"]
    # the next visit: a lower reading is kept on that visit but does not move the item's last reading back
    second = new_job(client, shop, title="Brakes", odometer_in="45000", asset_id=shop["subaru"])
    assert second["asset_detail"]["odometer"] == "45120.5"
    assert any("lower than the last" in (e["note"] or "") for e in second["events"])


def test_the_intake_screen_shows_what_was_done_before(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Oil service", asset_id=shop["subaru"])
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1", "description": "Oil and filter change"})
    post(client, shop, f"/jobs/{job['id']}/parts", {"description": "Oil filter", "quantity": "1", "unit_price": "20"})
    visits = client.get(f"{JOBS}/assets/{shop['subaru']}/visits", headers=shop["owner"]).json()
    assert visits[0]["job"]["number"] == job["number"]
    assert visits[0]["work"] == ["Oil and filter change", "Oil filter"] and visits[0]["total"] == "120.00"
    assert {v["job"]["number"] for v in visits} >= {job["number"], "JOB-HQ-000001"}


def test_next_service_is_kept_on_the_item_and_listed_when_due(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Service", asset_id=shop["subaru"])
    soon = (date.today() + timedelta(days=10)).isoformat()
    r = client.patch(f"{JOBS}/jobs/{job['id']}", headers=shop["owner"], json={
        "next_service_date": soon, "next_service_odometer": "50000"})
    assert r.status_code == 200, r.text
    asset = r.json()["asset_detail"]
    assert asset["next_service_date"] == soon and asset["service_due_in_days"] == 10
    assert Dec(asset["service_due_in_odometer"]) == Dec("4879.5")
    due = client.get(f"{JOBS}/service-due", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "within_days": 14}).json()
    assert [d["asset"]["id"] for d in due] == [shop["subaru"]] and due[0]["customer_name"] == "Wanjiku Motors"
    assert client.get(f"{JOBS}/service-due", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "within_days": 5}).json() == []


def test_service_reminders_are_queued_once_per_due_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    from uuid import UUID

    from ziira.modules.jobs.services import service_due
    from ziira.sdk import store_credential

    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "remind_service_due": True, "service_reminder_days": 14})
    with system(shop) as s:
        assert service_due.send_due_reminders(s) == 0              # no message channel yet: nothing is marked either
        marked = s.execute(text("select service_reminded_for from jobs.asset where id = :a"),
                           {"a": shop["subaru"]}).scalar_one()
        assert marked is None
        store_credential(s, company_id=shop["company_id"], provider="sms", label="Test SMS", secret={"key": "x"})
        assert service_due.send_due_reminders(s) == 1
        assert service_due.send_due_reminders(s) == 0              # once per due date
        body = s.execute(text("select body from kernel.notification where ref_type = 'jobs.asset' and ref_id = :a"),
                         {"a": UUID(shop["subaru"])}).scalar_one()
    assert "Subaru Forester" in body and "due for service" in body


# --------------------------------------------------------------------------- walk-ins
def test_a_walk_in_with_a_phone_becomes_a_customer_when_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Puncture",
        "customer_name": "Otieno", "customer_phone": "0722111222"}).json()
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "0.5", "description": "Repair puncture"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()
    assert done["customer_id"] and done["invoice_number"] and done["locked"] is True
    customer = client.get(f"/api/v1/crm/customers/{done['customer_id']}", headers=shop["owner"]).json()
    assert customer["name"] == "Otieno"
    assert any("customer record created" in e["note"] for e in done["events"] if e["note"])


# --------------------------------------------------------------------------- estimates, approval and additional work
def quoted_job(client, shop, **extra):  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Gearbox noise", **extra)
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "2", "description": "Strip and inspect"})
    estimate = post(client, shop, f"/jobs/{job['id']}/estimates", {"from_job": True}).json()
    sent = post(client, shop, f"/estimates/{estimate['id']}/send").json()["estimate"]
    post(client, shop, f"/estimates/{sent['id']}/decision", {"approved": True, "customer_name": "Wanjiku"})
    return get_job(client, shop, job)


def test_extra_work_after_approval_warns_and_needs_an_additional_estimate(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = quoted_job(client, shop)
    assert job["approval"]["approved_total"] == "200.00" and job["approval"]["extra"] == "0.00"
    post(client, shop, f"/jobs/{job['id']}/parts", {"description": "Clutch kit", "quantity": "1", "unit_price": "500"})
    job = get_job(client, shop, job)
    assert job["approval"]["extra"] == "500.00" and job["approval"]["mode"] == "warn"
    assert any("Beyond what the customer approved" in (e["note"] or "") for e in job["events"])
    # an additional-work estimate lists only what was added after the approval, and does not replace the first
    extra = post(client, shop, f"/jobs/{job['id']}/estimates", {"from_job": True, "kind": "additional"}).json()
    assert extra["kind"] == "additional" and [x["description"] for x in extra["lines"]] == ["Clutch kit"]
    sent = post(client, shop, f"/estimates/{extra['id']}/send").json()["estimate"]
    mid = get_job(client, shop, job)
    assert [e["status"] for e in mid["estimates"]] == ["approved", "sent"]
    assert mid["status"]["code"] == "approved"             # asking for more work does not send the job back to 'quoted'
    assert "approval" in mid["waiting_on"]
    post(client, shop, f"/estimates/{sent['id']}/decision", {"approved": True, "customer_name": "Wanjiku"})
    done = get_job(client, shop, job)
    assert done["approval"]["approved_total"] == "700.00" and done["approval"]["extra"] == "0.00"
    assert [e["status"] for e in done["estimates"]] == ["approved", "approved"]


def test_additional_work_follows_an_approved_estimate_only(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Noise")
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    r = post(client, shop, f"/jobs/{job['id']}/estimates", {"from_job": True, "kind": "additional"}, expect=(422,))
    assert "approved" in r.text


def test_a_business_can_block_work_beyond_what_was_approved(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={"unapproved_work": "block"})
    try:
        job = quoted_job(client, shop)
        refused = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"}, expect=(409,))
        assert "additional-work estimate" in refused.text
        post(client, shop, f"/jobs/{job['id']}/charges", {"kind": "towing", "description": "Tow", "unit_price": "10"},
             expect=(409,))
        assert get_job(client, shop, job)["labour"][0]["hours"] == "2.0000"
        assert len(get_job(client, shop, job)["labour"]) == 1
    finally:
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "unapproved_work": "warn"})


def test_a_job_nobody_quoted_is_never_checked(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={"unapproved_work": "block"})
    try:
        job = new_job(client, shop, title="Quick fix")
        post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
        assert get_job(client, shop, job)["approval"]["quoted"] is False
    finally:
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "unapproved_work": "warn"})


# --------------------------------------------------------------------------- labour: work types and the flat-rate library
def test_labour_is_priced_by_work_type_and_a_flat_rate_task(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    task = client.post(f"{JOBS}/labour-tasks", headers=shop["owner"], json={
        "company_id": co, "name": "Front brake pads", "code": "brake-pads-front", "standard_hours": "1.5",
        "work_type_code": "mechanical"})
    assert task.status_code == 201, task.text
    fixed = client.post(f"{JOBS}/labour-tasks", headers=shop["owner"], json={
        "company_id": co, "name": "Wheel alignment", "code": "alignment", "standard_hours": "0.8",
        "work_type_code": "mechanical", "flat_price": "90.00"})
    assert fixed.status_code == 201
    assert client.post(f"{JOBS}/labour-tasks", headers=shop["owner"], json={
        "company_id": co, "name": "Dup", "code": "alignment", "standard_hours": "1"}).status_code == 409
    job = new_job(client, shop, title="Brakes and alignment")
    body = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "2", "work_type_code": "body",
                                                             "description": "Straighten wing"}).json()
    assert body["labour"][0]["rate"] == "150.00" and body["labour"][0]["work_type_code"] == "body"
    out = post(client, shop, f"/jobs/{job['id']}/labour", {"task_code": "brake-pads-front"}).json()
    pads = out["labour"][1]
    assert pads["hours"] == "1.5000" and pads["rate"] == "100.00" and pads["description"] == "Front brake pads"
    assert pads["total"] == "150.00"
    out = post(client, shop, f"/jobs/{job['id']}/labour", {"task_code": "alignment"}).json()
    flat = out["labour"][2]
    assert flat["flat_price"] == "90.00" and flat["total"] == "90.00" and flat["hours"] == "0.8000"
    assert out["totals"]["labour_total"] == "540.00"           # 300 + 150 + 90
    unknown = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1", "work_type_code": "nope"}, expect=(422,))
    assert "work type" in unknown.text
    # a fixed price is one invoice line
    invoiced = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()
    assert invoiced["invoice_number"]
    from ziira.modules.pos.public import invoice_for_source

    with system(shop) as s:
        invoice = invoice_for_source(s, "job", job["id"] if not isinstance(job["id"], str) else __import__("uuid").UUID(job["id"]))
        assert invoice is not None and invoice.total == Dec("540.00")


def test_booked_hours_against_billed_hours_per_technician(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Timing belt")
    out = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "3", "description": "Timing belt",
                                                            "assignee_id": shop["users"]["tech"]}).json()
    line = out["labour"][0]
    post(client, shop, f"/jobs/{job['id']}/labour/{line['id']}/booked", {"booked_hours": "2.25"})
    rows = client.get(f"{JOBS}/reports/technicians", headers=shop["owner"], params={
        "company_id": str(shop["company_id"])}).json()
    mine = next(r for r in rows if r["user_id"] == shop["users"]["tech"])
    assert Dec(mine["billed_hours"]) == Dec("3") and Dec(mine["booked_hours"]) == Dec("2.25")
    assert mine["lines_without_booked"] == 0
    # a technician sees only their own row
    own = client.get(f"{JOBS}/reports/technicians", headers=shop["tech"], params={
        "company_id": str(shop["company_id"])}).json()
    assert [r["user_id"] for r in own] == [shop["users"]["tech"]]


# --------------------------------------------------------------------------- parts
def test_a_category_marks_up_the_cost_and_a_part_has_a_class(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cat = client.post(f"{JOBS}/part-categories", headers=shop["owner"], json={
        "company_id": co, "name": "Tyres", "markup_percent": "25", "default_class": "aftermarket"})
    assert cat.status_code == 201, cat.text
    assert client.patch(f"{JOBS}/part-categories/{cat.json()['id']}", headers=shop["owner"],
                        json={"markup_percent": "30"}).json()["markup_percent"] in ("30", "30.00")
    job = new_job(client, shop, title="New tyre")
    out = post(client, shop, f"/jobs/{job['id']}/parts", {
        "description": "Tyre 195/65R15", "quantity": "2", "category_code": "tyres", "cost_price": "1000"}).json()
    part = out["parts"][0]
    # cost 1000 + 30% = 1300, plus 16% VAT (the Parts item's code) = 1508.00 each
    assert part["unit_price"] == "1508.0000" and part["part_class"] == "aftermarket" and part["category_code"] == "tyres"
    genuine = post(client, shop, f"/jobs/{job['id']}/parts", {
        "description": "Wheel nut", "quantity": "4", "unit_price": "5", "part_class": "genuine"}).json()
    assert genuine["parts"][1]["part_class"] == "genuine"
    stock = post(client, shop, f"/jobs/{job['id']}/parts", {
        "product_id": shop["cement"], "quantity": "1", "category_code": "tyres"}).json()
    # stock part: average cost 50, +30%, +16% = 75.40
    assert stock["parts"][2]["unit_price"] == "75.4000" and stock["parts"][2]["is_stock"] is True
    bad = post(client, shop, f"/jobs/{job['id']}/parts", {"description": "x", "quantity": "1", "unit_price": "1",
                                                           "part_class": "stolen"}, expect=(422,))
    assert bad.status_code == 422


def test_the_customers_own_part_is_listed_but_never_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Fit customer's headlamp")
    out = post(client, shop, f"/jobs/{job['id']}/parts", {"description": "Headlamp (brought in)", "quantity": "1",
                                                           "customer_supplied": True}).json()
    assert out["parts"][0]["source"] == "customer_supplied" and out["totals"]["parts_total"] == "0.00"
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1", "description": "Fit headlamp"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()
    from uuid import UUID

    from ziira.modules.pos.public import invoice_for_source

    with system(shop) as s:
        invoice = invoice_for_source(s, "job", UUID(job["id"]))
        lines = s.execute(text("select description from pos.sales_invoice_line where invoice_id = :i"),
                          {"i": str(invoice.id)}).scalars().all()
    assert lines == ["Labour: Fit headlamp"] and done["totals"]["total"] == "100.00"


def test_a_part_ordered_for_the_job_blocks_the_invoice_until_it_arrives(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Alternator")
    out = post(client, shop, f"/jobs/{job['id']}/parts", {
        "description": "Alternator", "quantity": "1", "unit_price": "9000", "order_for_job": True,
        "supplier_name": "Spares Ltd", "expected_on": "2026-12-20"}).json()
    part = out["parts"][0]
    assert part["order_status"] == "to_order" and part["source"] == "special_order"
    assert out["waiting_on"] == ["parts"]
    listed = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"waiting_on": "parts"}).json()
    assert job["id"] in [j["id"] for j in listed]
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    refused = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}, expect=(422,))
    assert "has not arrived" in refused.text
    ordered = post(client, shop, f"/jobs/{job['id']}/parts/{part['id']}/ordered", {
        "supplier_name": "Spares Ltd", "expected_on": "2026-12-22"}).json()
    assert ordered["parts"][0]["order_status"] == "ordered" and ordered["parts"][0]["expected_on"] == "2026-12-22"
    arrived = post(client, shop, f"/jobs/{job['id']}/parts/{part['id']}/arrived").json()
    assert arrived["parts"][0]["order_status"] == "arrived" and arrived["waiting_on"] == []
    assert post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()["invoice_number"]


def test_an_ordered_stock_part_is_taken_from_the_store_when_it_arrives(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock_on_hand(shop)
    job = new_job(client, shop, title="Cement for the wall")
    out = post(client, shop, f"/jobs/{job['id']}/parts", {
        "product_id": shop["cement"], "quantity": "2", "order_for_job": True}).json()
    assert stock_on_hand(shop) == before                       # nothing left the shelf yet
    post(client, shop, f"/jobs/{job['id']}/parts/{out['parts'][0]['id']}/arrived")
    assert stock_on_hand(shop) == before - 2


def test_unused_parts_go_back_and_the_line_keeps_what_was_used(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock_on_hand(shop)
    job = new_job(client, shop, title="Pipes")
    out = post(client, shop, f"/jobs/{job['id']}/parts", {"product_id": shop["cement"], "quantity": "4"}).json()
    assert stock_on_hand(shop) == before - 4
    back = post(client, shop, f"/jobs/{job['id']}/parts/{out['parts'][0]['id']}/return", {
        "quantity": "1", "reason": "Wrong size"}).json()
    live = [p for p in back["parts"] if not p["voided"]]
    assert [p["quantity"] for p in live] == ["3.0000"] and stock_on_hand(shop) == before - 3
    voided = next(p for p in back["parts"] if p["voided"])
    assert "Returned 1 of 4" in voided["void_reason"]
    too_many = post(client, shop, f"/jobs/{job['id']}/parts/{live[0]['id']}/return", {"quantity": "9"}, expect=(422,))
    assert too_many.status_code == 422
    post(client, shop, f"/jobs/{job['id']}/parts/{live[0]['id']}/return", {"quantity": "3"})
    assert stock_on_hand(shop) == before


# --------------------------------------------------------------------------- charges, storage, deposits
def test_towing_is_a_charge_on_the_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Breakdown")
    out = post(client, shop, f"/jobs/{job['id']}/charges", {
        "kind": "towing", "description": "Tow from Thika Road", "unit_price": "3000"}).json()
    assert out["charges"][0]["total"] == "3000.00" and out["totals"]["charges_total"] == "3000.00"
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()
    assert done["totals"]["total"] == "3100.00"
    assert not any("check the tax items" in (e["note"] or "") for e in done["events"])


def test_storage_is_charged_after_the_free_days(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "storage_fee_per_day": "50", "storage_grace_days": 3})
    try:
        job = new_job(client, shop, title="Forgotten car")
        post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
        for code in ("in_progress", "ready"):
            assert move(client, shop, job, code).status_code == 200
        with system(shop) as s:
            s.execute(text("update jobs.job set ready_at = now() - interval '10 days' where id = :i"),
                      {"i": job["id"]})
        seen = get_job(client, shop, job)
        assert seen["storage_days"] == 7 and seen["storage_fee"] == "350.00"
        charged = post(client, shop, f"/jobs/{job['id']}/storage-fee").json()
        assert charged["charges"][0]["kind"] == "storage" and charged["totals"]["charges_total"] == "350.00"
        assert post(client, shop, f"/jobs/{job['id']}/storage-fee").json()["charges"].__len__() == 1       # not twice
        waived = client.post(f"{JOBS}/jobs/{job['id']}/storage-fee/waive", headers=shop["owner"])
        assert Dec(waived.json()["storage_fee"]) == 0
    finally:
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "storage_fee_per_day": "0"})


def test_a_deposit_is_a_payment_on_account(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Order: wedding suit")
    done = post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "500", "method": "cash"}).json()
    assert done["deposit_amount"] == "500.00"
    again = post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "250.50", "method": "cash"}).json()
    assert again["deposit_amount"] == "750.50"
    with system(shop) as s:
        n = s.execute(text("select count(*) from payments.payment where party_id = :c and direction = 'in'"),
                      {"c": shop["customer"]["id"]}).scalar_one()
    assert n >= 2
    assert any(e["kind"] == "deposit" for e in again["events"])
    bad = post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "0"}, expect=(422,))
    assert bad.status_code == 422


# --------------------------------------------------------------------------- release on payment
def finished(client, shop, title="Brake job"):  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title=title)
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    for code in ("in_progress", "ready"):
        assert move(client, shop, job, code).status_code == 200
    return job


def test_release_before_payment_warns_and_a_business_can_make_it_a_block(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={"release_unpaid": "warn"})
    try:
        # an account customer (credit terms) is released without a warning
        job = finished(client, shop, "On account")
        post(client, shop, f"/jobs/{job['id']}/invoice")
        assert get_job(client, shop, job)["release"]["ok"] is True
        # a customer with no terms and an unpaid invoice is warned
        walk = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
            "company_id": co, "branch_id": str(shop["branch_id"]), "title": "Cash job",
            "customer_name": "Passer-by"}).json()
        post(client, shop, f"/jobs/{walk['id']}/labour", {"hours": "1"})
        for code in ("in_progress", "ready"):
            assert move(client, shop, walk, code).status_code == 200
        unpaid = get_job(client, shop, walk)["release"]
        assert unpaid["ok"] is False and unpaid["invoiced"] is False and "not been invoiced" in unpaid["message"]
        asked = client.post(f"{JOBS}/jobs/{walk['id']}/collect", headers=shop["owner"], json={})
        assert asked.status_code == 409 and "Confirm to hand" in asked.text
        let = client.post(f"{JOBS}/jobs/{walk['id']}/collect", headers=shop["owner"], json={
            "acknowledge_unpaid": True, "collected_by_name": "Passer-by", "odometer_out": "100"})
        assert let.status_code == 200, let.text
        assert any(e["kind"] == "release" for e in let.json()["events"]) and let.json()["odometer_out"] == "100.0"
        # block: refused outright
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "release_unpaid": "block"})
        other = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
            "company_id": co, "branch_id": str(shop["branch_id"]), "title": "Another", "customer_name": "Stranger"}).json()
        post(client, shop, f"/jobs/{other['id']}/labour", {"hours": "1"})
        for code in ("in_progress", "ready"):
            assert move(client, shop, other, code).status_code == 200
        blocked = client.post(f"{JOBS}/jobs/{other['id']}/collect", headers=shop["owner"], json={
            "acknowledge_unpaid": True})
        assert blocked.status_code == 422 and "before it is paid" in blocked.text
        # paying the invoice clears it
        post(client, shop, f"/jobs/{other['id']}/invoice", {"pay_method": "cash"})
        assert client.post(f"{JOBS}/jobs/{other['id']}/collect", headers=shop["owner"], json={}).status_code == 200
    finally:
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "release_unpaid": "off"})


# --------------------------------------------------------------------------- bays and courtesy cars
def test_a_bay_holds_one_job_at_a_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, br = str(shop["company_id"]), str(shop["branch_id"])
    bay = client.post(f"{JOBS}/bays", headers=shop["owner"], json={"company_id": co, "branch_id": br, "name": "Bay 1"})
    assert bay.status_code == 201, bay.text
    assert client.post(f"{JOBS}/bays", headers=shop["owner"], json={
        "company_id": co, "branch_id": br, "name": "bay 1"}).status_code == 409
    one, two = new_job(client, shop, title="One"), new_job(client, shop, title="Two")
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1, hours=1)
    slot = {"bay_id": bay.json()["id"], "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=3)).isoformat()}
    booked = post(client, shop, f"/jobs/{one['id']}/bay-bookings", slot).json()
    assert booked["bay_bookings"][0]["bay_name"] == "Bay 1"
    clash = {**slot, "starts_at": (start + timedelta(hours=2)).isoformat(),
             "ends_at": (start + timedelta(hours=5)).isoformat()}
    assert post(client, shop, f"/jobs/{two['id']}/bay-bookings", clash, expect=(409,)).status_code == 409
    after = {**slot, "starts_at": (start + timedelta(hours=3)).isoformat(),
             "ends_at": (start + timedelta(hours=5)).isoformat()}
    post(client, shop, f"/jobs/{two['id']}/bay-bookings", after)
    board = client.get(f"{JOBS}/bay-board", headers=shop["owner"], params={
        "company_id": co, "branch_id": br, "day": start.date().isoformat(), "days": 3}).json()
    assert [b["job_number"] for b in board["bookings"]] == [one["number"], two["number"]]
    assert [b["name"] for b in board["bays"]] == ["Bay 1"]
    cancel = client.delete(f"{JOBS}/bay-bookings/{booked['bay_bookings'][0]['id']}", headers=shop["owner"])
    assert cancel.status_code == 200 and cancel.json()["bay_bookings"] == []
    again = post(client, shop, f"/jobs/{two['id']}/bay-bookings", {
        **slot, "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=3)).isoformat()})
    assert len(again.json()["bay_bookings"]) == 2          # the freed slot can be taken


def test_a_courtesy_car_is_out_on_one_loan_at_a_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    car = client.post(f"{JOBS}/assets", headers=shop["owner"], json={
        "company_id": co, "label": "Courtesy Vitz KCZ 001A", "kind": "courtesy-car"}).json()
    one, two = new_job(client, shop, title="Long repair"), new_job(client, shop, title="Other repair")
    due = (date.today() + timedelta(days=-1)).isoformat()
    out = post(client, shop, f"/jobs/{one['id']}/loans", {
        "asset_id": car["id"], "odometer_out": "12000", "fuel_out": "full", "due_at": due}).json()
    assert out["loans"][0]["asset_label"] == "Courtesy Vitz KCZ 001A" and out["loans"][0]["overdue"] is True
    again = post(client, shop, f"/jobs/{two['id']}/loans", {"asset_id": car["id"]}, expect=(409,))
    assert "already out" in again.text
    listed = client.get(f"{JOBS}/loans/out", headers=shop["owner"], params={"company_id": co}).json()
    assert [x["job_number"] for x in listed] == [one["number"]]
    low = post(client, shop, f"/loans/{out['loans'][0]['id']}/return", {"odometer_in": "11000"}, expect=(422,))
    assert low.status_code == 422
    back = post(client, shop, f"/loans/{out['loans'][0]['id']}/return", {"odometer_in": "12150", "fuel_in": "1/2"}).json()
    assert back["loans"][0]["in_at"] is not None and back["loans"][0]["overdue"] is False
    post(client, shop, f"/jobs/{two['id']}/loans", {"asset_id": car["id"]})
    notcar = client.post(f"{JOBS}/assets", headers=shop["owner"], json={"company_id": co, "label": "Hammer"}).json()
    post(client, shop, f"/jobs/{two['id']}/loans", {"asset_id": notcar["id"]}, expect=(422,))


# --------------------------------------------------------------------------- job types
def test_a_job_type_brings_its_checklist_and_warranty(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    template = client.post(f"{JOBS}/checklist-templates", headers=shop["owner"], json={
        "company_id": co, "name": "Body repair intake", "items": ["Photos of damage", "Valuables removed"]}).json()
    jt = client.post(f"{JOBS}/job-types", headers=shop["owner"], json={
        "company_id": co, "name": "Body repair", "checklist_template_id": template["id"], "default_warranty_days": 90})
    assert jt.status_code == 201, jt.text
    job = new_job(client, shop, title="Dented door", job_type_code="body-repair")
    assert [c["label"] for c in job["checklist"]] == ["Photos of damage", "Valuables removed"]
    assert job["warranty_days"] == 90 and job["job_type_code"] == "body-repair"
    bad = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "title": "x", "customer_name": "a",
        "job_type_code": "nope"})
    assert bad.status_code == 422


def test_catalogue_changes_need_the_settings_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    for path, body in (("/work-types", {"company_id": co, "name": "X"}),
                       ("/labour-tasks", {"company_id": co, "name": "X", "standard_hours": "1"}),
                       ("/part-categories", {"company_id": co, "name": "X"}),
                       ("/job-types", {"company_id": co, "name": "X"}),
                       ("/bays", {"company_id": co, "branch_id": str(shop["branch_id"]), "name": "X"})):
        assert client.post(f"{JOBS}{path}", headers=shop["tech"], json=body).status_code == 403
        assert client.get(f"{JOBS}{path}", headers=shop["tech"], params={"company_id": co}).status_code == 200


@pytest.mark.parametrize("day", ["9999-12-31", "0001-01-01"])
def test_the_bay_board_refuses_extreme_dates(client, shop, day) -> None:  # type: ignore[no-untyped-def]
    params = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"])}
    assert client.get(f"{JOBS}/bay-board", headers=shop["owner"], params={**params, "day": day}).status_code == 422
    assert client.get(f"{JOBS}/bay-board", headers=shop["owner"], params={**params, "day": "2026-06-01"}).status_code == 200
