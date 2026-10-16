"""Printed receipts, invoices and payment receipts: text for thermal printers, HTML, and data."""

from decimal import Decimal as Dec  # noqa: N817

import pytest

from tests.pos_helpers import POS, credit_customer, line, make_sales_shop, sell
from ziira.modules.pos.domain.printing import PrintDocument, PrintLine, VatRow, render_html, render_text
from ziira.modules.pos.services import printing


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_sales_shop(client, registry, "Print Co")


def test_a_till_receipt_in_text(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop, lines=[line(shop, "cement", "2"), line(shop, "paint", "1")],
                payments=[{"method": "cash", "amount": "500.00"}])
    assert sale.status_code == 201, sale.text
    sale = sale.json()
    r = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"], params={"format": "text"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    rows = r.text.splitlines()
    assert all(len(x) <= 40 for x in rows)
    assert "Print Co" in rows[0] and sale["number"] in r.text and "RECEIPT" in r.text
    assert "TOTAL" in r.text and "464.00" in r.text and "CASH" in r.text
    assert "16% on" in r.text and "Thank you for shopping with us" in r.text
    assert "COPY" not in r.text
    narrow = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"],
                        params={"format": "text", "width": 32, "copy": True})
    assert all(len(x) <= 32 for x in narrow.text.splitlines()) and "*** COPY ***" in narrow.text
    assert client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"],
                      params={"format": "text", "width": 20}).status_code == 422


def test_the_same_receipt_as_data_and_as_html(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop).json()
    data = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"]).json()
    assert data["title"] == "Receipt" and data["number"] == sale["number"] and data["is_copy"] is False
    assert Dec(data["totals"][-1]["amount"]) == 116 and data["lines"][0]["description"]
    vat = data["vat"][0]
    assert Dec(vat["rate"]) == 16 and Dec(vat["tax"]) == Dec("16.00") and Dec(vat["net"]) == Dec("100.00")
    html = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"], params={"format": "html"})
    assert html.headers["content-type"].startswith("text/html") and "<table" in html.text and sale["number"] in html.text
    assert client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"],
                      params={"format": "pdf"}).status_code == 422


def test_the_footer_is_a_company_setting(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop).json()
    path = f"/api/v1/companies/{shop['company_id']}/settings"
    changed = client.patch(path, headers=shop["owner"], json={"receipt_footer": "Goods once sold are not returnable"})
    assert changed.status_code == 200, changed.text
    text = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"], params={"format": "text"}).text
    assert "not returnable" in text and "Thank you" not in text
    assert client.patch(path, headers=shop["owner"], json={"receipt_footer": "a\nb"}).status_code == 422
    assert client.patch(path, headers=shop["owner"], json={"receipt_footer": "x" * 201}).status_code == 422


def test_a_credit_sale_receipt_says_it_is_on_account(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, "Mama Pima")
    sale = sell(client, shop, lines=[line(shop, "cement", "1")], payments=[{"method": "credit", "amount": "116.00"}],
                customer_id=cust["id"]).json()
    text = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"], params={"format": "text"}).text
    assert "Mama Pima" in text and "On account: invoice" in text


