"""Jobs and Repairs: taking items in, the stages as data, parts from stock, labour, estimates and the customer's answer,
invoicing and locking, collection and warranty, the board, scope, privacy, custom fields and seeding."""

from decimal import Decimal as Dec  # noqa: N817
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import balance
from tests.jobs_helpers import JOBS, make_jobs_shop, move, new_job, stage, stock_on_hand
from tests.payments_helpers import one
from tests.stock_helpers import system
from ziira.modules.jobs import public as jobs_public
from ziira.modules.jobs.domain.workflow import Definition, StatusDef
from ziira.sdk import PackData, store_credential


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_jobs_shop(client, registry, "Jobs Garage")


def get_job(client, shop, job, who="owner"):  # type: ignore[no-untyped-def]
    r = client.get(f"{JOBS}/jobs/{job['id']}", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- taking an item in
def test_an_item_is_taken_in_with_its_asset_and_a_checklist(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    template = client.post(f"{JOBS}/checklist-templates", headers=shop["owner"], json={
        "company_id": co, "name": "Vehicle intake", "asset_kind": "vehicle",
        "items": ["Fuel level noted", "Spare wheel present", "  ", "Photos taken"]})
    assert template.status_code == 201 and template.json()["items"] == ["Fuel level noted", "Spare wheel present",
                                                                         "Photos taken"]
    job = new_job(client, shop, new_asset={"label": "Toyota Corolla KAA 123B", "kind": "vehicle",
                                           "identifiers": {"plate": "KAA 123B", "mileage": "120000", "empty": " "}},
                  condition_notes="Scratch on rear bumper", checklist_template_id=template.json()["id"],
                  promised_at="2026-12-01")
    assert job["number"] == "JOB-HQ-000001" and job["status"]["code"] == "received"
    assert job["asset"]["label"] == "Toyota Corolla KAA 123B"
    assert [c["label"] for c in job["checklist"]] == ["Fuel level noted", "Spare wheel present", "Photos taken"]
    assert job["customer_name"] == "Wanjiku Motors" and job["customer_phone"] == "254712345678"
    assert [e["kind"] for e in job["events"]] == ["received"]
    asset = client.get(f"{JOBS}/assets/{job['asset']['id']}", headers=shop["owner"]).json()
    assert asset["identifiers"] == {"plate": "KAA 123B", "mileage": "120000"}            # blank identifiers dropped
    assert asset["customer_id"] == shop["customer"]["id"] and [j["number"] for j in asset["jobs"]] == [job["number"]]
    # editing the checklist template does not change the job that copied it
    client.patch(f"{JOBS}/checklist-templates/{template.json()['id']}", headers=shop["owner"], json={"items": ["New"]})
    assert len(get_job(client, shop, job)["checklist"]) == 3
    shop["first_job"] = job


def test_the_asset_keeps_a_history_of_many_jobs(client, shop) -> None:  # type: ignore[no-untyped-def]
    first = shop["first_job"]
    second = new_job(client, shop, asset_id=first["asset"]["id"], title="Oil change")
    assert second["asset"]["id"] == first["asset"]["id"] and second["number"] == "JOB-HQ-000002"
    asset = client.get(f"{JOBS}/assets/{first['asset']['id']}", headers=shop["owner"]).json()
    assert [j["number"] for j in asset["jobs"]] == ["JOB-HQ-000002", "JOB-HQ-000001"]
    found = client.get(f"{JOBS}/assets", headers=shop["owner"], params={"search": "kaa 123"}).json()
    assert [a["id"] for a in found] == [first["asset"]["id"]]
    assert [j["number"] for j in client.get(f"{JOBS}/jobs", headers=shop["owner"],
                                            params={"search": "KAA 123B"}).json()] == ["JOB-HQ-000002", "JOB-HQ-000001"]


def test_a_job_needs_a_customer_and_a_title_and_a_real_item(client, shop) -> None:  # type: ignore[no-untyped-def]
    base = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "x"}
    assert client.post(f"{JOBS}/jobs", headers=shop["owner"], json=base).status_code == 422          # nobody named
    walk_in = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={**base, "customer_name": "Walk-in Joe"})
    assert walk_in.status_code == 201 and walk_in.json()["customer_id"] is None
    assert client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        **base, "customer_name": "x", "asset_id": str(uuid4())}).status_code == 404
    assert client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        **base, "customer_id": str(uuid4())}).status_code == 422


def test_a_retry_from_the_counter_makes_one_job(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Phone screen",
            "customer_name": "Retry Rita"}
    headers = {**shop["owner"], "Idempotency-Key": "counter-retry-1"}
    a, b = (client.post(f"{JOBS}/jobs", headers=headers, json=body) for _ in range(2))
    assert a.status_code == 201 and b.json()["id"] == a.json()["id"]
    assert one(shop, "select count(*) from jobs.job where title = 'Phone screen'") == 1


