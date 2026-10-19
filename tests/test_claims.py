"""Claims end to end: payers and their terms, an insurer claim from estimate to settled (partial approval, counter-offer,
revision, supplementary estimate, completion, split invoices, a reduction after invoicing, payments and a short payment),
the payer's secure response link, closing outcomes, the work gate, scope, idempotency, events, privacy.

Numbers are worked out by hand in the comments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.claims_helpers import (
    CLAIMS,
    answer,
    by_description,
    estimate,
    get_claim,
    line,
    make_claims_shop,
    submit,
)
from tests.stock_helpers import system

POS = "/api/v1/pos"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_claims_shop(client, registry, "Claims Garage")


@pytest.fixture(scope="module")
def flow() -> dict[str, Any]:
    return {}


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def pos_invoice(client, shop, invoice_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.get(f"{POS}/invoices/{invoice_id}", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


# =========================================================================== payers and their terms
def test_a_payer_is_set_up_with_terms_as_data(client, shop) -> None:  # type: ignore[no-untyped-def]
    payer = shop["payer"]
    assert payer["customer_name"] == "Jubilee Claims" and payer["labour_rates"] == {"mechanical": "100.00", "body": "150.00"}
    assert payer["required_documents"] == ["Assessor report", "Photos"] and payer["payment_days"] == 30
    assert Dec(payer["parts_discount_pct"]) == 10
    again = client.post(f"{CLAIMS}/payers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "jubilee insurance"})
    assert again.status_code == 409                                              # names are unique, any case
    changed = client.patch(f"{CLAIMS}/payers/{payer['id']}", headers=shop["owner"], json={
        "labour_rates": {"Body": "160", "default": "90"}, "contacts": [{"name": "Hannah", "phone": "254711"}, {"name": " "}]})
    assert changed.status_code == 200
    assert changed.json()["labour_rates"] == {"body": "160", "default": "90"} and len(changed.json()["contacts"]) == 1
    client.patch(f"{CLAIMS}/payers/{payer['id']}", headers=shop["owner"], json={"labour_rates": {"body": "150.00"}})
    made = client.post(f"{CLAIMS}/payers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Fleet Co", "kind": "fleet",
        "new_customer": {"name": "Fleet Co Ltd", "phone": "254722000111"}})
    assert made.status_code == 201 and made.json()["customer_name"] == "Fleet Co Ltd"
    other = client.post(f"{CLAIMS}/payers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Bad", "customer_id": str(uuid4())})
    assert other.status_code == 422                                              # a customer that does not exist


def test_only_people_with_the_right_permission_set_up_payers(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "name": "Nobody Ltd"}
    assert client.post(f"{CLAIMS}/payers", headers=shop["rep"], json=body).status_code == 403
    assert client.post(f"{CLAIMS}/payers", headers=shop["cashier"], json=body).status_code == 403
    assert client.get(f"{CLAIMS}/payers", headers=shop["cashier"]).status_code == 200
    assert client.get(f"{CLAIMS}/payers", headers=shop["storekeeper"]).status_code == 403
    assert client.patch(f"{CLAIMS}/settings", params={"company_id": str(shop["company_id"])}, headers=shop["rep"],
                        json={"unapproved_work": "block"}).status_code == 403
    fm = client.post(f"{CLAIMS}/payers", headers=shop["fm"], json=body)
    assert fm.status_code == 201
    stock_item = client.patch(f"{CLAIMS}/settings", params={"company_id": str(shop["company_id"])},
                              headers=shop["owner"], json={"invoice_product_id": shop["cement"]})
    assert stock_item.status_code == 422                                         # claim invoices go under a service item


# =========================================================================== one claim from start to settled
def test_a_claim_is_opened_once_per_job_and_a_retry_changes_nothing(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    job = client.post("/api/v1/jobs/jobs", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Collision repair",
        "customer_id": shop["customer"]["id"]})
    assert job.status_code == 201, job.text
    flow["job"] = job.json()
    body = {"company_id": str(shop["company_id"]), "payer_id": shop["payer"]["id"], "source_type": "job",
            "source_id": flow["job"]["id"], "policy_number": "POL-778", "claim_number": "JUB-2026-0042",
            "excess_amount": "500.00", "loss_date": "2026-10-01", "assessor_name": "Peter Assessor"}
    first = client.post(f"{CLAIMS}/claims", headers=shop["rep"], json=body, params={})
    assert first.status_code == 201, first.text
    claim = first.json()
    assert claim["number"].startswith("CLM-HQ-") and claim["status"] == "draft"
    assert claim["customer_id"] == shop["customer"]["id"] and claim["insured_name"] == "Wanjiku Motors"
    assert claim["source_number"] == flow["job"]["number"] and claim["branch_id"] == str(shop["branch_id"])
    assert claim["required_documents"] == ["Assessor report", "Photos"]
    assert client.post(f"{CLAIMS}/claims", headers=shop["owner"], json=body).status_code == 409   # one live claim per job
    retry = {"Idempotency-Key": "claim-open-1"}
    other = {**body, "source_id": None, "source_type": None, "branch_id": str(shop["branch_id"])}
    a = client.post(f"{CLAIMS}/claims", headers={**shop["owner"], **retry}, json=other)
    b = client.post(f"{CLAIMS}/claims", headers={**shop["owner"], **retry}, json=other)
    assert a.status_code == 201 and b.json()["id"] == a.json()["id"]
    assert len(sql(shop, "select 1 from claims.claim where policy_number = 'POL-778' and source_id is null")) == 1
    flow["claim"] = claim
    by_source = client.get(f"{CLAIMS}/claims/by-source", headers=shop["owner"],
                           params={"source_type": "job", "source_id": flow["job"]["id"]})
    assert by_source.status_code == 200 and by_source.json()["id"] == claim["id"]


def test_the_estimate_is_priced_from_the_payers_terms(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    claim = flow["claim"]
    est = estimate(client, shop, claim, [
        line("labour", "Panel beating", "4", None, work_type="body"),                    # 4 x 150.00 (the payer's body rate)
        line("parts", "Front bumper", "1", "12000.00", part_class="genuine"),
        line("parts", "Headlamp", "1", "4500.00", part_class="aftermarket"),
        line("paint", "Respray bumper", "1", "8000.00"),
        line("sundries", "Masking and consumables", "1", "350.00")], notes="Photos attached")
    assert [x["asked_total"] for x in est["lines"]] == ["600.00", "12000.00", "4500.00", "8000.00", "350.00"]
    assert est["total"] == "25450.00" and est["label"] == "Estimate version 1" and est["status"] == "draft"
    assert est["over_approval_limit"] is False
    no_rate = client.post(f"{CLAIMS}/claims/{claim['id']}/estimates", headers=shop["owner"], json={
        "lines": [line("labour", "Mechanical", "1", None, work_type="electrical")]})
    assert no_rate.status_code == 409                                                  # a draft already exists
    flow["v1"] = est
    unpriced = client.patch(f"{CLAIMS}/estimates/{est['id']}", headers=shop["owner"], json={
        "lines": [line("parts", "No price", "1", None)]})
    assert unpriced.status_code == 422                                                 # parts need a price
    terms = client.patch(f"{CLAIMS}/estimates/{est['id']}", headers=shop["owner"], json={
        "lines": [line("parts", "Part at list price", "2", "1000.00")], "apply_payer_terms": True})
    assert terms.json()["lines"][0]["unit_price"] == "900.0000" and terms.json()["total"] == "1800.00"     # 10% off list
    restored = client.patch(f"{CLAIMS}/estimates/{est['id']}", headers=shop["owner"], json={"lines": [
        line("labour", "Panel beating", "4", None, work_type="body"),
        line("parts", "Front bumper", "1", "12000.00", part_class="genuine"),
        line("parts", "Headlamp", "1", "4500.00", part_class="aftermarket"),
        line("paint", "Respray bumper", "1", "8000.00"),
        line("sundries", "Masking and consumables", "1", "350.00")]})
    flow["v1"] = restored.json()
    assert restored.json()["total"] == "25450.00"


def test_the_estimate_is_sent_and_printed(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    v1 = flow["v1"]
    html = client.get(f"{CLAIMS}/estimates/{v1['id']}/document", headers=shop["owner"])
    assert html.status_code == 200 and "Front bumper" in html.text and "25,450.00" in html.text
    text_doc = client.get(f"{CLAIMS}/estimates/{v1['id']}/document", headers=shop["owner"], params={"format": "text"})
    assert text_doc.status_code == 200 and "Estimate version 1" in text_doc.text and "KES" in text_doc.text or "25,450.00" in text_doc.text
    assert client.get(f"{CLAIMS}/estimates/{v1['id']}/document", headers=shop["storekeeper"]).status_code == 403
    nobody = client.post(f"{CLAIMS}/estimates/{v1['id']}/submit", headers=shop["cashier"], json={})
    assert nobody.status_code == 403                                                   # a cashier may only view
    wrong = client.post(f"{CLAIMS}/estimates/{v1['id']}/submit", headers=shop["owner"], json={"channel": "carrier-pigeon"})
    assert wrong.status_code == 422                                                    # a channel the business does not have
    sent = submit(client, shop, v1)
    assert sent["estimate"]["status"] == "submitted" and sent["queued"] is False
    assert sent["estimate"]["valid_until"] is not None and len(sent["estimate"]["links"]) == 1
    flow["v1_link"] = sent["link_path"].removeprefix("/claim-response/")
    claim = get_claim(client, shop, flow["claim"])
    assert claim["status"] == "open" and claim["waiting_on"] == "payer"
    assert client.post(f"{CLAIMS}/estimates/{v1['id']}/submit", headers=shop["owner"], json={}).status_code == 409


def test_the_payer_answers_part_of_the_estimate_by_phone(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    v1 = flow["v1"]
    ids = {x["description"]: x["id"] for x in v1["lines"]}
    r = answer(client, shop, v1, [
        {"line_id": ids["Panel beating"], "state": "approved"},
        {"line_id": ids["Front bumper"], "state": "approved"},
        {"line_id": ids["Headlamp"], "state": "countered", "amount": "3000.00", "reason": "Aftermarket price list"},
        {"line_id": ids["Respray bumper"], "state": "rejected", "reason": "Paint not covered on a bumper repair"},
        {"line_id": ids["Masking and consumables"], "state": "needs_information"}], via="phone")
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["status"] == "submitted" and len(est["responses"]) == 1             # still waiting for the last line
    assert est["responses"][0]["by_name"] == "Peter Assessor" and est["responses"][0]["via"] == "phone"
    assert est["responses"][0]["channel"] == "staff"
    claim = get_claim(client, shop, flow["claim"])
    assert claim["status"] == "authorised" and claim["totals"]["payer_pays"] == "12600.00"     # 600 + 12000
    assert claim["waiting_on"] == "us"                                             # the counter waits for us first
    # a line answered cannot be answered again; a counter must be lower; a rejection needs its reason; no future times
    again = answer(client, shop, v1, [{"line_id": ids["Front bumper"], "state": "rejected", "reason": "x"}])
    assert again.status_code == 422
    for bad in ({"line_id": ids["Masking and consumables"], "state": "countered", "amount": "350.00"},
                {"line_id": ids["Masking and consumables"], "state": "rejected"},
                {"line_id": str(uuid4()), "state": "approved"}):
        assert answer(client, shop, v1, [bad]).status_code == 422
    future = answer(client, shop, v1, [{"line_id": ids["Masking and consumables"], "state": "approved"}],
                    occurred_at=(datetime.now(UTC) + timedelta(days=2)).isoformat())
    assert future.status_code == 422
    second = answer(client, shop, v1, [{"line_id": ids["Masking and consumables"], "state": "approved"}],
                    via="email", name="Peter Assessor", note="Consumables confirmed")
    assert second.status_code == 200
    done = second.json()
    assert done["status"] == "answered" and done["response"] == "countered" and len(done["responses"]) == 2
    head = by_description(done, "Headlamp")
    assert head["payer_state"] == "countered" and head["payer_amount"] == "3000.00" and head["waiting_on"] == "us"
    assert [h["state"] for h in head["history"]] == ["countered"]
    assert by_description(done, "Respray bumper")["waiting_on"] == "customer"
    assert answer(client, shop, v1, [{"line_id": ids["Masking and consumables"], "state": "approved"}]).status_code == 409
    flow["v1"] = done


def test_the_counter_is_declined_and_the_customer_agrees_to_pay_the_paint(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    v1 = flow["v1"]
    head, paint = by_description(v1, "Headlamp"), by_description(v1, "Respray bumper")
    no_name = client.post(f"{CLAIMS}/lines/{head['id']}/counter-decision", headers=shop["owner"], json={
        "accept": True, "shortfall_to": "customer"})
    assert no_name.status_code == 422                                                # the customer's name is needed
    declined = client.post(f"{CLAIMS}/lines/{head['id']}/counter-decision", headers=shop["owner"], json={
        "accept": False, "note": "Genuine part, see photo"})
    assert declined.status_code == 200
    assert client.post(f"{CLAIMS}/lines/{paint['id']}/counter-decision", headers=shop["owner"],
                       json={"accept": True}).status_code == 409                      # a rejection is not a counter
    pays = client.post(f"{CLAIMS}/lines/{paint['id']}/customer-decision", headers=shop["owner"], json={
        "pays": True, "by_name": "Wanjiku Mwangi"})
    assert pays.status_code == 200
    claim = pays.json()
    assert claim["totals"]["payer_pays"] == "12950.00" and claim["totals"]["customer_pays"] == "8000.00"
    assert claim["totals"]["open"] == "0.00" and claim["waiting_on"] is None
    assert client.post(f"{CLAIMS}/lines/{paint['id']}/customer-decision", headers=shop["cashier"],
                       json={"pays": False, "by_name": "x"}).status_code == 403


def test_a_new_version_asks_only_what_is_still_open_and_the_payer_answers_on_the_link(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    v1 = flow["v1"]
    r = client.post(f"{CLAIMS}/claims/{flow['claim']['id']}/estimates", headers=shop["owner"], json={
        "kind": "revision", "from_estimate_id": v1["id"], "revision_note": "The headlamp is genuine, photo attached"})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["label"] == "Estimate version 2" and v2["version"] == 2 and v2["previous_id"] == v1["id"]
    states = {x["description"]: (x["locked"], x["payer_state"]) for x in v2["lines"]}
    assert states == {"Panel beating": (True, "approved"), "Front bumper": (True, "approved"),
                      "Headlamp": (False, "pending"), "Respray bumper": (True, "rejected"),
                      "Masking and consumables": (True, "approved")}
    assert v2["total"] == "25450.00"
    locked = [x for x in v2["lines"] if x["locked"]][0]
    head_id = by_description(v2, "Headlamp")["id"]
    extra = client.patch(f"{CLAIMS}/estimates/{v2['id']}", headers=shop["owner"], json={"lines": [
        line("parts", "Headlamp", "1", "4500.00", part_class="genuine", line_id=head_id),
        line("sundries", "Wheel alignment", "1", "1000.00")]})
    assert extra.status_code == 200, extra.text            # the settled lines stay whatever is sent; the others are replaced
    assert extra.json()["total"] == "26450.00" and len(extra.json()["lines"]) == 6
    assert by_description(extra.json(), "Panel beating")["locked"] is True
    back = client.patch(f"{CLAIMS}/estimates/{v2['id']}", headers=shop["owner"], json={"lines": [
        line("parts", "Headlamp", "1", "4500.00", part_class="genuine", line_id=head_id)]})
    v2 = back.json()
    assert by_description(v2, "Headlamp")["part_class"] == "genuine" and v2["total"] == "25450.00" and len(v2["lines"]) == 5
    assert [h["state"] for h in by_description(v2, "Headlamp")["history"]] == ["countered"]    # its first round travels with it
    stranger = client.patch(f"{CLAIMS}/estimates/{v2['id']}", headers=shop["owner"], json={"lines": [
        line("parts", "Headlamp", "1", "4500.00", line_id=str(uuid4()))]})
    assert stranger.status_code == 422
    assert locked["payer_state"] == "approved"
    sent = submit(client, shop, v2)
    old = client.get(f"{CLAIMS}/estimates/{v1['id']}", headers=shop["owner"]).json()
    assert old["status"] == "superseded" and old["in_play"] is False and old["links"][0]["state"] == "revoked"
    flow["v2"], flow["v2_link"] = sent["estimate"], sent["link_path"].removeprefix("/claim-response/")
    dead = client.get(f"{CLAIMS}/public/claim-response/{flow['v1_link']}")
    assert dead.status_code == 200 and dead.json()["state"] == "replaced" and "lines" in dead.json() and dead.json()["lines"] == []
    assert dead.json().get("total") is None                                           # nothing of the estimate is shown
    page = client.get(f"{CLAIMS}/public/claim-response/{flow['v2_link']}")
    assert page.status_code == 200
    shown = page.json()
    assert shown["state"] == "open" and shown["business"] == "Claims Garage Ltd" and shown["payer"] == "Jubilee Insurance"
    assert shown["claim_number"] == "JUB-2026-0042" and shown["policy_number"] == "POL-778"
    assert shown["revision_note"] == "The headlamp is genuine, photo attached" and shown["total"] == "25450.00"
    raw = page.text
    assert "Wanjiku" not in raw and "254712345678" not in raw and "Peter Assessor" not in raw   # no customer details
    open_line = next(x for x in shown["lines"] if x["description"] == "Headlamp")
    # the payer must answer every open line, signs with a name
    no_name = client.post(f"{CLAIMS}/public/claim-response/{flow['v2_link']}", json={"name": " ", "lines": [
        {"line_id": open_line["id"], "state": "approved"}]})
    assert no_name.status_code == 422
    missing = client.post(f"{CLAIMS}/public/claim-response/{flow['v2_link']}", json={"name": "Grace", "lines": [
        {"line_id": locked["id"], "state": "approved"}]})
    assert missing.status_code == 422
    counter_high = client.post(f"{CLAIMS}/public/claim-response/{flow['v2_link']}", json={"name": "Grace", "lines": [
        {"line_id": open_line["id"], "state": "countered", "amount": "5000.00"}]})
    assert counter_high.status_code == 422
    ok = client.post(f"{CLAIMS}/public/claim-response/{flow['v2_link']}", json={
        "name": "Grace Adjuster", "role": "Claims officer", "authority_ref": "LPO-991", "authority_amount": "20000.00",
        "note": "Approved", "lines": [{"line_id": open_line["id"], "state": "approved"}]})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"state": "answered", "response": "accepted"}
    again = client.post(f"{CLAIMS}/public/claim-response/{flow['v2_link']}", json={
        "name": "Mallory", "lines": [{"line_id": open_line["id"], "state": "rejected", "reason": "no"}]})
    assert again.status_code == 409                                                   # a second sign-off changes nothing
    claim = get_claim(client, shop, flow["claim"])
    assert claim["authority_ref"] == "LPO-991" and claim["authority_amount"] == "20000.00"
    v2 = next(e for e in claim["estimates"] if e["id"] == flow["v2"]["id"])
    assert v2["status"] == "answered" and v2["responses"][0]["by_name"] == "Grace Adjuster (Claims officer)"
    assert v2["responses"][0]["channel"] == "link" and v2["links"][0]["state"] == "answered"
    head = by_description(v2, "Headlamp")
    assert head["payer_state"] == "approved" and [h["state"] for h in head["history"]] == ["countered", "approved"]
    assert claim["totals"]["payer_pays"] == "17450.00" and claim["totals"]["customer_pays"] == "8000.00"   # 600+12000+4500+350
    flow["v2"] = v2


def test_every_use_of_the_link_is_logged(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    link_id = next(x for x in client.get(f"{CLAIMS}/estimates/{flow['v2']['id']}/links", headers=shop["owner"]).json())["id"]
    log = client.get(f"{CLAIMS}/links/{link_id}/access", headers=shop["owner"]).json()
    actions = [(x["action"], x["outcome"].split(":")[0]) for x in reversed(log)]
    assert actions[0] == ("view", "open")
    assert ("answer", "refused") in actions and ("answer", "accepted") in actions and ("answer", "answered") in actions
    shown = client.get(f"{CLAIMS}/links/{link_id}/access", headers=shop["rep"])
    assert shown.status_code == 200                                                    # claims.view is enough
    assert client.get(f"{CLAIMS}/links/{link_id}/access", headers=shop["storekeeper"]).status_code == 403
    rows = sql(shop, "select count(*) as n from claims.link_access where link_id = :l", l=link_id)
    assert rows[0].n == len(log)
    with pytest.raises(Exception, match="immutable"):
        sql(shop, "update claims.link_access set outcome = 'x' where link_id = :l", l=link_id)


def test_extra_damage_is_a_supplementary_estimate_approved_separately(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    claim = flow["claim"]
    none_yet = client.post(f"{CLAIMS}/claims/{flow['claim']['id']}/estimates", headers=shop["owner"], json={
        "kind": "original", "lines": [line("labour", "x", "1", "1")]})
    assert none_yet.status_code == 409                                                 # the first estimate exists
    s1 = estimate(client, shop, claim, [line("labour", "Straighten radiator support", "2", None, work_type="body"),
                                        line("parts", "Radiator support bracket", "1", "2200.00")],
                  kind="supplementary", notes="Found after teardown")
    assert s1["label"] == "Supplementary 1, version 1" and s1["total"] == "2500.00"       # 2 x 150 + 2200
    sent = submit(client, shop, s1)
    s1 = sent["estimate"]
    mid = get_claim(client, shop, claim)
    assert mid["gate"]["state"] == "partly_authorised" and mid["gate"]["unapproved_total"] == "2500.00"
    ids = {x["description"]: x["id"] for x in s1["lines"]}
    r = answer(client, shop, s1, [
        {"line_id": ids["Straighten radiator support"], "state": "approved"},
        {"line_id": ids["Radiator support bracket"], "state": "countered", "amount": "2000.00", "reason": "Used part"}],
        via="portal", name="Insurer portal")
    assert r.status_code == 200 and r.json()["status"] == "answered"
    accept = client.post(f"{CLAIMS}/lines/{ids['Radiator support bracket']}/counter-decision", headers=shop["owner"],
                         json={"accept": True, "shortfall_to": "business"})
    assert accept.status_code == 200
    claim_now = accept.json()
    assert claim_now["totals"]["payer_pays"] == "19750.00"                          # 17450 + 300 + 2000
    assert claim_now["totals"]["absorbed"] == "200.00" and claim_now["totals"]["customer_pays"] == "8000.00"
    assert len([e for e in claim_now["estimates"] if e["in_play"]]) == 2             # version 2 and the supplementary one
    assert next(e for e in claim_now["estimates"] if e["id"] == flow["v1"]["id"])["in_play"] is False
    assert claim_now["gate"]["state"] == "authorised"
    flow["s1"] = s1


def test_the_work_is_signed_off_and_invoiced_to_the_payer_and_the_customer(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    claim = flow["claim"]
    early = client.post(f"{CLAIMS}/claims/{claim['id']}/invoice", headers=shop["owner"])
    assert early.status_code == 422 and "signed off" in early.text                  # not before the work is signed off
    assert client.post(f"{CLAIMS}/claims/{claim['id']}/completion", headers=shop["rep"], json={
        "signed_by": "Peter Assessor", "note": "Re-inspected and accepted"}).status_code == 200
    assert client.post(f"{CLAIMS}/claims/{claim['id']}/completion", headers=shop["owner"], json={
        "signed_by": "Peter"}).status_code == 409
    done = get_claim(client, shop, claim)
    assert done["status"] == "completed" and done["completion_signed_by"] == "Peter Assessor"
    preview = client.get(f"{CLAIMS}/claims/{claim['id']}/billing", headers=shop["owner"]).json()
    # payer: 600 + 12000 + 350 + 4500 + 300 + 2000 = 19750, less the excess 500 = 19250; customer: excess 500 + paint 8000
    assert preview["payer_gross"] == "19750.00" and preview["payer_net"] == "19250.00"
    assert preview["excess_applied"] == "500.00" and preview["customer_total"] == "8500.00"
    assert preview["absorbed"] == "200.00" and preview["blockers"] == []
    discounts = [Dec(p["discount"]) for p in preview["payer_parts"]]
    assert sum(discounts) == Dec("500.00") and all(d >= 0 for d in discounts)
    assert client.post(f"{CLAIMS}/claims/{claim['id']}/invoice", headers=shop["cashier"]).status_code == 403
    invoiced = client.post(f"{CLAIMS}/claims/{claim['id']}/invoice", headers=shop["owner"])
    assert invoiced.status_code == 200, invoiced.text
    c = invoiced.json()
    assert c["status"] == "invoiced" and len(c["runs"]) == 1
    run = c["runs"][0]
    assert run["payer_amount"] == "19250.00" and run["customer_amount"] == "8500.00" and run["excess_applied"] == "500.00"
    payer_inv, cust_inv = pos_invoice(client, shop, run["payer_invoice_id"]), pos_invoice(client, shop, run["customer_invoice_id"])
    assert payer_inv["customer_id"] == shop["payer_customer"]["id"] and Dec(payer_inv["total"]) == Dec("19250.00")
    assert cust_inv["customer_id"] == shop["customer"]["id"] and Dec(cust_inv["total"]) == Dec("8500.00")
    assert sorted(Dec(x["line_total"]) for x in payer_inv["lines"]) == sorted(
        Dec(p["amount"]) - Dec(p["discount"]) for p in preview["payer_parts"])
    assert sorted(Dec(x["line_total"]) for x in cust_inv["lines"]) == [Dec("500.00"), Dec("8000.00")]
    described = sql(shop, "select description from pos.sales_invoice_line where invoice_id = :i", i=run["customer_invoice_id"])
    assert {r.description for r in described} == {"Excess (your share of the claim)", "Respray bumper"}
    assert payer_inv["due_date"] > payer_inv["issue_date"]
    again = client.post(f"{CLAIMS}/claims/{claim['id']}/invoice", headers=shop["owner"])
    assert again.status_code == 422                                                   # nothing is left to invoice
    assert all(x["invoiced"] for e in c["estimates"] if e["in_play"] for x in e["lines"])
    flow["run1"], flow["payer_inv1"] = run, payer_inv
    flow["bumper_id"] = next(x["id"] for e in c["estimates"] if e["id"] == flow["v2"]["id"]
                             for x in e["lines"] if x["description"] == "Front bumper")


def test_the_payer_reduces_a_line_after_invoicing_and_the_credit_is_exact(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    claim = flow["claim"]
    base = {"line_id": flow["bumper_id"], "new_amount": "10000.00", "reason": "Assessor re-priced", "by_name": "Grace"}
    assert client.post(f"{CLAIMS}/claims/{claim['id']}/reductions", headers=shop["rep"], json=base).status_code == 403
    for bad in ({"new_amount": "12000.00"}, {"new_amount": "13000.00"}, {"reason": " "}):
        assert client.post(f"{CLAIMS}/claims/{claim['id']}/reductions", headers=shop["owner"],
                           json={**base, **bad}).status_code == 422
    r = client.post(f"{CLAIMS}/claims/{claim['id']}/reductions", headers=shop["owner"], json=base)
    assert r.status_code == 200, r.text
    c = r.json()
    # the bumper carried 303.80 of the excess (largest-remainder share): its invoice line was 12000 - 303.80 = 11696.20
    inv = pos_invoice(client, shop, flow["run1"]["payer_invoice_id"])
    assert Dec(inv["credited"]) == Dec("11696.20") and inv["status"] in ("issued", "part_paid")
    bumper = next(x for e in c["estimates"] if e["id"] == flow["v2"]["id"] for x in e["lines"] if x["description"] == "Front bumper")
    assert bumper["payer_state"] == "countered" and bumper["payer_amount"] == "10000.00" and bumper["invoiced"] is False
    assert [h["state"] for h in bumper["history"]] == ["approved", "reduced"] or bumper["history"][-1]["state"] == "reduced"
    assert c["status"] == "completed"                                                 # something is waiting to be billed again
    assert any(e["kind"] == "credit" for e in c["events"])
    preview = client.get(f"{CLAIMS}/claims/{claim['id']}/billing", headers=shop["owner"]).json()
    # 10000 again, with the 303.80 it had lost: the customer already paid the whole excess, so no second excess charge
    assert preview["payer_net"] == "9696.20" and preview["customer_total"] == "0.00" and preview["excess_applied"] == "0.00"
    second = client.post(f"{CLAIMS}/claims/{claim['id']}/invoice", headers=shop["owner"])
    assert second.status_code == 200, second.text
    runs = second.json()["runs"]
    assert len(runs) == 2 and runs[1]["payer_amount"] == "9696.20" and runs[1]["customer_invoice_id"] is None
    # what the payer owes now: 19250 - 11696.20 + 9696.20 = 17250 = 19750 - 2000 - 500
    owed = client.get(f"{CLAIMS}/owed", headers=shop["owner"], params={"payer_id": shop["payer"]["id"]}).json()
    claim_owed = [o for o in owed if o["claim_id"] == claim["id"]]
    assert sum(Dec(o["outstanding"]) for o in claim_owed) == Dec("17250.00")
    flow["run2"] = runs[1]


def test_the_ageing_report_shows_what_the_payer_owes_by_how_late(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    owed = [o for o in client.get(f"{CLAIMS}/owed", headers=shop["owner"], params={"payer_id": shop["payer"]["id"]}).json()
            if o["claim_id"] == flow["claim"]["id"]]
    first = next(o for o in owed if o["run_id"] == flow["run1"]["id"])
    assert Dec(first["outstanding"]) == Dec("7553.80") and first["bucket"] == "not_due" and first["days_late"] == 0
    from datetime import date

    due = date.fromisoformat(first["due_date"])
    rows = client.get(f"{CLAIMS}/ageing", headers=shop["owner"], params={"as_of": (due + timedelta(days=45)).isoformat()}).json()
    ours = next(r for r in rows if r["payer_id"] == shop["payer"]["id"])
    assert Dec(ours["buckets"]["d31_60"]) == Dec("17250.00") and Dec(ours["buckets"]["not_due"]) == 0
    assert Dec(ours["total"]) == Dec("17250.00") and ours["invoices"] == 2
    soon = client.get(f"{CLAIMS}/ageing", headers=shop["owner"], params={"as_of": (due + timedelta(days=95)).isoformat()}).json()
    assert Dec(next(r for r in soon if r["payer_id"] == shop["payer"]["id"])["buckets"]["d90_plus"]) == Dec("17250.00")
    assert client.get(f"{CLAIMS}/ageing", headers=shop["storekeeper"]).status_code == 403


def test_the_payer_pays_and_comes_up_short(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    claim, payer = flow["claim"], shop["payer"]
    r1, r2 = flow["run1"], flow["run2"]
    body = {"branch_id": str(shop["branch_id"]), "amount": "7553.80", "method": "mobile_money", "reference": "REM-001",
            "allocations": [{"run_id": r1["id"], "amount": "7553.80"}]}
    assert client.post(f"{CLAIMS}/payers/{payer['id']}/receipts", headers=shop["rep"], json=body).status_code == 403
    first = client.post(f"{CLAIMS}/payers/{payer['id']}/receipts", headers=shop["owner"], json=body)
    assert first.status_code == 201, first.text
    assert first.json()["created"] is True and first.json()["receipt"]["pos_receipt_number"].startswith("RCT")
    repeat = client.post(f"{CLAIMS}/payers/{payer['id']}/receipts", headers=shop["owner"], json=body)
    assert repeat.status_code == 200 and repeat.json()["created"] is False
    assert repeat.json()["receipt"]["id"] == first.json()["receipt"]["id"]
    assert pos_invoice(client, shop, r1["payer_invoice_id"])["status"] == "paid"
    over = client.post(f"{CLAIMS}/payers/{payer['id']}/receipts", headers=shop["owner"], json={
        **body, "reference": "REM-OVER", "amount": "999999.00", "allocations": [{"run_id": r2["id"], "amount": "999999.00"}]})
    assert over.status_code == 422                                                    # more than the invoice owes
    short = client.post(f"{CLAIMS}/payers/{payer['id']}/receipts", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "amount": "9000.00", "method": "mobile_money", "reference": "REM-002",
        "allocations": [{"run_id": r2["id"], "amount": "9000.00", "closes_invoice": True}]})
    assert short.status_code == 201, short.text
    c = get_claim(client, shop, claim)
    # 9696.20 invoiced, 9000.00 paid and called final: 696.20 short
    assert len(c["short_pays"]) == 1
    sp = c["short_pays"][0]
    assert sp["expected"] == "9696.20" and sp["paid"] == "9000.00" and sp["difference"] == "696.20" and sp["status"] == "open"
    assert c["status"] == "invoiced"
    flagged = sql(shop, "select message from kernel.exception_item where unit_name = 'claims' and kind = 'short_payment'")
    assert flagged and "696.20" in flagged[0].message
    flow["short_pay"] = sp


def test_a_short_payment_is_recharged_to_the_customer_and_the_claim_settles(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    sp, claim = flow["short_pay"], flow["claim"]
    url = f"{CLAIMS}/short-pays/{sp['id']}/resolve"
    assert client.post(url, headers=shop["rep"], json={"resolution": "recharge"}).status_code == 403
    assert client.post(url, headers=shop["owner"], json={"resolution": "dispute"}).status_code == 422     # a note is needed
    disputed = client.post(url, headers=shop["owner"], json={"resolution": "dispute", "note": "Asked Grace for the remittance"})
    assert disputed.json()["status"] == "disputed"
    recharged = client.post(url, headers=shop["owner"], json={"resolution": "recharge"})
    assert recharged.status_code == 200 and recharged.json()["status"] == "recharged"
    assert recharged.json()["recharge_invoice_number"].startswith("INV")
    assert client.post(url, headers=shop["owner"], json={"resolution": "accept", "note": "x"}).status_code == 409
    # the customer pays the excess, the paint and the recharged difference: 8500 + 696.20
    paid = client.post(f"{POS}/receipts", headers=shop["owner"], json={
        "customer_id": shop["customer"]["id"], "amount": "9196.20", "method": "mobile_money",
        "branch_id": str(shop["branch_id"]), "external_ref": "CUST-1"})
    assert paid.status_code == 201, paid.text
    settled = client.post(f"{CLAIMS}/claims/{claim['id']}/refresh", headers=shop["owner"])
    assert settled.status_code == 200 and settled.json()["status"] == "settled"
    assert settled.json()["short_pays"][0]["status"] == "recharged"
    assert any(e["kind"] == "short_pay" for e in settled.json()["events"])
    closed = client.post(f"{CLAIMS}/claims/{claim['id']}/close", headers=shop["owner"], json={"reason": "cancelled"})
    assert closed.status_code == 422                                                   # invoiced: only written off


def test_the_timeline_tells_the_story_in_order(client, shop, flow) -> None:  # type: ignore[no-untyped-def]
    c = get_claim(client, shop, flow["claim"])
    kinds = [e["kind"] for e in c["events"]]
    assert kinds[0] == "created" and kinds[-1] in ("short_pay", "payment", "invoice")
    for needed in ("estimate", "submitted", "response", "decision", "authority", "completion", "invoice", "credit",
                   "payment", "short_pay"):
        assert needed in kinds, needed
    assert [e["created_at"] for e in c["events"]] == sorted(e["created_at"] for e in c["events"])
    with pytest.raises(Exception, match="immutable"):
        sql(shop, "delete from claims.claim_event where claim_id = :c", c=flow["claim"]["id"])
    with pytest.raises(Exception, match="immutable"):
        sql(shop, "update claims.line_response set reason = 'x'")
