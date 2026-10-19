"""The shared invoice function other units use for services: `pos.public.issue_invoice_from_lines`."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import UUID, uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system
from ziira.modules.pos.public import InvoiceLineIn, invoice_for_source, issue_invoice_from_lines
from ziira.sdk import ValidationFailed


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_sales_shop(client, registry, "Svc Invoice Co", stock="10")


def issue(shop, customer, lines, source_id, **kw):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return issue_invoice_from_lines(
            s, company_id=shop["company_id"], branch_id=shop["branch_id"], customer_id=UUID(customer["id"]),
            lines=lines, source_type="test.source", source_id=source_id, **kw)


def test_service_lines_are_invoiced_with_tax_and_posted(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Consulting Client", limit="5000", terms=14)
    delivery = UUID(shop["delivery"])
    before = {c: balance(shop, c) for c in ("1100", "4000", "2200")}
    sid = uuid4()
    # 3 h x 100.00 = 300.00 and 1 x 58.00 less 8.00 discount = 50.00, both VAT 16% inclusive: 350.00 total,
    # tax = 350 x 16 / 116 = 48.28 (300 -> 41.38, 50 -> 6.90)
    ref = issue(shop, cust, [InvoiceLineIn(delivery, "Design work, 3 h", Dec(3), Dec("100.00")),
                             InvoiceLineIn(delivery, "Courier", Dec(1), Dec("58.00"), discount=Dec("8.00"))], sid,
                due_days=7, memo="June work")
    assert ref.total == Dec("350.00") and ref.tax_total == Dec("48.28") and ref.number.startswith("INV-HQ-")
    assert (ref.due_date - ref.issue_date).days == 7
    inv = client.get(f"{POS}/invoices/{ref.id}", headers=shop["owner"]).json()
    assert inv["customer_id"] == cust["id"] and Dec(inv["total"]) == 350
    after = {c: balance(shop, c) for c in before}
    assert after["1100"] - before["1100"] == 350 and after["4000"] - before["4000"] == -Dec("301.72")
    assert after["2200"] - before["2200"] == -Dec("48.28")
    assert one(shop, "select description from pos.sales_invoice_line where invoice_id = :i and line_no = 1",
               i=ref.id) == "Design work, 3 h"


def test_the_same_source_gives_the_same_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Twice Client")
    sid = uuid4()
    line = [InvoiceLineIn(UUID(shop["delivery"]), "Hours", Dec(1), Dec("116.00"))]
    first = issue(shop, cust, line, sid)
    second = issue(shop, cust, line, sid)
    assert first.id == second.id and first.number == second.number
    assert one(shop, "select count(*) from pos.sales_invoice where source_id = :s", s=sid) == 1
    with system(shop) as s:
        assert invoice_for_source(s, "test.source", sid).id == first.id          # type: ignore[union-attr]
        assert invoice_for_source(s, "test.source", uuid4()) is None
    # cancelled: the source may be invoiced again
    assert client.post(f"{POS}/invoices/{first.id}/cancel", headers=shop["fm"], json={"reason": "Test"}).status_code == 200
    third = issue(shop, cust, line, sid)
    assert third.id != first.id


def test_bad_input_and_rollback(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Rollback Client", limit="100", terms=5)
    delivery = UUID(shop["delivery"])
    sid = uuid4()
    with pytest.raises(ValidationFailed):
        issue(shop, cust, [], sid)
    with pytest.raises(ValidationFailed):
        issue(shop, cust, [InvoiceLineIn(delivery, "x", Dec(0), Dec("10"))], sid)
    with pytest.raises(Exception, match="credit limit"):                           # 232 > 100: refused, nothing left
        issue(shop, cust, [InvoiceLineIn(delivery, "Big", Dec(1), Dec("232.00"))], sid)
    assert one(shop, "select count(*) from pos.sales_invoice where source_id = :s", s=sid) == 0


def test_the_caller_needs_invoices_manage(client, shop) -> None:  # type: ignore[no-untyped-def]
    """A signed-in cashier (no 'invoices.manage') is refused by the invoice service this function uses."""
    from ziira.kernel.context import RequestContext, set_context

    cust = credit_customer(client, shop, name="Perm Client")
    with system(shop) as s:
        ctx = RequestContext(tenant_id=shop["tenant_id"], user_id=uuid4())
        set_context(ctx)
        with pytest.raises(Exception, match="(?i)permission|not allowed"):
            issue_invoice_from_lines(
                s, company_id=shop["company_id"], branch_id=shop["branch_id"], customer_id=UUID(cust["id"]),
                lines=[InvoiceLineIn(UUID(shop["delivery"]), "Hours", Dec(1), Dec("58.00"))],
                source_type="test.source", source_id=uuid4())