# --------------------------------------------------------------------------- the stages are data
def test_a_job_moves_only_along_the_allowed_moves(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Alternator")
    assert move(client, shop, job, "ready").status_code == 422                       # received -> ready is not allowed
    assert move(client, shop, job, "diagnosing", note="Looks like the belt").status_code == 200
    assert move(client, shop, job, "diagnosing").status_code == 422                  # already there
    detail = get_job(client, shop, job)
    assert detail["status"]["code"] == "diagnosing"
    assert [e["kind"] for e in detail["events"]] == ["received", "status"]
    assert detail["events"][1]["from_status"] == "Received" and detail["events"][1]["note"] == "Looks like the belt"
    assert {n for n in detail["next_status_ids"]} == {stage(client, shop, c) for c in (
        "quoted", "in_progress", "waiting_for_parts", "ready", "cancelled")}


def test_a_business_edits_its_own_stages_and_moves(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    made = client.post(f"{JOBS}/statuses", headers=shop["owner"], json={
        "company_id": co, "code": "painting", "name": "In the paint booth", "kind": "open"})
    assert made.status_code == 201 and made.json()["role"] is None
    assert client.post(f"{JOBS}/statuses", headers=shop["owner"], json={
        "company_id": co, "code": "painting", "name": "Again", "kind": "open"}).status_code == 409
    assert client.post(f"{JOBS}/statuses", headers=shop["owner"], json={
        "company_id": co, "code": "Bad Code", "name": "x", "kind": "open"}).status_code == 422
    # a role can be held by one stage only
    assert client.patch(f"{JOBS}/statuses/{made.json()['id']}", headers=shop["owner"],
                        json={"role": "ready"}).status_code == 409
    sid = made.json()["id"]
    moves = client.put(f"{JOBS}/statuses/{stage(client, shop, 'in_progress')}/moves", headers=shop["owner"], json={
        "to_status_ids": [sid, stage(client, shop, "ready")]})
    assert moves.status_code == 200 and sid in moves.json()["moves_to"]
    job = new_job(client, shop, title="Respray door")
    for code in ("in_progress", "painting"):
        step = move(client, shop, job, code) if code == "in_progress" else None
        if code == "painting":
            step = client.post(f"{JOBS}/jobs/{job['id']}/status", headers=shop["owner"], json={"to_status_id": sid})
        assert step.status_code == 200, step.text
    # a stage with jobs in it cannot be switched off or deleted
    assert client.patch(f"{JOBS}/statuses/{sid}", headers=shop["owner"], json={"is_active": False}).status_code == 422
    assert client.delete(f"{JOBS}/statuses/{sid}", headers=shop["owner"]).status_code == 422
    # the first stage cannot be switched off
    assert client.patch(f"{JOBS}/statuses/{stage(client, shop, 'received')}", headers=shop["owner"],
                        json={"is_active": False}).status_code == 422


def test_only_people_with_settings_permission_change_stages(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "code": "x_stage", "name": "X", "kind": "open"}
    for who in ("tech", "manager", "cashier"):
        assert client.post(f"{JOBS}/statuses", headers=shop[who], json=body).status_code == 403
    assert client.get(f"{JOBS}/workflow", headers=shop["tech"], params={"company_id": str(shop["company_id"])}
                      ).status_code == 200


def test_a_pack_seeds_stages_without_changing_what_exists(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = client.get(f"{JOBS}/workflow", headers=shop["owner"], params={"company_id": str(shop["company_id"]),
                                                                           "include_inactive": True}).json()
    custom = Definition(
        [StatusDef("received", "Renamed by the pack", "open", "initial"), StatusDef("fitting", "Fitting", "open"),
         StatusDef("final_check", "Final check", "waiting", "ready")],        # 'ready' is taken: added without a role
        [("in_progress", "fitting"), ("fitting", "final_check"), ("nowhere", "fitting")])
    with system(shop) as s:
        first = jobs_public.seed_statuses(s, shop["company_id"], custom)
        again = jobs_public.seed_statuses(s, shop["company_id"], custom)
    assert first == (2, 2) and again == (0, 0)
    after = {s_["code"]: s_ for s_ in client.get(f"{JOBS}/workflow", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "include_inactive": True}).json()}
    assert after["received"]["name"] == "Received" and len(after) == len(before) + 2     # nothing was changed
    assert after["final_check"]["role"] is None and after["fitting"]["moves_to"] == [after["final_check"]["id"]]
    assert jobs_public.parse_definition({"statuses": [{"code": "a", "name": "A", "kind": "open"}],
                                         "moves": []}).statuses[0].code == "a"


# --------------------------------------------------------------------------- parts and labour
def test_stock_parts_leave_stock_at_the_ledger_cost_and_come_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Fit pads")
    stock0, cogs0, inv0 = stock_on_hand(shop), balance(shop, "5000"), balance(shop, "1200")
    r = client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "product_id": shop["cement"], "quantity": "2"})
    assert r.status_code == 201, r.text
    part = r.json()["parts"][0]
    # the selling price is the list price, 116.00 with VAT 16% inside: 2 x 116.00 = 232.00, tax 232 x 16 / 116 = 32.00
    assert Dec(part["unit_price"]) == 116 and Dec(part["total"]) == 232 and Dec(part["tax"]) == 32
    assert Dec(part["unit_cost"]) == 50 and Dec(part["cost_value"]) == 100 and part["is_stock"]
    assert stock_on_hand(shop) == stock0 - 2
    assert balance(shop, "5000") == cogs0 + 100 and balance(shop, "1200") == inv0 - 100        # cost of parts is booked
    assert Dec(r.json()["totals"]["cost"]) == 100
    # a hand-priced part takes no stock
    r = client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "description": "Brake fluid (bought in)", "quantity": "1", "unit_price": "58.00"})
    assert r.status_code == 201 and stock_on_hand(shop) == stock0 - 2
    # taking the stock part off puts it back at its cost
    removed = client.delete(f"{JOBS}/jobs/{job['id']}/parts/{part['id']}", headers=shop["owner"])
    assert removed.status_code == 200 and stock_on_hand(shop) == stock0
    assert balance(shop, "5000") == cogs0 and balance(shop, "1200") == inv0
    assert [p["voided"] for p in removed.json()["parts"]] == [True, False]
    assert Dec(removed.json()["totals"]["parts_total"]) == 58                   # voided parts are not counted
    again = client.delete(f"{JOBS}/jobs/{job['id']}/parts/{part['id']}", headers=shop["owner"])
    assert again.status_code == 200 and stock_on_hand(shop) == stock0           # asking twice changes nothing