def test_an_invoice_and_its_payment_receipt(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, "Duka <b>Kubwa</b>")
    inv = client.post(f"{POS}/invoices", headers=shop["owner"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "terms_days": 30, "notes": "Deliver to <script>x</script>",
        "lines": [{"product_id": shop["cement"], "quantity": "2"}]})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    paid = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "100.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    assert paid.status_code == 201, paid.text
    text = client.get(f"{POS}/invoices/{inv['id']}/print", headers=shop["fm"], params={"format": "text"}).text
    assert "INVOICE" in text and inv["number"] in text and "Due:" in text
    assert "BALANCE DUE" in text and "132.00" in text and "Paid" in text
    html = client.get(f"{POS}/invoices/{inv['id']}/print", headers=shop["fm"], params={"format": "html"}).text
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Kubwa" in html          # user text is escaped
    receipt = client.get(f"{POS}/receipts/{paid.json()['id']}/print", headers=shop["fm"], params={"format": "text"}).text
    assert "PAYMENT RECEIPT" in receipt and "AMOUNT RECEIVED" in receipt and f"Invoice {inv['number']}" in receipt
    reversed_ = client.post(f"{POS}/receipts/{paid.json()['id']}/reverse", headers=shop["fm"], json={"reason": "Bounced"})
    assert reversed_.status_code == 200
    assert "REVERSED" in client.get(f"{POS}/receipts/{paid.json()['id']}/print", headers=shop["fm"],
                                    params={"format": "text"}).text
    cancelled = client.post(f"{POS}/invoices/{inv['id']}/cancel", headers=shop["owner"], json={"reason": "Wrong customer"})
    if cancelled.status_code == 200:
        assert "CANCELLED" in client.get(f"{POS}/invoices/{inv['id']}/print", headers=shop["fm"],
                                         params={"format": "text"}).text


def test_who_may_print_what(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop).json()
    cust = credit_customer(client, shop, "Hidden Debtor")
    inv = client.post(f"{POS}/invoices", headers=shop["owner"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "lines": [{"product_id": shop["cement"], "quantity": "1"}]}
    ).json()
    assert client.get(f"{POS}/invoices/{inv['id']}/print", headers=shop["cashier"]).status_code == 403
    assert client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["storekeeper"]).status_code == 403
    missing = "00000000-0000-0000-0000-000000000001"
    for path in (f"sales/{missing}/receipt", f"invoices/{missing}/print", f"receipts/{missing}/print"):
        assert client.get(f"{POS}/{path}", headers=shop["owner"]).status_code == 404, path


def test_extras_from_plugins_are_added_and_a_broken_one_is_ignored(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Good:
        def lines(self, session, kind, document_id):  # type: ignore[no-untyped-def]
            return [f"CU {kind}"]

    class Broken:
        def lines(self, session, kind, document_id):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    monkeypatch.setattr(printing, "implementations", lambda session, name: [Broken(), Good()])
    assert printing._extras(None, "sale", None) == ["CU sale"]                         # type: ignore[arg-type]


def test_rendering_rules() -> None:
    doc = PrintDocument(
        title="Receipt", number="R-1", header=["A very long company name that does not fit on a narrow strip of paper"],
        meta=[("Customer", "X" * 60)], lines=[PrintLine("Item " + "y" * 50, Dec("1.5"), Dec("10"), Dec("15"))],
        vat=[VatRow(Dec(16), Dec("12.93"), Dec("2.07"))], totals=[("TOTAL", Dec("1234567.5"))])
    for width in (32, 40, 48):
        assert all(len(x) <= width for x in render_text(doc, width).splitlines())
    assert "1,234,567.50" in render_text(doc) and "1.5 x 10.00" in render_text(doc)
    with pytest.raises(ValueError):
        render_text(doc, 10)
    hostile = PrintDocument(title="<i>", number="&", header=['"><script>'], meta=[("a", "<u>")], totals=[])
    assert "<script>" not in render_html(hostile) and "<u>" not in render_html(hostile) and "<i>" not in render_html(hostile)


def test_the_receipt_time_is_the_companys_clock_not_utc(client, shop) -> None:  # type: ignore[no-untyped-def]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    sale = sell(client, shop).json()
    data = client.get(f"{POS}/sales/{sale['id']}/receipt", headers=shop["cashier"]).json()
    shown = dict(data["meta"])["Date"]
    sold = datetime.fromisoformat(sale["sold_at"].replace("Z", "+00:00"))
    assert shown == sold.astimezone(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M")      # the fixture company's zone
    assert shown != sold.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")                 # three hours apart
    assert client.get("/api/v1/companies", headers=shop["owner"]).json()[0]["timezone"] == "Africa/Nairobi"
