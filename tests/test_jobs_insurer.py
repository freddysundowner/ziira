"""Insurer jobs: a job with a claim from the claims unit. The payer's rates and parts rules price the work, what the payer
authorised decides what may go ahead, a technician sees only the authorised work, unapproved extra work warns or blocks,
the customer's excess is collected at hand-over and the payer and the customer are invoiced separately."""

from decimal import Decimal as Dec  # noqa: N817

import pytest

from tests.claims_helpers import CLAIMS, answer, by_description, make_claims_shop, submit
from tests.jobs_helpers import JOBS
from tests.pos_helpers import POS


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    made = make_claims_shop(client, registry, "Insurer Garage")
    co = str(made["company_id"])
    r = client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=made["owner"], json={
        "default_labour_rate": "100.00", "labour_product_id": made["delivery"], "parts_product_id": made["delivery"],
        "release_unpaid": "warn"})
    assert r.status_code == 200, r.text
    for code, rate in (("mechanical", "100.00"), ("body", "200.00")):
        assert client.post(f"{JOBS}/work-types", headers=made["owner"], json={
            "company_id": co, "code": code, "name": code.title(), "hourly_rate": rate}).status_code == 201
    made["flow"] = {}
    return made


def post(client, shop, path, body=None, who="owner", expect=(200, 201)):  # type: ignore[no-untyped-def]
    r = client.post(f"{JOBS}{path}", headers=shop[who], json=body or {})
    assert r.status_code in expect, r.text
    return r


def get_job(client, shop, job_id, who="owner"):  # type: ignore[no-untyped-def]
    r = client.get(f"{JOBS}/jobs/{job_id}", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def test_a_claim_is_opened_from_the_job_and_the_job_remembers_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = client.post(f"{JOBS}/jobs", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Collision repair",
        "customer_id": shop["customer"]["id"], "job_type_code": None,
        "new_asset": {"label": "Toyota Corolla KAA 123B", "kind": "vehicle"}}).json()
    shop["flow"]["job"] = job
    assert job["claim"] is None and job["has_claim"] is False
    opened = post(client, shop, f"/jobs/{job['id']}/claim", {
        "payer_id": shop["payer"]["id"], "policy_number": "POL-778", "claim_number": "JUB-2026-0042",
        "excess_amount": "500.00", "loss_date": "2026-10-01"}).json()
    claim = opened["claim"]
    assert opened["has_claim"] is True and opened["claim_id"] == claim["id"]
    assert claim["number"].startswith("CLM-HQ-") and claim["payer_name"] == "Jubilee Insurance"
    assert claim["status"] == "draft" and claim["excess"] == "500.00" and claim["limited"] is False
    assert claim["required_documents"] == ["Assessor report", "Photos"]
    assert any(e["kind"] == "claim" and "opened" in e["note"] for e in opened["events"])
    assert post(client, shop, f"/jobs/{job['id']}/claim", {"payer_id": shop["payer"]["id"]}, expect=(422, 409))


def test_the_payers_rates_and_parts_rules_price_the_work(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["flow"]["job"]
    body = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "4", "work_type_code": "body",
                                                              "description": "Panel beating"}).json()
    assert body["labour"][0]["rate"] == "150.00"           # the insurer's body rate, not the workshop's 200.00
    typed = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1", "work_type_code": "body", "rate": "180",
                                                               "description": "Special"}).json()
    assert typed["labour"][1]["rate"] == "180.00"          # a rate typed by hand wins
    part = post(client, shop, f"/jobs/{job['id']}/parts", {"product_id": shop["cement"], "quantity": "1"}).json()
    assert part["parts"][0]["unit_price"] == "104.4000"    # the list price 116.00 less the insurer's 10%
    explicit = post(client, shop, f"/jobs/{job['id']}/parts", {"description": "Headlamp", "quantity": "1",
                                                                 "unit_price": "4500", "part_class": "aftermarket"}).json()
    assert explicit["parts"][1]["unit_price"] == "4500.0000"
    post(client, shop, f"/jobs/{job['id']}/labour/{typed['labour'][1]['id']}", expect=(405,))


def test_the_estimate_for_the_payer_comes_from_the_job_and_its_answers_flow_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["flow"]["job"]
    # remove the special line so the estimate holds panel beating, the cement part and the headlamp
    current = get_job(client, shop, job["id"])
    special = next(x for x in current["labour"] if x["description"] == "Special")
    client.delete(f"{JOBS}/jobs/{job['id']}/labour/{special['id']}", headers=shop["owner"])
    drafted = post(client, shop, f"/jobs/{job['id']}/claim/estimate", {}).json()
    est = client.get(f"{CLAIMS}/estimates/{drafted['claim_estimate_id']}", headers=shop["owner"]).json()
    assert {x["description"] for x in est["lines"]} == {"Panel beating", "Cement", "Headlamp"} or len(est["lines"]) == 3
    sent = submit(client, shop, est)["estimate"]
    waiting = get_job(client, shop, job["id"])
    assert waiting["claim"]["status"] == "open" and waiting["claim"]["waiting_on"] == "payer"
    assert "insurer" in waiting["waiting_on"]
    listed = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"waiting_on": "insurer"}).json()
    assert job["id"] in [j["id"] for j in listed]
    ids = {x["description"]: x["id"] for x in sent["lines"]}
    r = answer(client, shop, sent, [
        {"line_id": ids["Panel beating"], "state": "approved"},
        {"line_id": ids["Headlamp"], "state": "rejected", "reason": "Aftermarket part not covered"},
        {"line_id": next(v for k, v in ids.items() if k not in ("Panel beating", "Headlamp")), "state": "approved"}])
    assert r.status_code == 200, r.text
    shop["flow"]["estimate"] = r.json()
    after = get_job(client, shop, job["id"])
    claim = after["claim"]
    assert claim["status"] == "authorised" and claim["waiting_on"] == "customer"        # the rejected line awaits the customer
    states = {x["description"]: (x["state"], x["work_authorised"]) for x in claim["lines"]}
    assert states["Panel beating"] == ("approved", True) and states["Headlamp"] == ("rejected", False)
    assert "insurer" not in after["waiting_on"]
    assert any("authorised" in (e["note"] or "").lower() for e in after["events"])