def test_parts_need_stock_a_price_and_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Too many pads")
    too_many = client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "product_id": shop["cement"], "quantity": "500"})
    assert too_many.status_code == 422 and "Not enough stock" in too_many.text
    assert one(shop, "select count(*) from jobs.job_part where job_id = :j", j=UUID(job["id"])) == 0
    assert client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "description": "No price", "quantity": "1"}).status_code == 422
    assert client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "product_id": shop["cement"], "quantity": "0"}).status_code == 422
    # a cashier can take items in but may not use stock; the storekeeper may use stock but not take items in
    body = {"product_id": shop["cement"], "quantity": "1"}
    assert client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["cashier"], json=body).status_code == 403
    assert client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["storekeeper"], json=body).status_code == 201
    assert client.post(f"{JOBS}/jobs", headers=shop["storekeeper"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "x",
        "customer_name": "y"}).status_code == 403


def test_costs_are_shown_only_to_people_who_may_see_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Cost privacy")
    client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={"product_id": shop["cement"],
                                                                              "quantity": "1"})
    seen = get_job(client, shop, job, "tech")
    assert seen["parts"][0]["unit_cost"] is None and seen["totals"]["cost"] is None
    assert Dec(get_job(client, shop, job)["totals"]["cost"]) == 50


def test_labour_is_hours_times_a_rate(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Labour job")
    r = client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["tech"], json={
        "hours": "1.5", "description": "Diagnose"})
    assert r.status_code == 201, r.text
    first = r.json()["labour"][0]
    assert Dec(first["rate"]) == 100 and Dec(first["total"]) == 150 and Dec(first["tax"]) == Dec("20.69")   # 150 x 16 / 116
    assert first["assignee_id"] == shop["users"]["tech"] and first["source"] == "manual"
    r = client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["tech"], json={
        "hours": "0.25", "description": "Road test", "rate": "80.00"})
    assert [Dec(x["total"]) for x in r.json()["labour"]] == [150, 20]
    assert Dec(r.json()["totals"]["labour_total"]) == 170
    assert client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["tech"], json={"hours": "0"}).status_code == 422
    gone = client.delete(f"{JOBS}/jobs/{job['id']}/labour/{first['id']}", headers=shop["tech"])
    assert Dec(gone.json()["totals"]["labour_total"]) == 20


def test_time_from_another_unit_is_added_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Timer job")
    source = uuid4()
    with system(shop) as s:
        first = jobs_public.add_labour_line(s, UUID(job["id"]), hours=Dec("2"), description="Timer", source="timer",
                                            source_id=source)
        second = jobs_public.add_labour_line(s, UUID(job["id"]), hours=Dec("2"), description="Timer", source="timer",
                                             source_id=source)
    assert first == second
    assert len(get_job(client, shop, job)["labour"]) == 1


