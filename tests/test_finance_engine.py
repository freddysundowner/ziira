"""The posting engine called directly: every guard, without going through events or HTTP."""

from datetime import date
from decimal import Decimal as Dec
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import FIN, make_books_shop
from tests.stock_helpers import system
from ziira.modules.finance.domain.entries import Line
from ziira.modules.finance.services import books, posting
from ziira.modules.finance.services.posting import EntryRequest
from ziira.sdk import Conflict, ValidationFailed, company_today


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Engine Co")
    co2 = uuid4()
    with system(s) as db:
        db.execute(text("insert into kernel.company (id, tenant_id, name, base_currency) values (:i, :t, 'Other Ltd', 'USD')"),
                   {"i": str(co2), "t": str(s["tenant_id"])})
        books.ensure_books(db, s["company_id"])
        books.ensure_books(db, co2)
        rows = db.execute(text("select company_id, code, id from finance.account")).all()
    s["co2"] = co2
    s["acc"] = {(c, code): i for c, code, i in rows}
    return s


def request(shop, debit="6000", credit="1020", **kw):  # type: ignore[no-untyped-def]
    co = kw.pop("company_id", shop["company_id"])
    amount = kw.pop("amount", Dec("10"))
    lines = kw.pop("lines", None) or [Line(shop["acc"][(co, debit)], debit=amount),
                                      Line(shop["acc"][(co, credit)], credit=amount)]
    return EntryRequest(**{"company_id": co, "entry_date": date(2026, 10, 13), "journal_code": "GEN", "lines": lines,
                           "description": "t", **kw})


def post(shop, req):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return posting.post_entry(s, req)


def test_a_valid_entry(shop) -> None:  # type: ignore[no-untyped-def]
    entry = post(shop, request(shop, source_type="t", source_id=uuid4(), is_manual=True))
    assert entry.number.startswith("GEN-") and entry.entry_date == date(2026, 10, 13)
    with system(shop) as s:
        event = s.execute(text("select payload from kernel.event_outbox where event_type = 'journal.posted' "
                               "and aggregate_id = :i"), {"i": str(entry.id)}).scalar_one()
    assert event["number"] == entry.number and Dec(str(event["total"])) == 10


def test_the_lines_must_be_good(shop) -> None:  # type: ignore[no-untyped-def]
    other = shop["acc"][(shop["co2"], "6000")]
    mine = shop["acc"][(shop["company_id"], "6000")]
    cash = shop["acc"][(shop["company_id"], "1020")]
    with pytest.raises(ValidationFailed, match="Account not found"):
        post(shop, request(shop, lines=[Line(other, debit=Dec(5)), Line(cash, credit=Dec(5))]))     # another company's
    with pytest.raises(ValidationFailed, match="Account not found"):
        post(shop, request(shop, lines=[Line(uuid4(), debit=Dec(5)), Line(cash, credit=Dec(5))]))
    with pytest.raises(ValidationFailed, match="does not balance"):
        post(shop, request(shop, lines=[Line(mine, debit=Dec(5)), Line(cash, credit=Dec(4))]))
    with pytest.raises(ValidationFailed, match="Journal 'NOPE' not found"):
        post(shop, request(shop, journal_code="NOPE"))
    with pytest.raises(ValidationFailed, match="Branch not found"):
        post(shop, request(shop, lines=[Line(mine, debit=Dec(5), branch_id=uuid4()), Line(cash, credit=Dec(5))]))
    with pytest.raises(ValidationFailed, match="Company not found"):
        post(shop, request(shop, company_id=uuid4(), lines=[Line(mine, debit=Dec(5)), Line(cash, credit=Dec(5))]))


def test_inactive_and_control_accounts(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    stock = shop["acc"][(shop["company_id"], "1200")]
    cash = shop["acc"][(shop["company_id"], "1020")]
    lines = [Line(stock, debit=Dec(5)), Line(cash, credit=Dec(5))]
    with pytest.raises(ValidationFailed, match="cannot be posted to by hand"):
        post(shop, request(shop, lines=lines))
    assert post(shop, request(shop, lines=lines, automatic=True))                    # the system may
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update finance.account set is_active = false where id = :i"), {"i": str(cash)})
    try:
        with pytest.raises(ValidationFailed, match="not active"):
            post(shop, request(shop, lines=lines, automatic=True))
    finally:
        with tenant_session(shop["tenant_id"], admin=True) as s:
            s.execute(text("update finance.account set is_active = true where id = :i"), {"i": str(cash)})


def test_a_source_document_is_posted_once(shop) -> None:  # type: ignore[no-untyped-def]
    source = uuid4()
    post(shop, request(shop, source_type="thing", source_id=source))
    with pytest.raises(Conflict, match="already been posted"):
        post(shop, request(shop, source_type="thing", source_id=source))
    # the same id from another company is a different document
    other = request(shop, company_id=shop["co2"], source_type="thing", source_id=source)
    assert post(shop, other)


def test_unknown_companies_have_no_books(shop) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed, match="Company not found"), system(shop) as s:
        books.ensure_books(s, uuid4())


def test_periods_are_created_for_any_date(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        first = books.get_or_create_period(s, shop["company_id"], date(2030, 2, 14))
        again = books.get_or_create_period(s, shop["company_id"], date(2030, 2, 28))
        assert first.id == again.id and (first.start_date, first.end_date) == (date(2030, 2, 1), date(2030, 2, 28))
        assert books.get_or_create_period(s, shop["company_id"], date(2030, 3, 1)).id != first.id


def test_an_empty_recipe_posts_nothing(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        assert posting.post_from_recipe(s, company_id=shop["company_id"], doc_type="sale", journal_code="SAL",
                                        entry_date=date(2026, 10, 13), recipe=[], context={}, branch_id=None,
                                        source_type="sale", source_id=uuid4()) is None


def test_when_even_the_current_period_is_closed_the_document_is_refused(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    with system(shop) as s:
        books.get_or_create_period(s, shop["company_id"], date(2026, 1, 15))
        today = books.get_or_create_period(s, shop["company_id"], company_today(s, shop["company_id"]))
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update finance.period set status = 'locked' where id = :i or start_date = '2026-01-01'"),
                  {"i": str(today.id)})
    try:
        with pytest.raises(ValidationFailed, match="no open accounting period"):
            post(shop, request(shop, entry_date=date(2026, 1, 20), automatic=True))
    finally:
        with tenant_session(shop["tenant_id"], admin=True) as s:
            s.execute(text("update finance.period set status = 'open' where id = :i"), {"i": str(today.id)})


def test_the_api_refuses_a_company_the_user_cannot_see(client, shop) -> None:  # type: ignore[no-untyped-def]
    cashier = shop["cashier"]
    assert client.get(f"{FIN}/accounts", headers=cashier).status_code == 403
    r = client.get(f"{FIN}/accounts", headers=shop["owner"], params={"company_id": str(uuid4())})
    assert r.status_code == 200 and r.json() == []                    # nothing there to see
    other = shop["user"]("engineclerk", "Accountant", shop["juja"])    # reaches only one branch of one company
    assert client.get(f"{FIN}/accounts", headers=other, params={"company_id": str(shop["co2"])}).status_code == 404