def test_a_technician_sees_only_the_work_that_is_authorised(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["flow"]["job"]
    limited = get_job(client, shop, job["id"], who="cashier")["claim"]
    assert limited["limited"] is True and limited["payer_pays"] is None and limited["excess"] is None
    assert {x["description"] for x in limited["lines"]} == {"Panel beating", "Cement"} or all(
        x["work_authorised"] for x in limited["lines"])
    assert all(x["asked_total"] is None for x in limited["lines"])
    assert "Headlamp" not in {x["description"] for x in limited["lines"]}
    full = get_job(client, shop, job["id"], who="owner")["claim"]
    assert "Headlamp" in {x["description"] for x in full["lines"]} and full["payer_pays"] is not None


def test_extra_work_beyond_the_payers_approval_warns_or_blocks(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["flow"]["job"]
    co = str(shop["company_id"])
    seen = get_job(client, shop, job["id"])
    assert seen["approval"]["quoted"] is True and Dec(seen["approval"]["extra"]) > 0     # the headlamp is not authorised
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "2", "work_type_code": "mechanical"})
    assert any("Beyond what the customer approved" in (e["note"] or "") for e in get_job(client, shop, job["id"])["events"])
    r = client.patch(f"{CLAIMS}/settings", params={"company_id": co}, headers=shop["owner"],
                     json={"unapproved_work": "block"})
    assert r.status_code == 200, r.text
    try:
        blocked = post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"}, expect=(409,))
        assert "additional-work estimate" in blocked.text or "approved" in blocked.text
        # a recorded decision to go ahead lifts the block
        claim_id = get_job(client, shop, job["id"])["claim"]["id"]
        decision = client.post(f"{CLAIMS}/claims/{claim_id}/work-decisions", headers=shop["owner"], json={
            "note": "Customer is waiting; the assessor agreed by phone"})
        assert decision.status_code in (200, 201), decision.text
        post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    finally:
        client.patch(f"{CLAIMS}/settings", params={"company_id": co}, headers=shop["owner"],
                     json={"unapproved_work": "warn"})


def test_the_customer_agrees_to_pay_the_rejected_line_and_the_job_is_billed_to_both(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["flow"]["job"]
    claim = get_job(client, shop, job["id"])["claim"]
    est = shop["flow"]["estimate"]
    headlamp = by_description(est, "Headlamp")
    pays = client.post(f"{CLAIMS}/lines/{headlamp['id']}/customer-decision", headers=shop["owner"], json={
        "pays": True, "by_name": "Wanjiku Mwangi"})
    assert pays.status_code == 200, pays.text
    after = get_job(client, shop, job["id"])
    assert after["claim"]["waiting_on"] is None
    # not signed off yet: the job cannot be billed
    early = client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["owner"], json={})
    assert early.status_code == 422 and "signed off" in early.text
    release = after["release"]
    assert release["ok"] is False and "customer's share" in release["message"]
    done = post(client, shop, f"/jobs/{job['id']}/claim/complete", {"signed_by": "Peter Assessor"}).json()
    assert done["claim"]["completed"] is True
    billed = post(client, shop, f"/jobs/{job['id']}/invoice").json()
    assert billed["locked"] is True and billed["invoiced"] is True and billed["invoice_id"] is None
    assert "(payer)" in billed["invoice_number"] and "(customer)" in billed["invoice_number"]
    claim_after = client.get(f"{CLAIMS}/claims/{claim['id']}", headers=shop["owner"]).json()
    assert claim_after["status"] == "invoiced"
    again = client.post(f"{JOBS}/jobs/{job['id']}/invoice", headers=shop["owner"], json={})
    assert again.status_code == 409
    waiting = get_job(client, shop, job["id"])["release"]
    assert waiting["ok"] is False and waiting["invoiced"] is True        # the customer still owes the excess
    # collecting the excess clears the warning; the payer's invoice stays open for the payer
    paid = client.post(f"{POS}/receipts", headers=shop["owner"], json={
        "customer_id": shop["customer"]["id"], "amount": str(waiting["balance"]), "method": "cash",
        "branch_id": str(shop["branch_id"])})
    assert paid.status_code == 201, paid.text
    assert get_job(client, shop, job["id"])["release"]["ok"] is True