# --------------------------------------------------------------------------- estimates
def test_an_estimate_is_versioned_sent_and_approved_by_staff(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Estimate me")
    client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["owner"], json={"hours": "3", "description": "Labour"})
    made = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["tech"], json={
        "from_job": True, "lines": [], "notes": "Valid for a week"})
    assert made.status_code == 201, made.text
    est = made.json()
    # 3 h x 100.00 = 300.00 with 16% inside: 300 x 16 / 116 = 41.38; net 258.62
    assert est["version"] == 1 and est["status"] == "draft" and Dec(est["total"]) == 300
    assert Dec(est["tax"]) == Dec("41.38") and Dec(est["net"]) == Dec("258.62")
    assert client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["tech"], json={
        "from_job": True}).status_code == 409                                          # one draft at a time
    changed = client.patch(f"{JOBS}/estimates/{est['id']}", headers=shop["tech"], json={"lines": [
        {"kind": "labour", "description": "Labour", "quantity": "2", "unit_price": "100.00"},
        {"kind": "part", "description": "Pads", "quantity": "1", "unit_price": "116.00"}]})
    assert Dec(changed.json()["total"]) == 316 and len(changed.json()["lines"]) == 2
    sent = client.post(f"{JOBS}/estimates/{est['id']}/send", headers=shop["tech"], json={})
    assert sent.status_code == 200 and sent.json()["link_path"].startswith("/job-approval/")
    assert sent.json()["estimate"]["status"] == "sent" and sent.json()["estimate"]["valid_until"]
    after = get_job(client, shop, job)
    assert after["status"]["code"] == "quoted"                                            # sending moved the job
    assert client.patch(f"{JOBS}/estimates/{est['id']}", headers=shop["tech"], json={"notes": "x"}).status_code == 409
    # a revised estimate is version 2 and replaces version 1 once sent
    v2 = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["tech"], json={"lines": [
        {"kind": "labour", "description": "More labour", "quantity": "1", "unit_price": "100.00"}]}).json()
    assert v2["version"] == 2
    client.post(f"{JOBS}/estimates/{v2['id']}/send", headers=shop["tech"], json={})
    assert [e["status"] for e in get_job(client, shop, job)["estimates"]] == ["superseded", "sent"]
    # the customer said yes on the phone
    yes = client.post(f"{JOBS}/estimates/{v2['id']}/decision", headers=shop["tech"], json={
        "approved": True, "note": "Called at 10:15", "customer_name": "Wanjiku"})
    assert yes.status_code == 200 and yes.json()["status"] == "approved" and yes.json()["decision_channel"] == "staff"
    done = get_job(client, shop, job)
    assert done["status"]["code"] == "approved"
    approval = [e for e in done["events"] if e["kind"] == "approval"]
    assert len(approval) == 1 and "Called at 10:15" in approval[0]["note"] and "Wanjiku" in approval[0]["note"]
    assert client.post(f"{JOBS}/estimates/{v2['id']}/decision", headers=shop["tech"], json={
        "approved": False}).status_code == 409                                          # answered once


def test_the_customer_answers_through_a_link_that_works_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Link job")
    est = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={"lines": [
        {"kind": "part", "description": "Clutch kit", "quantity": "1", "unit_price": "232.00"}]}).json()
    link = client.post(f"{JOBS}/estimates/{est['id']}/send", headers=shop["owner"], json={}).json()["link_path"]
    token = link.removeprefix("/job-approval/")
    url = f"{JOBS}/public/job-approval/{token}"
    page = client.get(url)                                                             # no sign-in
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["state"] == "open" and Dec(body["total"]) == 232 and body["job_number"] == job["number"]
    assert [x["description"] for x in body["lines"]] == ["Clutch kit"]
    assert "customer" not in page.text.lower() and "Wanjiku" not in page.text and "254712345678" not in page.text
    assert client.get(f"{JOBS}/public/job-approval/{token[:-3]}xyz").status_code == 404
    assert client.get(f"{JOBS}/public/job-approval/not-a-token").status_code == 404
    assert client.post(url, json={"approve": True, "name": " "}).status_code == 422          # a name is needed
    ok = client.post(url, json={"approve": True, "name": "Wanjiku Mwangi", "note": "Go ahead"})
    assert ok.status_code == 200 and ok.json() == {"state": "approved"}
    assert client.post(url, json={"approve": False, "name": "Someone else"}).status_code == 422     # one answer only
    assert client.get(url).json()["state"] == "approved"
    after = get_job(client, shop, job)
    assert after["status"]["code"] == "approved"
    assert after["estimates"][0]["decision_channel"] == "link" and after["estimates"][0]["decided_by_name"] == "Wanjiku Mwangi"
    # sending the estimate again would have ended an old link: a declined one leaves the job where it is
    job2 = new_job(client, shop, title="Decline job")
    est2 = client.post(f"{JOBS}/jobs/{job2['id']}/estimates", headers=shop["owner"], json={"lines": [
        {"kind": "labour", "description": "Work", "quantity": "1"}]}).json()
    token2 = client.post(f"{JOBS}/estimates/{est2['id']}/send", headers=shop["owner"], json={}).json()["link_path"] \
        .removeprefix("/job-approval/")
    no = client.post(f"{JOBS}/public/job-approval/{token2}", json={"approve": False, "name": "Pat"})
    assert no.status_code == 200 and no.json()["state"] == "declined"
    assert get_job(client, shop, job2)["status"]["code"] == "quoted"


