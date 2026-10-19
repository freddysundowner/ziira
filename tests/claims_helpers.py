"""Shared setup for the Claims tests: a sales shop (POS, CRM, Finance) with Jobs, Claims, Intelligence and the Command
Center on, a payer (an insurer with terms, linked to a customer account with credit), an insured customer, and the
service item claim invoices are made under (DELIVERY, VAT 16% inclusive)."""

from decimal import Decimal

from tests.pos_helpers import credit_customer, make_sales_shop

CLAIMS = "/api/v1/claims"


def make_claims_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """The sales shop with Claims on. `payer` is the insurer's payer record (labour 100.00/h, body 150.00/h, parts discount
    10%, 30 days to pay) and `payer_customer` its customer account; `customer` is the insured customer; users: `rep` (Sales
    Rep at HQ), `fm` (Finance Manager), the sales shop's manager and cashier."""
    shop = make_sales_shop(client, registry, name, stock="20")
    for unit in ("jobs", "claims", "intel", "command"):
        registry.enable(shop["tenant_id"], unit)
    owner, co = shop["owner"], str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=owner, json={"timezone": "UTC"})
    r = client.patch(f"{CLAIMS}/settings", params={"company_id": co}, headers=owner,
                     json={"invoice_product_id": shop["delivery"]})
    assert r.status_code == 200, r.text
    shop["rep"] = shop["user"]("rep", "Sales Rep", shop["branch_id"])
    shop["payer_customer"] = credit_customer(client, shop, name="Jubilee Claims", limit="1000000", terms=30,
                                             phone="254700000001")
    shop["customer"] = credit_customer(client, shop, name="Wanjiku Motors", limit="100000", terms=14,
                                       phone="254712345678")
    made = client.post(f"{CLAIMS}/payers", headers=owner, json={
        "company_id": co, "name": "Jubilee Insurance", "kind": "insurer", "customer_id": shop["payer_customer"]["id"],
        "labour_rates": {"mechanical": "100.00", "body": "150.00"}, "parts_discount_pct": "10", "payment_days": 30,
        "required_documents": ["Assessor report", "Photos"],
        "contacts": [{"name": "Claims desk", "phone": "254700000009", "email": "claims@jubilee.test"}],
        "estimate_email": "claims@jubilee.test", "approval_limit": "100000"})
    assert made.status_code == 201, made.text
    shop["payer"] = made.json()
    return shop


def new_claim(client, shop, who: str = "owner", **extra):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]),
            "payer_id": shop["payer"]["id"], "customer_id": shop["customer"]["id"], "subject": "Toyota Corolla KAA 123B",
            "policy_number": "POL-778", "claim_number": "JUB-2026-0042", "loss_date": "2026-10-01",
            "excess_amount": "500.00", **extra}
    r = client.post(f"{CLAIMS}/claims", headers=shop[who], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def line(kind: str, description: str, quantity: str, price: str | None, **extra):  # type: ignore[no-untyped-def]
    body = {"kind": kind, "description": description, "quantity": quantity, **extra}
    if price is not None:
        body["unit_price"] = price
    return body


def estimate(client, shop, claim, lines, who: str = "owner", **extra):  # type: ignore[no-untyped-def]
    r = client.post(f"{CLAIMS}/claims/{claim['id']}/estimates", headers=shop[who], json={"lines": lines, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def submit(client, shop, est, who: str = "owner", **body):  # type: ignore[no-untyped-def]
    r = client.post(f"{CLAIMS}/estimates/{est['id']}/submit", headers=shop[who], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def answer(client, shop, est, answers, who: str = "owner", via: str = "phone", name: str = "Peter Assessor", **extra):  # type: ignore[no-untyped-def]
    r = client.post(f"{CLAIMS}/estimates/{est['id']}/responses", headers=shop[who],
                    json={"by_name": name, "via": via, "answers": answers, **extra})
    return r


def by_description(est, description):  # type: ignore[no-untyped-def]
    return next(x for x in est["lines"] if x["description"] == description)


def get_claim(client, shop, claim, who: str = "owner"):  # type: ignore[no-untyped-def]
    r = client.get(f"{CLAIMS}/claims/{claim['id']}", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def money(value) -> Decimal:  # type: ignore[no-untyped-def]
    return Decimal(str(value))
