"""The real actions Intelligence can propose, each run through the real engine and the owning unit's own services.

Purchasing: a draft purchase request, a new selling price. POS and CRM: a payment reminder, holding credit. People,
Finance and Intelligence itself: a nudge to whoever can decide. Hand-checked numbers throughout.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import credit_customer, make_sales_shop
from tests.purchasing_helpers import PUR
from tests.stock_helpers import P, system
from ziira.modules.intel.services import engine
from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

INTEL = "/api/v1/intel"
TODAY = datetime.now(ZoneInfo("Africa/Nairobi")).date()         # the test businesses' time zone (a fixture value)
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.crm.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.pos.hooks  # noqa: F401
    import ziira.modules.purchasing.hooks  # noqa: F401

    s = make_sales_shop(client, registry, "Act Real Co", stock="500")
    for unit in ("purchasing", "intel", "messaging"):
        registry.enable(s["tenant_id"], unit)
    for channel in ("sms", "email"):
        r = client.put(f"/api/v1/notifications/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    sup = client.post(f"{PUR}/suppliers", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "code": "TOTAL01", "name": "Total Supplies", "payment_terms_days": 30})
    assert sup.status_code == 201, sup.text
    other = client.post(f"{PUR}/suppliers", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "code": "BETA01", "name": "Beta Supplies", "payment_terms_days": 30})
    s.update(supplier=sup.json()["id"], beta=other.json()["id"], buyer=s["manager"],
             rep=s["user"]("rep", "Sales Rep", s["branch_id"]),
             clerk=s["user"]("clerk", "Accountant", None))
    return s


def set_level(client, shop, level: int) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                     json={"intel_action_level": level})
    assert r.status_code == 200, r.text


def setting(client, shop, **values: Any) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"], json=values)
    assert r.status_code == 200, r.text


def run(shop, *codes: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only=set(codes))


def finding_of(shop, code: str, **match: Any) -> Any:  # type: ignore[no-untyped-def]
    """The one open finding of a check whose summary contains `match['text']` (or whose entity is `match['entity']`)."""
    with system(shop) as s:
        rows = s.execute(text("select id, summary, entity_id, branch_id from intel.finding where check_code = :c "
                              "and status not in ('resolved', 'dismissed') order by first_seen_at"), {"c": code}).all()
    chosen = [r for r in rows if match.get("text", "") in r.summary
              and (match.get("entity") is None or str(r.entity_id) == str(match["entity"]))]
    assert len(chosen) == 1, [r.summary for r in rows]
    return chosen[0]


def actions_of(client, shop, finding_id: Any, who: str = "owner") -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings/{finding_id}/actions", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def one_action(client, shop, finding_id: Any, kind: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    found = [a for a in actions_of(client, shop, finding_id) if a["action_type"] == kind]
    assert len(found) == 1, [a["action_type"] for a in actions_of(client, shop, finding_id)]
    return found[0]


def approve(client, shop, proposal: dict[str, Any], who: str = "owner", **body: Any):  # type: ignore[no-untyped-def]
    return client.post(f"{INTEL}/actions/{proposal['id']}/approve", headers=shop[who], json=body)


# --------------------------------------------------------------------------- stock helpers
def new_product(client, shop, sku: str, **extra: Any) -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": sku, "name": f"Item {sku}", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"], **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def move(shop, product: str, quantity: str, kind: str, business_date: date | None = None) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(product),
            quantity=Dec(quantity), movement_type=kind, source_type="test_doc", source_id=uuid4(),
            business_date=business_date or TODAY, unit_cost=Dec(10) if Dec(quantity) > 0 else None))


def bought(shop, supplier: str, product: str, cost: str, days_ago: int) -> None:  # type: ignore[no-untyped-def]
    """A price a supplier charged earlier (as a past receipt would have left it)."""
    with system(shop) as s:
        s.execute(text(
            "insert into purchasing.supplier_price (tenant_id, supplier_id, product_id, unit_cost, effective_date, "
            "source_type, source_id) values (kernel.current_tenant(), :s, :p, :c, :d, 'goods_receipt', :i)"),
            {"s": supplier, "p": product, "c": cost, "d": TODAY - timedelta(days=days_ago), "i": str(uuid4())})


# --------------------------------------------------------------------------- purchasing: a draft purchase request
def test_an_empty_shelf_becomes_a_draft_request_for_the_usual_supplier(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    oos = new_product(client, shop, "ACT-OOS", reorder_level="10")
    move(shop, oos, "20", "opening")
    move(shop, oos, "-20", "sale", TODAY - timedelta(days=5))                  # 20 sold this month, none left
    for supplier, cost, days in ((shop["supplier"], "40", 50), (shop["supplier"], "42", 20), (shop["beta"], "45", 10)):
        bought(shop, supplier, oos, cost, days)
    run(shop, "inventory.out_of_stock")
    f = finding_of(shop, "inventory.out_of_stock", entity=oos)
    proposal = one_action(client, shop, f.id, "purchasing.draft_purchase_request")
    # on hand 0, reorder level 10, sold 20 in 30 days: the larger of the two
    assert proposal["params"]["quantity"] == "20" and proposal["params"]["product_id"] == oos
    assert proposal["facts"]["On hand"] == "0" and proposal["facts"]["Reorder level"] == "10"
    assert proposal["facts"]["Sold in the last 30 days"] == "20" and proposal["facts"]["Quantity to order"] == "20"
    assert proposal["facts"]["Usual supplier"] == ("Total Supplies (last cost KES 42.00); "
                                                    "Beta Supplies (last cost KES 45.00)")
    assert proposal["description"].startswith("Draft a purchase request for 20 x Item ACT-OOS (ACT-OOS) for this branch")
    assert proposal["needs_permission"] == "po.create" and proposal["can_decide"] is True
    # the storekeeper may not; the HQ branch manager may, and the draft is theirs
    assert approve(client, shop, proposal, who="storekeeper").status_code == 403
    done = approve(client, shop, proposal, who="buyer")
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    [ref] = done.json()["result"]["created"]
    assert ref["type"] == "purchasing.purchase_request" and ref["label"].startswith("Request PRQ")
    request = client.get(f"{PUR}/requests/{ref['id']}", headers=shop["buyer"]).json()
    assert request["status"] == "draft" and request["branch_id"] == str(shop["branch_id"])
    [line] = request["lines"]
    assert (line["product_id"], Dec(line["quantity"])) == (oos, Dec(20))
    assert line["note"] == "Usual supplier: Total Supplies, Beta Supplies"
    creator = one(shop, "select u.full_name from purchasing.purchase_request r join kernel.app_user u "
                        "on u.id = r.created_by where r.id = :i", i=ref["id"])
    assert creator == "manager"
    # asking twice makes nothing twice
    assert approve(client, shop, proposal, who="buyer").json()["status"] == "executed"
    assert one(shop, "select count(*) from purchasing.purchase_request_line where product_id = :p", p=oos) == 1


def test_running_low_asks_for_the_gap_to_the_reorder_level(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    low = new_product(client, shop, "ACT-LOW", reorder_level="10")
    move(shop, low, "7", "opening")
    move(shop, low, "-3", "sale", TODAY - timedelta(days=2))                   # 4 left, 3 sold
    run(shop, "inventory.low_stock")
    f = finding_of(shop, "inventory.low_stock", entity=low)
    proposal = one_action(client, shop, f.id, "purchasing.draft_purchase_request")
    assert proposal["params"]["quantity"] == "6"                               # 10 - 4 = 6, more than the 3 sold
    assert proposal["facts"]["Usual supplier"] == "None on record"
    edited = approve(client, shop, proposal, who="buyer", params={"quantity": "12", "needed_by": TOMORROW.isoformat()})
    assert edited.status_code == 200 and edited.json()["params"]["quantity"] == "12"
    [ref] = edited.json()["result"]["created"]
    request = client.get(f"{PUR}/requests/{ref['id']}", headers=shop["buyer"]).json()
    assert Dec(request["lines"][0]["quantity"]) == 12 and request["needed_by"] == TOMORROW.isoformat()
    again = approve(client, shop, proposal, who="buyer", params={"quantity": "99"})
    assert again.status_code == 200 and again.json()["params"]["quantity"] == "12"      # done is done: nothing changes
    fresh = new_product(client, shop, "ACT-FIXED", reorder_level="10")
    move(shop, fresh, "2", "opening")
    run(shop, "inventory.low_stock")
    h = finding_of(shop, "inventory.low_stock", entity=fresh)
    open_one = one_action(client, shop, h.id, "purchasing.draft_purchase_request")
    assert approve(client, shop, open_one, who="buyer", params={"product_id": str(uuid4())}).status_code == 422


def test_a_product_with_an_open_request_is_not_proposed_again_and_stock_that_came_back_is_not_ordered(  # type: ignore[no-untyped-def]
        client, shop) -> None:
    set_level(client, shop, 3)
    covered = new_product(client, shop, "ACT-COV", reorder_level="10")
    move(shop, covered, "2", "opening")
    asked = client.post(f"{PUR}/requests", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]),
        "lines": [{"product_id": covered, "quantity": "30"}]})
    assert asked.status_code == 201, asked.text
    run(shop, "inventory.low_stock")
    f = finding_of(shop, "inventory.low_stock", entity=covered)
    assert [a for a in actions_of(client, shop, f.id) if a["action_type"] == "purchasing.draft_purchase_request"] == []
    # a proposal made, then stock arrives before a person looks: nothing is ordered
    late = new_product(client, shop, "ACT-LATE", reorder_level="10")
    move(shop, late, "3", "opening")
    run(shop, "inventory.low_stock")
    g = finding_of(shop, "inventory.low_stock", entity=late)
    proposal = one_action(client, shop, g.id, "purchasing.draft_purchase_request")
    assert proposal["params"]["quantity"] == "7"
    move(shop, late, "50", "receipt")
    failed = approve(client, shop, proposal, who="buyer")
    assert failed.status_code == 200 and failed.json()["status"] == "failed"
    assert "53" in failed.json()["result"]["message"] and failed.json()["result"]["created"] == []
    assert one(shop, "select count(*) from purchasing.purchase_request_line where product_id = :p", p=late) == 0


# --------------------------------------------------------------------------- purchasing: a new selling price
def test_a_cost_rise_becomes_a_price_that_keeps_the_margin(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    item = new_product(client, shop, "ACT-PRICE")
    r = client.put(f"{P}/price-lists/{shop['price_list']}/prices", headers=shop["owner"], json={
        "product_id": item, "price": "116.00", "valid_from": "2026-01-01"})            # 100.00 before 16% VAT
    assert r.status_code == 200, r.text
    bought(shop, shop["supplier"], item, "80", 30)                                      # 20% margin on 100.00
    bought(shop, shop["supplier"], item, "95", 1)                                       # now only 5%
    run(shop, "purchasing.margin_squeeze", "purchasing.supplier_price_rise")
    f = finding_of(shop, "purchasing.margin_squeeze", entity=item)
    proposal = one_action(client, shop, f.id, "purchasing.propose_price_update")
    # 95 / (1 - 0.20) = 118.75 before tax, 137.75 with 16% tax, from tomorrow
    assert proposal["params"] == {"product_id": item, "price": "137.75", "valid_from": TOMORROW.isoformat()}
    assert proposal["facts"]["Selling price now (with tax)"] == "KES 116.00"
    assert proposal["facts"]["Margin before the rise"] == "20.0%" and proposal["facts"]["Cost now"] == "KES 95.00"
    assert proposal["facts"]["Proposed price (with tax)"] == "KES 137.75"
    assert proposal["needs_permission"] == "prices.manage"
    assert approve(client, shop, proposal, who="buyer").status_code == 404             # a branch manager cannot see it
    assert approve(client, shop, proposal, who="clerk").status_code == 403             # an accountant sees, sets no prices
    done = approve(client, shop, proposal, who="fm")
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    assert "137.75" in done.json()["result"]["message"]
    rows = list(system_rows(shop, "select price, valid_from, valid_to from products.price_list_item where "
                                  "product_id = :p order by valid_from", p=item))
    assert [(r.price, r.valid_from, r.valid_to) for r in rows] == [
        (Dec("116.00"), date(2026, 1, 1), TODAY), (Dec("137.75"), TOMORROW, None)]    # the old price ends today
    audited = one(shop, "select count(*) from kernel.audit_log where action = 'set_price' and entity_id = "
                        "(select id from products.price_list_item where product_id = :p and price = 137.75)", p=item)
    assert audited == 1


def system_rows(shop, sql: str, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return list(s.execute(text(sql), {k: str(v) if isinstance(v, UUID) else v for k, v in params.items()}).all())


def test_a_price_is_not_proposed_when_there_is_nothing_to_keep_and_not_applied_when_it_moved(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    loss = new_product(client, shop, "ACT-LOSS")
    client.put(f"{P}/price-lists/{shop['price_list']}/prices", headers=shop["owner"], json={
        "product_id": loss, "price": "58.00", "valid_from": "2026-01-01"})             # 50.00 net, already below cost
    bought(shop, shop["supplier"], loss, "60", 30)
    bought(shop, shop["supplier"], loss, "70", 1)
    run(shop, "purchasing.margin_squeeze")
    f = finding_of(shop, "purchasing.margin_squeeze", entity=loss)
    assert [a for a in actions_of(client, shop, f.id) if a["action_type"] == "purchasing.propose_price_update"] == []
    # a proposal exists, someone sets a higher price meanwhile: approving changes nothing
    again = new_product(client, shop, "ACT-MOVED")
    client.put(f"{P}/price-lists/{shop['price_list']}/prices", headers=shop["owner"], json={
        "product_id": again, "price": "116.00", "valid_from": "2026-01-01"})
    bought(shop, shop["supplier"], again, "80", 30)
    bought(shop, shop["supplier"], again, "95", 1)
    run(shop, "purchasing.margin_squeeze")
    g = finding_of(shop, "purchasing.margin_squeeze", entity=again)
    proposal = one_action(client, shop, g.id, "purchasing.propose_price_update")
    client.put(f"{P}/price-lists/{shop['price_list']}/prices", headers=shop["owner"], json={
        "product_id": again, "price": "150.00", "valid_from": TODAY.isoformat()})
    result = approve(client, shop, proposal, who="fm")
    assert result.json()["status"] == "failed" and "no lower" in result.json()["result"]["message"]
    assert one(shop, "select count(*) from products.price_list_item where product_id = :p", p=again) == 2
    below = approve(client, shop, proposal, who="fm", params={"price": "0"})
    assert below.status_code == 422


# --------------------------------------------------------------------------- customers: reminders and credit
def raw_invoice(shop, number: str, customer: Any, issue: date, due: date, total: str, *,  # type: ignore[no-untyped-def]
                paid: str = "0", status: str = "issued") -> UUID:
    invoice = uuid4()
    with system(shop) as s:
        s.execute(text("""
            insert into pos.sales_invoice (id, tenant_id, company_id, branch_id, number, customer_id, issue_date, due_date,
                subtotal, tax_total, total, amount_paid, status, created_at)
            values (:id, kernel.current_tenant(), :co, :br, :n, :cu, :iss, :due, :t, 0, :t, :paid, :st,
                cast(:iss as timestamptz))"""),
                  {"id": str(invoice), "co": str(shop["company_id"]), "br": str(shop["branch_id"]), "n": number,
                   "cu": str(customer), "iss": issue, "due": due, "t": total, "paid": paid, "st": status})
    return invoice


def late_customer(client, shop, name: str, days_overdue: list[int], *, limit: str = "50000", phone: str | None = None,
                  prefix: str = "") -> dict[str, Any]:
    """A customer with one unpaid 1,000.00 invoice for each entry of `days_overdue` (due that many days ago)."""
    customer = credit_customer(client, shop, name=name, limit=limit, **({"phone": phone} if phone else {}))
    for n, days in enumerate(days_overdue):
        due = TODAY - timedelta(days=days)
        raw_invoice(shop, f"{prefix or name[:3].upper()}-{n + 1}", customer["id"], due - timedelta(days=30), due, "1000.00")
    return customer


def sent_to(shop, finding_id: Any = None, ref_type: str = "sales_invoice") -> list[Any]:  # type: ignore[no-untyped-def]
    return system_rows(shop, "select recipient, channel, body, status from kernel.notification where ref_type = :t "
                             "order by created_at, recipient", t=ref_type)


def test_a_payment_reminder_goes_to_the_customer_by_the_businesss_channel(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="sms")
    wanjiru = late_customer(client, shop, "Mama Wanjiru", [70, 40], phone="0722111333", prefix="W")
    nophone = late_customer(client, shop, "Nophone Stores", [50], prefix="N")
    run(shop, "pos.customer_overdue")
    f = finding_of(shop, "pos.customer_overdue", entity=wanjiru["id"])
    proposal = one_action(client, shop, f.id, "pos.send_payment_reminder")
    assert proposal["params"] == {"customer_id": wanjiru["id"], "min_days_overdue": 1, "channel": "sms"}
    assert proposal["facts"]["Invoices to chase"] == "W-1, W-2" and proposal["facts"]["Owed on those"] == "KES 2,000.00"
    assert proposal["facts"]["Oldest overdue (days)"] == "70"
    assert proposal["needs_permission"] == "receivables.manage"
    # no phone number on record: nothing can be sent, so nothing is proposed
    g = finding_of(shop, "pos.customer_overdue", entity=nophone["id"])
    assert [a for a in actions_of(client, shop, g.id) if a["action_type"] == "pos.send_payment_reminder"] == []
    # a sales rep sees receivables but not findings; an accountant may approve
    assert approve(client, shop, proposal, who="rep").status_code == 403               # a sales rep reads no findings
    done = approve(client, shop, proposal, who="clerk")
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    assert done.json()["result"]["message"] == "Reminded Mama Wanjiru by sms about W-1, W-2"
    assert [c["label"] for c in done.json()["result"]["created"]] == ["Invoice W-1", "Invoice W-2"]
    messages = [m for m in sent_to(shop) if m.recipient.endswith("722111333")]
    assert len(messages) == 2 and all(m.channel == "sms" and "Mama Wanjiru" in m.body for m in messages)
    assert one(shop, "select count(*) from pos.invoice_reminder r join pos.sales_invoice i on i.id = r.invoice_id "
                     "where i.customer_id = :c", c=wanjiru["id"]) == 2
    again = approve(client, shop, proposal, who="clerk")
    assert again.json()["status"] == "executed"
    assert len([m for m in sent_to(shop) if m.recipient.endswith("722111333")]) == 2          # nothing sent twice


def test_the_reminder_names_the_companys_own_currency(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="sms")
    system_rows(shop, "update kernel.company set base_currency = 'USD' where id = :c returning id",
                c=shop["company_id"])
    try:
        usd = late_customer(client, shop, "Dollar Debtor", [45], phone="0788999000", prefix="D")
        run(shop, "pos.customer_overdue")
        f = finding_of(shop, "pos.customer_overdue", entity=usd["id"])
        done = approve(client, shop, one_action(client, shop, f.id, "pos.send_payment_reminder"), who="clerk")
        assert done.json()["status"] == "executed", done.text
        [message] = [m for m in sent_to(shop) if m.recipient.endswith("788999000")]
        assert "for USD 1,000.00 was due on" in message.body and "KES" not in message.body
    finally:
        system_rows(shop, "update kernel.company set base_currency = 'KES' where id = :c returning id",
                    c=shop["company_id"])


def test_a_customer_who_asked_not_to_be_contacted_is_not_messaged(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="sms")
    quiet = late_customer(client, shop, "Quiet Trader", [45], phone="0733222111", prefix="Q")
    from ziira.sdk import opt_out_contact

    with system(shop) as s:
        opt_out_contact(s, company_id=shop["company_id"], recipient="254733222111", channel=None, reason="Asked")
    run(shop, "pos.customer_overdue")
    f = finding_of(shop, "pos.customer_overdue", entity=quiet["id"])
    proposal = one_action(client, shop, f.id, "pos.send_payment_reminder")
    done = approve(client, shop, proposal, who="clerk")
    assert done.json()["status"] == "executed"
    assert done.json()["result"]["message"] == "Nothing sent: Quiet Trader asked not to be contacted"
    states = [m.status for m in sent_to(shop) if m.recipient.endswith("733222111")]
    assert states and "queued" not in states
    assert one(shop, "select count(*) from pos.invoice_reminder r join pos.sales_invoice i on i.id = r.invoice_id "
                     "where i.customer_id = :c", c=quiet["id"]) == 0


def test_without_a_reminder_channel_no_reminder_is_proposed(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="off")
    off = late_customer(client, shop, "Channel Off", [60], phone="0744333222", prefix="C")
    run(shop, "pos.customer_overdue")
    f = finding_of(shop, "pos.customer_overdue", entity=off["id"])
    assert [a["action_type"] for a in actions_of(client, shop, f.id)] == ["pos.hold_credit"]
    setting(client, shop, reminder_channel="sms")


def test_at_level_4_reminders_go_out_by_themselves_within_the_rule(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="sms")
    old = late_customer(client, shop, "Old Debtor", [95], phone="0755444333", prefix="O")
    recent = late_customer(client, shop, "Recent Debtor", [40], phone="0766555444", prefix="R")
    run(shop, "pos.customer_overdue")                                  # level 3: suggestions only, nothing sent
    assert not [m for m in sent_to(shop) if m.recipient.endswith(("755444333", "766555444"))]
    set_level(client, shop, 4)
    rule = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "pos.send_payment_reminder", "daily_cap": 5,
        "conditions": {"min_days_overdue": 60, "channel": "sms"}})
    assert rule.status_code == 201, rule.text
    assert client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "pos.hold_credit"}).status_code == 422
    assert client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "purchasing.propose_price_update"}).status_code == 422
    result = run(shop, "pos.customer_overdue")
    assert result.acted >= 1
    f_old = finding_of(shop, "pos.customer_overdue", entity=old["id"])
    f_new = finding_of(shop, "pos.customer_overdue", entity=recent["id"])
    done = one_action(client, shop, f_old.id, "pos.send_payment_reminder")
    assert done["status"] == "executed" and done["decided_by"] is None
    assert [m.channel for m in sent_to(shop) if m.recipient.endswith("755444333")] == ["sms"]
    waiting = one_action(client, shop, f_new.id, "pos.send_payment_reminder")
    assert waiting["status"] == "proposed"                              # only 40 days: the rule wants 60
    assert not [m for m in sent_to(shop) if m.recipient.endswith("766555444")]
    assert one_action(client, shop, f_old.id, "pos.hold_credit")["status"] == "proposed"    # credit is never automatic
    log = client.get(f"{INTEL}/actions/log", headers=shop["owner"], params={"mode": "automatic"}).json()
    mine = [e for e in log if e["finding_id"] == str(f_old.id)]
    assert [(e["action_type"], e["outcome"], e["actor_name"], e["level"]) for e in mine] == [
        ("pos.send_payment_reminder", "executed", None, 4)]
    run(shop, "pos.customer_overdue")
    assert [m.channel for m in sent_to(shop) if m.recipient.endswith("755444333")] == ["sms"]   # once
    set_level(client, shop, 1)


def test_holding_credit_lowers_the_limit_to_what_is_owed_through_crm(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    setting(client, shop, reminder_channel="off")
    slow = late_customer(client, shop, "Slow Payer", [45, 20], limit="5000", prefix="S")      # owes 2,000.00
    fine = late_customer(client, shop, "Tight Limit", [45], limit="800", prefix="T")          # owes 1,000.00 > 800
    run(shop, "pos.customer_overdue")
    f = finding_of(shop, "pos.customer_overdue", entity=slow["id"])
    proposal = one_action(client, shop, f.id, "pos.hold_credit")
    assert proposal["params"] == {"customer_id": slow["id"], "credit_limit": "2000"}
    assert proposal["facts"] == {"Customer": "Slow Payer", "Owes now": "KES 2,000.00",
                                 "Credit limit now": "KES 5,000.00", "Credit limit proposed": "KES 2,000.00"}
    g = finding_of(shop, "pos.customer_overdue", entity=fine["id"])
    assert [a for a in actions_of(client, shop, g.id) if a["action_type"] == "pos.hold_credit"] == []   # already held
    assert approve(client, shop, proposal, who="clerk").status_code == 403             # an accountant manages no customers
    # raising is not what this action does, even by editing
    assert approve(client, shop, proposal, who="fm", params={"credit_limit": "9000"}).json()["status"] == "failed"
    done = approve(client, shop, proposal, who="fm", params={"credit_limit": "2000"})
    assert done.json()["status"] == "executed", done.text
    after = client.get(f"/api/v1/crm/customers/{slow['id']}", headers=shop["owner"]).json()
    assert Dec(after["credit_limit"]) == Dec("2000") and after["payment_terms_days"] == slow["payment_terms_days"]
    history = client.get(f"/api/v1/crm/customers/{slow['id']}/credit", headers=shop["owner"]).json()
    assert Dec(history[0]["credit_limit"]) == Dec("2000") and "Intelligence" in history[0]["reason"]


def test_credit_given_to_an_overdue_customer_can_be_held_from_the_invoice_finding(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    risky = credit_customer(client, shop, name="Risky Buyer", limit="9000")
    raw_invoice(shop, "RB-OLD", risky["id"], TODAY - timedelta(days=50), TODAY - timedelta(days=20), "700.00")
    raw_invoice(shop, "RB-NEW", risky["id"], TODAY - timedelta(days=2), TODAY + timedelta(days=12), "200.00")
    run(shop, "pos.credit_to_overdue_customer")
    f = finding_of(shop, "pos.credit_to_overdue_customer", text="RB-NEW")
    proposal = one_action(client, shop, f.id, "pos.hold_credit")
    assert proposal["params"] == {"customer_id": risky["id"], "credit_limit": "900"}          # 700 + 200 owed
    assert approve(client, shop, proposal, who="fm").json()["status"] == "executed"
    assert Dec(client.get(f"/api/v1/crm/customers/{risky['id']}", headers=shop["owner"]).json()["credit_limit"]) == 900


# --------------------------------------------------------------------------- nudges to whoever can decide
def alert_by_email(client, s) -> None:  # type: ignore[no-untyped-def]
    for channel in ("email",):
        r = client.put(f"/api/v1/notifications/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    setting(client, s, intel_alert_channel="email")


def told(shop, finding_id: Any) -> dict[str, str]:  # type: ignore[no-untyped-def]
    rows = system_rows(shop, "select recipient, body from kernel.notification where ref_type = 'intel.finding' "
                             "and ref_id = :r", r=finding_id)
    return {r.recipient: r.body for r in rows}


@pytest.fixture(scope="module")
def staff_shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.people.hooks  # noqa: F401
    from tests.people_helpers import make_people_shop, new_employee

    s = make_people_shop(client, registry, "Act People Co")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "messaging")
    s["juja_boss"] = s["user"]("jujaboss", "Branch Manager", s["juja"])
    s["ann"] = new_employee(client, s, "Ann Otieno", branch_id=str(s["branch_id"]))
    s["annual"] = client.post("/api/v1/people/leave-types", headers=s["hr"], json={
        "company_id": s["company"], "name": "Annual", "days_per_year": "21"}).json()["id"]
    alert_by_email(client, s)
    return s


def pending_leave(shop, employee: dict[str, Any], days_ago: int) -> str:  # type: ignore[no-untyped-def]
    inserted = system_rows(
        shop, "insert into people.leave_request (tenant_id, employee_id, leave_type_id, start_date, end_date, days, "
              "status, created_at) values (kernel.current_tenant(), :e, :l, '2026-12-20', '2026-12-22', 3, 'pending', "
              "now() - make_interval(days => :d)) returning id", e=employee["id"], l=shop["annual"], d=days_ago)
    return str(inserted[0].id)


def test_a_waiting_leave_request_nudges_the_people_who_can_decide(client, staff_shop) -> None:  # type: ignore[no-untyped-def]
    s = staff_shop
    set_level(client, s, 3)
    leave = pending_leave(s, s["ann"], 9)
    run(s, "people.leave_waiting")
    f = finding_of(s, "people.leave_waiting", entity=leave)
    proposal = one_action(client, s, f.id, "people.nudge_approver")
    # leave.approve at the employee's branch: HR and the HQ managers and the owner, not the Juja manager
    code = s["code"]
    names = proposal["facts"]["Will be told"].split(", ")
    assert "hr" in names and "manager" in names and "jujaboss" not in names and "cashier" not in names
    assert proposal["needs_permission"] == "findings.manage"
    done = approve(client, s, proposal)
    assert done.json()["status"] == "executed", done.text
    got = told(s, f.id)
    assert f"hr@{code}.test" in got and f"manager@{code}.test" in got and f"owner@{code}.test" in got
    assert f"jujaboss@{code}.test" not in got and f"cashier@{code}.test" not in got
    assert all("Ann Otieno asked for" in body for body in got.values())
    count = len(got)
    approve(client, s, proposal)
    assert len(told(s, f.id)) == count                                         # asked twice, told once
    # decided meanwhile: nobody is bothered
    other = pending_leave(s, s["ann"], 10)
    run(s, "people.leave_waiting")
    g = finding_of(s, "people.leave_waiting", entity=other)
    second = one_action(client, s, g.id, "people.nudge_approver")
    system_rows(s, "update people.leave_request set status = 'approved' where id = :i returning id", i=other)
    late = approve(client, s, second)
    assert late.json()["status"] == "failed" and "decided already" in late.json()["result"]["message"]
    assert told(s, g.id) == {}


def test_without_an_alert_channel_there_is_nobody_to_nudge_with(client, staff_shop) -> None:  # type: ignore[no-untyped-def]
    s = staff_shop
    set_level(client, s, 3)
    setting(client, s, intel_alert_channel="off")
    leave = pending_leave(s, s["ann"], 12)
    run(s, "people.leave_waiting")
    f = finding_of(s, "people.leave_waiting", entity=leave)
    assert actions_of(client, s, f.id) == []
    setting(client, s, intel_alert_channel="email")


def test_a_nudge_runs_by_itself_under_a_rule_and_only_once(client, staff_shop) -> None:  # type: ignore[no-untyped-def]
    s = staff_shop
    set_level(client, s, 4)
    rule = client.post(f"{INTEL}/automation/rules", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "action_type": "people.nudge_approver", "daily_cap": 3})
    assert rule.status_code == 201, rule.text
    leave = pending_leave(s, s["ann"], 14)
    result = run(s, "people.leave_waiting")
    assert result.acted >= 1
    f = finding_of(s, "people.leave_waiting", entity=leave)
    done = one_action(client, s, f.id, "people.nudge_approver")
    assert done["status"] == "executed" and done["decided_by"] is None
    assert done["result"]["message"].startswith("Reminder sent to ")
    count = len(told(s, f.id))
    assert count >= 3
    run(s, "people.leave_waiting")
    assert len(told(s, f.id)) == count
    audited = system_rows(s, "select channel, user_id from kernel.audit_log where action = 'intel.action.executed' "
                             "and entity_id = :e", e=done["id"])
    assert [(a.channel, a.user_id) for a in audited] == [("intelligence", None)]
    client.patch(f"{INTEL}/automation/rules/{rule.json()['id']}", headers=s["owner"], json={"enabled": False})
    set_level(client, s, 1)


def test_who_a_waiting_decision_is_waiting_for() -> None:
    from ziira.modules.people.action_providers import LEAVE, RUN, decider_permission

    assert decider_permission(LEAVE, "pending") == "leave.approve"
    assert decider_permission(RUN, "calculated") == "payroll.approve"
    assert decider_permission(RUN, "pending_approval") == "payroll.approve"
    assert decider_permission(RUN, "approved") == "payroll.pay"
    assert decider_permission(RUN, "posted") == "payroll.pay"


@pytest.fixture(scope="module")
def books(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.finance.hooks  # noqa: F401
    from tests.finance_helpers import FIN, make_books_shop

    s = make_books_shop(client, registry, "Act Books Co")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "messaging")
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    s["company"] = str(s["company_id"])
    made = client.post(f"{FIN}/companies/{s['company']}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in made}
    s["fm"] = s["user"]("fm", "Finance Manager", None)
    s["clerk"] = s["user"]("clerk", "Accountant", None)
    alert_by_email(client, s)
    return s


def test_a_reconciliation_left_open_nudges_those_who_reconcile(client, books) -> None:  # type: ignore[no-untyped-def]
    s = books
    set_level(client, s, 3)
    from datetime import UTC, datetime

    recon = system_rows(
        s, "insert into finance.bank_reconciliation (tenant_id, created_at, company_id, account_id, statement_date, "
           "statement_balance, book_balance, difference, status) values (kernel.current_tenant(), :ca, :c, :a, :d, 0, "
           "0, 0, 'in_progress') returning id", ca=datetime.now(UTC) - timedelta(days=40), c=s["company"],
        a=s["acc"]["1020"], d=date.today() - timedelta(days=1))[0].id
    with system(s) as db:
        engine.run_company(db, s["company_id"], today=datetime.now(UTC).date(), only={"finance.stale_reconciliation"})
    f = finding_of(s, "finance.stale_reconciliation", entity=recon)
    proposal = one_action(client, s, f.id, "finance.ask_for_reconciliation")
    assert "clerk" in proposal["facts"]["Will be told"] and "fm" in proposal["facts"]["Will be told"]
    assert proposal["facts"]["Open for (days)"] == "40"
    assert approve(client, s, proposal, who="clerk").status_code == 403      # an accountant manages no findings
    done = approve(client, s, proposal, who="fm")
    assert done.json()["status"] == "executed", done.text
    got = told(s, f.id)
    assert f"clerk@{s['code']}.test" in got and f"fm@{s['code']}.test" in got
    assert f"manager@{s['code']}.test" not in got                            # a branch manager does not reconcile
    # finished meanwhile: no more nudges
    system_rows(s, "update finance.bank_reconciliation set status = 'completed' where id = :i returning id", i=recon)
    again = approve(client, s, proposal, who="fm")
    assert again.json()["status"] == "executed"                              # already done: returned as it was


def test_an_exceptions_backlog_nudges_the_reviewers(client, books) -> None:  # type: ignore[no-untyped-def]
    s = books
    set_level(client, s, 3)
    for n in range(4):
        system_rows(s, "insert into kernel.exception_item (tenant_id, unit_name, kind, severity, company_id, message, "
                       "dedupe_key, created_at) values (kernel.current_tenant(), 'test', 'old', 'low', :c, :m, :k, "
                       "now() - interval '20 days') returning id", c=s["company"], m=f"Old item {n}", k=f"old-{n}")
    from datetime import UTC, datetime

    with system(s) as db:
        engine.run_company(db, s["company_id"], today=datetime.now(UTC).date(), only={"controls.exceptions_backlog"})
    f = finding_of(s, "controls.exceptions_backlog", text="4 exceptions have waited")
    proposal = one_action(client, s, f.id, "intel.nudge_exceptions_reviewers")
    assert proposal["facts"]["Waiting"] == "4"
    done = approve(client, s, proposal, who="fm")
    assert done.json()["status"] == "executed", done.text
    got = told(s, f.id)
    assert f"fm@{s['code']}.test" in got and f"boss@{s['code']}.test" in got       # exceptions.manage, company-wide
    assert f"manager@{s['code']}.test" not in got                                   # one branch only: not a company item
    assert f"clerk@{s['code']}.test" not in got and f"cashier@{s['code']}.test" not in got
    system_rows(s, "update kernel.exception_item set status = 'resolved' where unit_name = 'test' returning id")
    again = approve(client, s, proposal, who="fm")
    assert again.json()["status"] == "executed"