def test_an_expired_link_cannot_be_answered(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Old link")
    est = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={
        "valid_until": "2026-01-01", "lines": [{"kind": "labour", "description": "Work", "quantity": "1"}]}).json()
    token = client.post(f"{JOBS}/estimates/{est['id']}/send", headers=shop["owner"], json={}).json()["link_path"] \
        .removeprefix("/job-approval/")
    url = f"{JOBS}/public/job-approval/{token}"
    assert client.get(url).json()["state"] == "expired"
    assert client.post(url, json={"approve": True, "name": "Late Larry"}).status_code == 422
    assert get_job(client, shop, job)["status"]["code"] == "quoted"


# --------------------------------------------------------------------------- invoicing and the lock
def test_a_job_is_invoiced_once_and_then_locked(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Invoice me")
    stock0 = stock_on_hand(shop)
    client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={"product_id": shop["cement"],
                                                                              "quantity": "2"})
    client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["owner"], json={"hours": "1.5", "description": "Fit"})
    assert client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["cashier"]).status_code == 403
    before = {c: balance(shop, c) for c in ("1100", "4000", "2200", "5000")}
    r = client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["owner"])
    assert r.status_code == 200, r.text
    done = r.json()
    # parts 2 x 116.00 = 232.00 (tax 32.00) + labour 1.5 h x 100.00 = 150.00 (tax 20.69): 382.00 with 52.69 tax
    assert Dec(done["totals"]["total"]) == 382 and Dec(done["totals"]["tax"]) == Dec("52.69")
    assert done["invoice_number"].startswith("INV-HQ-") and done["locked"]
    inv = client.get(f"/api/v1/pos/invoices/{done['invoice_id']}", headers=shop["owner"]).json()
    assert Dec(inv["total"]) == 382 and Dec(inv["tax_total"]) == Dec("52.69") and inv["customer_id"] == shop["customer"]["id"]
    assert stock_on_hand(shop) == stock0 - 2                                  # the invoice did not take the parts again
    after = {c: balance(shop, c) for c in before}
    assert after["1100"] - before["1100"] == 382 and after["5000"] - before["5000"] == 0     # cost was booked at issue
    # locked: no new parts, labour, tasks, estimate, no edits; notes, warranty, collection still work
    assert client.post(f"{JOBS}/jobs/{job['id']}/parts", headers=shop["owner"], json={
        "description": "x", "quantity": "1", "unit_price": "1"}).status_code == 409
    assert client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["owner"], json={"hours": "1"}).status_code == 409
    assert client.post(f"{JOBS}/jobs/{job['id']}/tasks", headers=shop["owner"], json={"title": "x"}).status_code == 409
    assert client.patch(f"{JOBS}/jobs/{job['id']}", headers=shop["owner"], json={"title": "New title"}).status_code == 409
    assert client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={
        "from_job": True}).status_code == 409
    assert client.delete(f"{JOBS}/jobs/{job['id']}/parts/{done['parts'][0]['id']}",
                         headers=shop["owner"]).status_code == 409
    assert client.post(f"{JOBS}/jobs/{job['id']}/notes", headers=shop["owner"], json={"text": "Paid in full"}
                       ).status_code == 201
    warranty = client.patch(f"{JOBS}/jobs/{job['id']}", headers=shop["owner"], json={"warranty_days": 90})
    assert warranty.status_code == 200 and warranty.json()["warranty_days"] == 90
    assert client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["owner"]).status_code == 409
    assert one(shop, "select count(*) from pos.sales_invoice where source_type = 'job' and source_id = :j",
               j=UUID(job["id"])) == 1
    shop["invoiced_job"] = done


