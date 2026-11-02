"""The simple start: a plan needs only a name and a price (its code and the item it is invoiced as are made for it),
and a member with no credit limit can still be signed up and invoiced."""

from tests.gym_helpers import M, customer, make_gym_shop, rows, scalar


def test_a_plan_with_only_a_name_and_a_price_works_end_to_end(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_gym_shop(client, registry, "Gym Simple Start")
    co = str(shop["company_id"])
    made = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": co, "name": "Monthly gym", "fee": "3500", "billing_interval": "month",
        "invoice_as_plan_name": True})
    assert made.status_code == 201, made.text
    plan = made.json()
    assert plan["code"] == "MONTHLY-GYM" and plan["service_product_id"]
    name = scalar(shop, "select name from products.product where id = :p", p=plan["service_product_id"])
    kind = scalar(shop, "select product_type from products.product where id = :p", p=plan["service_product_id"])
    assert (name, kind) == ("Monthly gym", "service")
    # the same name again: a second code, and the same item is used
    again = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": co, "name": "Monthly gym", "fee": "4000", "billing_interval": "month",
        "invoice_as_plan_name": True}).json()
    assert again["code"] == "MONTHLY-GYM-2" and again["service_product_id"] == plan["service_product_id"]
    # a brand-new person with no credit limit set is signed up and invoiced
    newcomer = customer(client, shop, "Newcomer", limit="0")
    r = client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": plan["id"], "customer_id": newcomer["id"], "branch_id": str(shop["branch_id"])})
    assert r.status_code == 201, r.text
    total = scalar(shop, "select total from pos.sales_invoice where customer_id = :c", c=newcomer["id"])
    assert total is not None and float(total) == 3500.0


def test_a_plan_still_uses_the_item_it_is_given_and_a_code_typed_by_hand(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_gym_shop(client, registry, "Gym Simple Explicit")
    r = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "vip", "name": "Vip", "fee": "100",
        "billing_interval": "month", "service_product_id": shop["delivery"], "invoice_as_plan_name": True})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "VIP" and r.json()["service_product_id"] == shop["delivery"]
    assert rows(shop, "select 1 from products.product where name = 'Vip'") == []        # no extra item was made


def test_a_customer_on_hold_is_still_refused(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_gym_shop(client, registry, "Gym Simple Hold")
    plan = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Basic", "fee": "100", "billing_interval": "month",
        "invoice_as_plan_name": True}).json()
    held = customer(client, shop, "On Hold", limit="0")
    r = client.patch(f"/api/v1/crm/customers/{held['id']}", headers=shop["owner"], json={"status": "on_hold"})
    assert r.status_code == 200, r.text
    out = client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": plan["id"], "customer_id": held["id"], "branch_id": str(shop["branch_id"])})
    assert out.status_code == 422 and "on hold" in out.text