def test_invoicing_needs_something_to_charge_and_a_walk_in_gets_a_customer_record(client, shop) -> None:  # type: ignore[no-untyped-def]
    empty = new_job(client, shop, title="Nothing done")
    r = client.post(f"{JOBS}/jobs/{empty['id']}/invoice", headers=shop["owner"])
    assert r.status_code == 422 and "no parts or labour" in r.text
    walk_in = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Walk-in",
        "customer_name": "Walk-in Joe"}).json()
    client.post(f"{JOBS}/jobs/{walk_in['id']}/labour", headers=shop["owner"], json={"hours": "1"})
    assert get_job(client, shop, walk_in)["can_invoice"] is True              # no customer record is needed any more
    unpaid = client.post(f"{JOBS}/jobs/{walk_in['id']}/invoice", headers=shop["owner"])
    assert unpaid.status_code == 422 and "credit" in unpaid.text.lower()          # a stranger has no credit: pay now
    made = client.post(f"{JOBS}/jobs/{walk_in['id']}/invoice", headers=shop["owner"], json={"pay_method": "cash"})
    assert made.status_code == 200, made.text
    assert made.json()["customer_id"] is not None and made.json()["invoice_number"]
    assert made.json()["release"]["ok"] is True


# --------------------------------------------------------------------------- collection, warranty, return visits
def test_collection_starts_the_warranty_and_a_return_visit_is_linked(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["invoiced_job"]
    # walk the invoiced job to the end of the default workflow (it was never moved)
    for code in ("in_progress", "ready"):
        assert move(client, shop, job, code).status_code == 200
    gone = client.post(f"{JOBS}/jobs/{job['id']}/collect", headers=shop["owner"], json={
        "collected_by_name": "Brother of Wanjiku", "note": "ID checked"})
    assert gone.status_code == 200, gone.text
    out = gone.json()
    today = one(shop, "select (collected_at at time zone 'UTC')::date from jobs.job where id = :j", j=UUID(job["id"]))
    assert out["status"]["code"] == "collected" and out["collected_by_name"] == "Brother of Wanjiku"
    assert out["warranty_ends"] == str(today.replace(year=today.year) + (today - today) + __import__("datetime").timedelta(days=90))
    assert client.post(f"{JOBS}/jobs/{job['id']}/collect", headers=shop["owner"], json={}).status_code in (409, 422)
    visit = client.post(f"{JOBS}/jobs/{job['id']}/return-visit", headers=shop["owner"], json={})
    assert visit.status_code == 201, visit.text
    v = visit.json()
    assert v["is_rework"] and v["rework_of"]["number"] == job["number"] and v["title"].startswith("Return visit")
    assert v["customer_id"] == job["customer_id"] and v["asset"] == job["asset"]
    original = get_job(client, shop, job)
    assert [(x["number"], x["in_warranty"]) for x in original["return_visits"]] == [(v["number"], True)]
    # a visit after the warranty ended is still allowed, and says so
    with system(shop) as s:
        s.execute(text("update jobs.job set warranty_ends = current_date - 1 where id = :j"), {"j": job["id"]})
    late = client.post(f"{JOBS}/jobs/{job['id']}/return-visit", headers=shop["owner"], json={"title": "Squeak again"})
    assert late.status_code == 201
    shop["rework_pair"] = (job, v)
    flags = get_job(client, shop, job)["return_visits"]
    assert sorted(x["in_warranty"] for x in flags) == [False, True]
    # only a collected job can have a return visit
    fresh = new_job(client, shop, title="Not collected")
    assert client.post(f"{JOBS}/jobs/{fresh['id']}/return-visit", headers=shop["owner"], json={}).status_code == 422


def test_the_customer_is_told_when_the_item_is_ready(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = shop["company_id"]
    with system(shop) as s:           # an SMS channel that is set up (nothing is sent: messages are only queued)
        store_credential(s, company_id=co, provider="sms", label="Test SMS", secret={"key": "x"})
    job = new_job(client, shop, title="Phone screen", new_asset={"label": "Phone X"})
    assert move(client, shop, job, "in_progress").status_code == 200
    assert move(client, shop, job, "ready").status_code == 200
    rows = one(shop, "select count(*) from kernel.notification where ref_type = 'job' and ref_id = :j", j=UUID(job["id"]))
    assert rows == 1
    text_ = one(shop, "select body from kernel.notification where ref_type = 'job' and ref_id = :j", j=UUID(job["id"]))
    assert job["number"] in text_ and "Phone X" in text_ and "ready for collection" in text_
    # a business can switch the message off
    client.patch(f"{JOBS}/settings", params={"company_id": str(co)}, headers=shop["owner"],
                 json={"tell_customer_when_ready": False})
    other = new_job(client, shop, title="Quiet one")
    move(client, shop, other, "in_progress")
    move(client, shop, other, "ready")
    assert one(shop, "select count(*) from kernel.notification where ref_type = 'job' and ref_id = :j",
               j=UUID(other["id"])) == 0
    client.patch(f"{JOBS}/settings", params={"company_id": str(co)}, headers=shop["owner"],
                 json={"tell_customer_when_ready": True})


# --------------------------------------------------------------------------- the board and the list
def test_the_board_groups_jobs_by_stage_and_filters(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    mine = new_job(client, shop, title="Board: mine", assignee_id=shop["users"]["tech"], promised_at="2026-01-01")
    new_job(client, shop, title="Board: nobody", promised_at="2999-01-01")
    board = client.get(f"{JOBS}/jobs/board", headers=shop["owner"], params={"company_id": co}).json()
    assert [s["code"] for s in board["statuses"]][:3] == ["received", "diagnosing", "quoted"]
    titles = {j["title"] for j in board["jobs"]}
    assert {"Board: mine", "Board: nobody"} <= titles
    assert not any(j["status"]["kind"] == "closed" for j in board["jobs"])
    only = client.get(f"{JOBS}/jobs/board", headers=shop["owner"], params={
        "company_id": co, "assignee_id": shop["users"]["tech"]}).json()
    assert {j["title"] for j in only["jobs"]} == {"Board: mine"}
    late = client.get(f"{JOBS}/jobs/board", headers=shop["owner"], params={"company_id": co, "overdue": True}).json()
    assert {j["title"] for j in late["jobs"]} == {"Board: mine"} and late["jobs"][0]["overdue"]
    listed = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"assignee_id": shop["users"]["tech"]}).json()
    assert [j["id"] for j in listed] == [mine["id"]]
    closed = new_job(client, shop, title="Board: cancelled")
    move(client, shop, closed, "cancelled")
    assert "Board: cancelled" not in {j["title"] for j in client.get(
        f"{JOBS}/jobs/board", headers=shop["owner"], params={"company_id": co}).json()["jobs"]}
    assert "Board: cancelled" in {j["title"] for j in client.get(
        f"{JOBS}/jobs/board", headers=shop["owner"], params={"company_id": co, "include_closed": True}).json()["jobs"]}
    assert client.get(f"{JOBS}/jobs/board", headers=shop["owner"], params={"company_id": str(uuid4())}).status_code == 422


def test_tasks_have_a_person_and_a_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Tasks job")
    r = client.post(f"{JOBS}/jobs/{job['id']}/tasks", headers=shop["tech"], json={
        "title": "Order the part", "assignee_id": shop["users"]["tech"], "due_date": "2026-01-02"})
    assert r.status_code == 201
    task = r.json()["tasks"][0]
    assert task["overdue"] and task["assignee_name"] and task["done_at"] is None
    done = client.patch(f"{JOBS}/jobs/{job['id']}/tasks/{task['id']}", headers=shop["tech"], json={"done": True})
    assert done.json()["tasks"][0]["done_at"] and not done.json()["tasks"][0]["overdue"]
    summary = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"search": "Tasks job"}).json()[0]
    assert (summary["tasks_total"], summary["tasks_done"]) == (1, 1)
    assert client.post(f"{JOBS}/jobs/{job['id']}/tasks", headers=shop["tech"], json={
        "title": "x", "assignee_id": str(uuid4())}).status_code == 422
    assert client.delete(f"{JOBS}/jobs/{job['id']}/tasks/{task['id']}", headers=shop["tech"]).json()["tasks"] == []


def test_checklist_lines_are_ticked_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Checklist job", checklist_items=["Charger", "Case"])
    first = job["checklist"][0]
    r = client.patch(f"{JOBS}/jobs/{job['id']}/checklist/{first['id']}", headers=shop["tech"], json={
        "state": "issue", "note": "Cable frayed"})
    assert r.json()["checklist"][0]["state"] == "issue" and r.json()["checklist"][0]["note"] == "Cable frayed"
    assert client.patch(f"{JOBS}/jobs/{job['id']}/checklist/{first['id']}", headers=shop["tech"],
                        json={"state": "broken"}).status_code == 422
    added = client.post(f"{JOBS}/jobs/{job['id']}/checklist", headers=shop["tech"], json={"label": "Screen protector"})
    assert [c["label"] for c in added.json()["checklist"]] == ["Charger", "Case", "Screen protector"]


# --------------------------------------------------------------------------- scope and isolation
def test_branches_and_businesses_are_kept_apart(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    juja_job = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["juja"]), "title": "Juja only",
        "customer_name": "Juja Jane"}).json()
    assert juja_job["number"].startswith("JOB-JUJA-")
    assert client.get(f"{JOBS}/jobs/{juja_job['id']}", headers=shop["manager"]).status_code == 404       # HQ manager
    assert client.get(f"{JOBS}/jobs/{juja_job['id']}", headers=shop["juja_keeper"]).status_code == 200   # sees Juja
    assert "Juja only" not in {j["title"] for j in client.get(f"{JOBS}/jobs", headers=shop["manager"]).json()}
    assert client.post(f"{JOBS}/jobs/{juja_job['id']}/notes", headers=shop["manager"], json={"text": "hi"}
                       ).status_code == 404
    assert client.post(f"{JOBS}/jobs", headers=shop["manager"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["juja"]), "title": "x", "customer_name": "y"}
                       ).status_code == 403
    other = make_jobs_shop(client, registry, "Other Garage")
    assert client.get(f"{JOBS}/jobs/{shop['first_job']['id']}", headers=other["owner"]).status_code == 404
    assert client.get(f"{JOBS}/jobs", headers=other["owner"]).json() == [] or all(
        j["id"] != shop["first_job"]["id"] for j in client.get(f"{JOBS}/jobs", headers=other["owner"]).json())
    unauthenticated = client.get(f"{JOBS}/jobs")
    assert unauthenticated.status_code == 401


# --------------------------------------------------------------------------- settings
def test_settings_choose_service_items_not_stock(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    bad = client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "labour_product_id": shop["cement"]})
    assert bad.status_code == 422 and "service" in bad.text
    ok = client.get(f"{JOBS}/settings", params={"company_id": co}, headers=shop["tech"]).json()
    assert Dec(ok["default_labour_rate"]) == 100 and ok["labour_product_name"] and ok["invoicing_available"]
    assert client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["tech"], json={
        "default_labour_rate": "5"}).status_code == 403


# --------------------------------------------------------------------------- privacy
def test_the_privacy_provider_finds_exports_and_erases_a_customer(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.jobs.privacy import JobsPersonalData
    from ziira.sdk import Subject

    done = new_job(client, shop, title="Privacy done", customer_name="Peter Privacy", customer_phone="+254 700 111 222")
    live = new_job(client, shop, title="Privacy live")
    client.post(f"{JOBS}/jobs/{done['id']}/notes", headers=shop["owner"], json={"text": "Peter likes calls at noon"})
    for code in ("cancelled",):
        assert move(client, shop, done, code).status_code == 200
    provider = JobsPersonalData()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], Subject(raw="254700111222", phone="254700111222"))
        assert [r.record_id for r in found] == [UUID(done["id"])]
        export = provider.export(s, found[0])
        assert export["job"][0]["customer_name"] == "Peter Privacy" and export["notes_and_history"]
        outcome = provider.anonymise(s, found[0], "request")
        assert outcome.status == "anonymised"
        open_ones = [r for r in provider.find(s, shop["company_id"], Subject(raw="Wanjiku", name="Wanjiku"))
                     if r.record_id == UUID(live["id"])]
        refused = provider.anonymise(s, open_ones[0], "request")
        assert refused.status == "refused" and "return it" in refused.kept[0].why
    after = get_job(client, shop, done)
    assert after["customer_name"].startswith("[") and after["customer_phone"] is None
    assert all("noon" not in (e["note"] or "") for e in after["events"])


# --------------------------------------------------------------------------- custom fields and packs
def test_work_orders_and_items_can_carry_custom_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    kinds = {k["entity_type"] for k in client.get("/api/v1/custom-fields/entities", headers=shop["owner"]).json()}
    assert {"jobs.work_order", "jobs.asset"} <= kinds


def test_an_industry_pack_seeds_stages_checklists_and_settings(client, shop, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.jobs.hooks import JobsSeeder

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "jobs.toml").write_text(
        '[settings]\ndefault_warranty_days = 30\n\n'
        '[[status]]\ncode = "awaiting_customer"\nname = "Awaiting customer"\nkind = "waiting"\n\n'
        '[[move]]\nfrom = "diagnosing"\nto = "awaiting_customer"\n\n'
        '[[checklist]]\nname = "Appliance intake"\nasset_kind = "appliance"\nitems = ["Power cord", "Model plate read"]\n')
    pack = PackData(name="pack_test", title="Test", summary="", meta={"units": ["jobs"]}, directory=tmp_path)
    seeder = JobsSeeder()
    with system(shop) as s:
        first = seeder.seed(s, pack, shop["company_id"])
        again = seeder.seed(s, pack, shop["company_id"])
        added = {i.item_type for i in first.added}
        assert added == {"job_status", "checklist_template"} and again.count == 0
        status_item = next(i for i in first.added if i.item_type == "job_status")
        assert seeder.untouched(s, "job_status", status_item.item_id)
        seeder.remove(s, "job_status", status_item.item_id)
    codes = {x["code"] for x in client.get(f"{JOBS}/workflow", headers=shop["owner"], params={
        "company_id": str(shop["company_id"])}).json()}
    assert "awaiting_customer" not in codes
    names = {t["name"] for t in client.get(f"{JOBS}/checklist-templates", headers=shop["owner"], params={
        "company_id": str(shop["company_id"])}).json()}
    assert "Appliance intake" in names
    assert stage(client, shop, "received")
