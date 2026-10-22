"""Finance: the chart of accounts, posting rules, reports, who may do what, and the integrity check."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest

from tests.finance_helpers import FIN, balance, make_books_shop, opening, publish_sale
from tests.stock_helpers import system

ROLES = ["Owner", "Branch Manager", "Finance Manager", "Accountant", "Storekeeper", "Cashier", "Sales Rep", "HR"]


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Admin Books")
    opening(client, s)
    s["people"] = {"Owner": s["owner"]}
    for role in ROLES[1:]:
        s["people"][role] = s["user"]("fin" + role.lower().replace(" ", ""), role, None)       # company-wide
    accounts = client.get(f"{FIN}/accounts", headers=s["owner"], params={"company_id": str(s["company_id"])}).json()
    s["acc"] = {a["code"]: a["id"] for a in accounts}
    return s


# --------------------------------------------------------------------------- chart of accounts
def new_account(client, shop, **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "code": "6700", "name": "Repairs", "type": "expense", **kw}
    return client.post(f"{FIN}/accounts", headers=shop["owner"], json=body)


def test_accounts_are_validated_and_unique(client, shop) -> None:  # type: ignore[no-untyped-def]
    ok = new_account(client, shop)
    assert ok.status_code == 201 and ok.json()["is_control"] is False and ok.json()["code"] == "6700"
    assert new_account(client, shop).status_code == 409                                    # codes are unique
    assert new_account(client, shop, code="6700 ").status_code == 409
    for change in ({"code": "bad code"}, {"code": ""}, {"code": "x" * 21}, {"code": "6702", "name": "  "},
                   {"code": "6702", "name": "x" * 201}, {"code": "6702", "type": "gadget"},
                   {"code": "6702", "parent_id": str(uuid4())},
                   {"code": "6701", "parent_id": shop["acc"]["4000"]},              # not the parent's type
                   {"code": "6702", "company_id": str(uuid4())}):
        assert new_account(client, shop, **change).status_code in (403, 422), change
    child = new_account(client, shop, code="6701", parent_id=ok.json()["id"])
    assert child.status_code == 201 and child.json()["parent_id"] == ok.json()["id"]


def test_accounts_can_be_renamed_and_switched_off_carefully(client, shop) -> None:  # type: ignore[no-untyped-def]
    acc = client.post(f"{FIN}/accounts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "6710", "name": "Misc", "type": "expense"}).json()
    r = client.patch(f"{FIN}/accounts/{acc['id']}", headers=shop["owner"], json={"name": "Miscellaneous"})
    assert r.json()["name"] == "Miscellaneous"
    assert client.patch(f"{FIN}/accounts/{acc['id']}", headers=shop["owner"], json={"name": " "}).status_code == 422
    assert client.patch(f"{FIN}/accounts/{shop['acc']['1200']}", headers=shop["owner"],
                        json={"is_active": False}).status_code == 422                       # a control account
    assert client.patch(f"{FIN}/accounts/{shop['acc']['4000']}", headers=shop["owner"],
                        json={"is_active": False}).status_code == 422                       # a posting rule uses it
    assert client.patch(f"{FIN}/accounts/{shop['acc']['3000']}", headers=shop["owner"],
                        json={"is_active": False}).status_code == 200                       # unused and empty
    assert client.patch(f"{FIN}/accounts/{shop['acc']['3000']}", headers=shop["owner"],
                        json={"is_active": True}).status_code == 200
    assert client.patch(f"{FIN}/accounts/{uuid4()}", headers=shop["owner"], json={"name": "x"}).status_code == 404
    ids = {a["id"] for a in client.get(f"{FIN}/accounts", headers=shop["owner"]).json()}
    client.patch(f"{FIN}/accounts/{acc['id']}", headers=shop["owner"], json={"is_active": False})
    assert acc["id"] not in {a["id"] for a in client.get(f"{FIN}/accounts", headers=shop["owner"]).json()}
    assert acc["id"] in {a["id"] for a in client.get(f"{FIN}/accounts?include_inactive=true",
                                                      headers=shop["owner"]).json()} and ids


def test_an_account_with_a_balance_cannot_be_switched_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    d = client.post(f"{FIN}/manual-journals", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "entry_date": "2026-10-13", "description": "Rent", "lines": [
            {"account_id": shop["acc"]["6000"], "debit": "300"}, {"account_id": shop["acc"]["1020"], "credit": "300"}]})
    assert client.post(f"{FIN}/manual-journals/{d.json()['id']}/submit", headers=shop["owner"]).status_code == 200
    r = client.patch(f"{FIN}/accounts/{shop['acc']['6000']}", headers=shop["owner"], json={"is_active": False})
    assert r.status_code == 422 and "balance" in r.json()["message"]


# --------------------------------------------------------------------------- posting rules
def test_rules_are_data_and_a_specific_rule_overrides_the_general_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    from uuid import UUID

    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    owner, co = shop["owner"], str(shop["company_id"])
    rules = client.get(f"{FIN}/posting-rules", headers=owner, params={"company_id": co}).json()
    assert len(rules) > 15 and {r["doc_type"] for r in rules} >= {"stock_movement", "sale", "sale_return"}
    damage = client.post(f"{FIN}/accounts", headers=owner, json={
        "company_id": co, "code": "5290", "name": "Damaged goods", "type": "expense"}).json()
    r = client.post(f"{FIN}/posting-rules", headers=owner, json={
        "company_id": co, "doc_type": "stock_movement", "line_role": "shrinkage", "account_id": damage["id"],
        "side": "debit", "conditions": {"movement_type": "write_off"}})
    assert r.status_code == 201, r.text
    reasons = client.get("/api/v1/settings/reason-codes", headers=owner).json()
    write_off = next(x["id"] for x in reasons if x["category"] == "write_off")
    adjust = next(x["id"] for x in reasons if x["category"] == "stock_adjustment")
    shrinkage_before = balance(shop, "5100")

    def move(kind: str, reason: str) -> None:
        with system(shop) as s:
            post_movement(s, MovementRequest(
                company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["cement"]),
                quantity=Dec("-2"), movement_type=kind, source_type="t", source_id=uuid4(),
                reason_code_id=UUID(reason)))

    move("write_off", write_off)                         # the specific rule: this loss goes to "Damaged goods"
    assert balance(shop, "5290") == 20 and balance(shop, "5100") == shrinkage_before
    move("adjustment", adjust)                           # anything else still goes to the general shrinkage account
    assert balance(shop, "5290") == 20 and balance(shop, "5100") == shrinkage_before + 20


def test_rule_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co, acc = shop["owner"], str(shop["company_id"]), shop["acc"]

    def rule(**kw):  # type: ignore[no-untyped-def]
        return client.post(f"{FIN}/posting-rules", headers=owner, json={
            "company_id": co, "doc_type": "stock_movement", "line_role": "cogs", "account_id": acc["5000"],
            "side": "debit", **kw})

    for change in ({"doc_type": "payroll"}, {"line_role": "nonsense"}, {"line_role": "sales"}, {"side": "sideways"},
                   {"account_id": str(uuid4())}, {"conditions": {"colour": "red"}},
                   {"conditions": {"movement_type": "teleport"}}, {"priority": 0}, {"priority": 5000},
                   {"doc_type": "sale", "line_role": "cash", "conditions": {"movement_type": "sale"}}):
        assert rule(**change).status_code == 422, change
    assert rule(conditions={"movement_type": "sale"}).status_code == 201


def test_rules_can_be_repointed_but_the_last_general_rule_cannot_be_deleted(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    rules = {(r["doc_type"], r["line_role"], tuple(r["conditions"].items())): r for r in client.get(
        f"{FIN}/posting-rules", headers=owner, params={"company_id": co}).json()}
    general = rules[("stock_movement", "grni", ())]
    other = client.post(f"{FIN}/accounts", headers=owner, json={
        "company_id": co, "code": "2150", "name": "Accrued purchases", "type": "liability"}).json()
    r = client.put(f"{FIN}/posting-rules/{general['id']}", headers=owner, json={"account_id": other["id"]})
    assert r.status_code == 200 and r.json()["account_id"] == other["id"]
    assert client.put(f"{FIN}/posting-rules/{general['id']}", headers=owner,
                      json={"account_id": str(uuid4())}).status_code == 422
    assert client.delete(f"{FIN}/posting-rules/{general['id']}", headers=owner).status_code == 422
    assert client.delete(f"{FIN}/posting-rules/{uuid4()}", headers=owner).status_code == 404
    specific = client.post(f"{FIN}/posting-rules", headers=owner, json={
        "company_id": co, "doc_type": "stock_movement", "line_role": "grni", "account_id": other["id"],
        "side": "credit", "conditions": {"movement_type": "receipt"}}).json()
    assert client.delete(f"{FIN}/posting-rules/{specific['id']}", headers=owner).status_code == 204
    client.put(f"{FIN}/posting-rules/{general['id']}", headers=owner, json={"account_id": shop["acc"]["2100"]})


def test_a_missing_rule_stops_the_operation_clearly(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from ziira.kernel.db import tenant_session
    from ziira.sdk import ValidationFailed

    with tenant_session(shop["tenant_id"], admin=True) as s:                  # as if rules were removed behind our back
        s.execute(text("delete from finance.posting_rule where line_role = 'cogs'"))
    with pytest.raises(ValidationFailed, match="No posting rule for 'cogs' on 'stock_movement'"):
        publish_sale(shop, lines=[{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "1"}])
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text(
            "insert into finance.posting_rule (tenant_id, company_id, doc_type, line_role, account_id, side) "
            "values (:t, :c, 'stock_movement', 'cogs', :a, 'debit')"),
            {"t": str(shop["tenant_id"]), "c": str(shop["company_id"]), "a": shop["acc"]["5000"]})


# --------------------------------------------------------------------------- reports
def tb(client, shop, who="owner", **params):  # type: ignore[no-untyped-def]
    headers = shop[who] if isinstance(who, str) and who in shop else who
    return client.get(f"{FIN}/reports/trial-balance", headers=headers,
                      params={"company_id": str(shop["company_id"]), **params})


def test_the_trial_balance_balances_and_is_reproducible_for_any_past_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    publish_sale(shop, net="1000", tax="160", business_date="2026-09-10")
    snapshot = tb(client, shop, as_of="2026-09-30").json()
    assert snapshot["balanced"] and snapshot["total_debit"] == snapshot["total_credit"]
    publish_sale(shop, net="500", tax="80", business_date="2026-09-20")          # later postings, earlier date
    publish_sale(shop, net="900", tax="144", business_date="2026-10-02")
    again = tb(client, shop, as_of="2026-09-30").json()
    assert again["lines"] != snapshot["lines"]                                       # the 20 Sept sale is in it now
    assert tb(client, shop, as_of="2026-09-09").json()["total_debit"] != again["total_debit"]
    # reading the same date twice gives the same answer; later entries do not change earlier dates
    publish_sale(shop, net="1", tax="0.16", business_date="2026-10-03")
    assert tb(client, shop, as_of="2026-09-30").json() == again
    assert tb(client, shop, as_of="1999-01-01").json()["lines"] == []


def test_trial_balance_columns_and_filters(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = tb(client, shop, as_of="2030-01-01").json()
    by_code = {x["code"]: x for x in t["lines"]}
    assert Dec(by_code["4000"]["balance"]) == Dec(by_code["4000"]["credit"]) - Dec(by_code["4000"]["debit"])
    assert Dec(by_code["1200"]["balance"]) == Dec(by_code["1200"]["debit"]) - Dec(by_code["1200"]["credit"])
    assert "6900" not in by_code and "6900" in {x["code"] for x in tb(client, shop, as_of="2030-01-01",
                                                                      include_zero="true").json()["lines"]}
    juja = tb(client, shop, as_of="2030-01-01", branch_id=str(shop["juja"])).json()
    assert juja["balanced"] and [x["code"] for x in juja["lines"]] in ([], ["1200"])
    assert tb(client, shop, as_of="2030-01-01", branch_id=str(uuid4())).status_code == 422
    assert tb(client, shop, as_of="soon").status_code == 422
    assert client.get(f"{FIN}/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(uuid4()), "as_of": "2030-01-01"}).status_code in (403, 404, 422)


def test_the_general_ledger_has_an_opening_balance_and_a_running_balance(client, shop) -> None:  # type: ignore[no-untyped-def]
    params = {"company_id": str(shop["company_id"]), "account_id": shop["acc"]["4000"]}
    g = client.get(f"{FIN}/reports/general-ledger", headers=shop["owner"],
                   params={**params, "date_from": "2026-09-15", "date_to": "2026-10-31"}).json()
    assert g["code"] == "4000" and Dec(g["opening"]) == 1000             # the 10 Sept sale, before the range
    running = Dec(g["opening"])
    for line in g["lines"]:
        running += Dec(line["credit"]) - Dec(line["debit"])
        assert Dec(line["balance"]) == running
    assert Dec(g["closing"]) == running
    dates = [x["entry_date"] for x in g["lines"]]
    assert dates == sorted(dates) and all("2026-09-15" <= d <= "2026-10-31" for d in dates)
    paged = client.get(f"{FIN}/reports/general-ledger", headers=shop["owner"], params={
        **params, "date_from": "2026-09-15", "date_to": "2026-10-31", "limit": 1}).json()
    assert len(paged["lines"]) == 1
    bad = client.get(f"{FIN}/reports/general-ledger", headers=shop["owner"], params={
        **params, "date_from": "2026-10-31", "date_to": "2026-09-15"})
    assert bad.status_code == 422
    other = client.get(f"{FIN}/reports/general-ledger", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "account_id": str(uuid4()), "date_from": "2026-01-01",
        "date_to": "2026-12-31"})
    assert other.status_code == 404


def test_a_branch_manager_sees_only_their_own_branch_in_the_books(client, shop) -> None:  # type: ignore[no-untyped-def]
    juja_manager = shop["user"]("jujafinance", "Branch Manager", shop["juja"])           # reports.view, one branch
    t = tb(client, shop, who=juja_manager, as_of="2030-01-01").json()
    all_of_it = tb(client, shop, as_of="2030-01-01").json()
    assert t["balanced"] is False or t["lines"] == [] or t["total_debit"] < all_of_it["total_debit"]
    assert Dec(t["total_debit"]) < Dec(all_of_it["total_debit"])
    ledger = client.get(f"{FIN}/reports/general-ledger", headers=juja_manager, params={
        "company_id": str(shop["company_id"]), "account_id": shop["acc"]["1010"], "date_from": "2026-01-01",
        "date_to": "2030-01-01"}).json()
    assert ledger["lines"] == []                                          # till cash is at the HQ branch
    entries = client.get(f"{FIN}/journal-entries", headers=juja_manager).json()
    first = client.get(f"{FIN}/journal-entries/{entries[0]['id']}", headers=juja_manager).json()
    assert all(x["branch_id"] == str(shop["juja"]) for x in first["lines"])


# --------------------------------------------------------------------------- who may do what
def call(client, shop, role: str, action: str):  # type: ignore[no-untyped-def]
    h, co = shop["people"][role], str(shop["company_id"])
    unique = uuid4().hex[:8]
    if action == "read":
        return client.get(f"{FIN}/accounts", headers=h)
    if action == "chart":
        return client.post(f"{FIN}/accounts", headers=h, json={"company_id": co, "code": f"X{unique}", "name": "x",
                                                                "type": "expense"})
    if action == "write_journal":
        return client.post(f"{FIN}/manual-journals", headers=h, json={
            "company_id": co, "entry_date": "2026-10-13", "description": "x", "lines": [
                {"account_id": shop["acc"]["6000"], "debit": "1"}, {"account_id": shop["acc"]["1020"], "credit": "1"}]})
    if action == "close":
        return client.post(f"{FIN}/periods", headers=h, json={"company_id": co, "day": "2031-01-01"})
    if action == "report":
        return client.get(f"{FIN}/reports/trial-balance", headers=h, params={"company_id": co, "as_of": "2030-01-01"})
    raise AssertionError(action)


ALLOWED = {"read": {"Owner", "Branch Manager", "Finance Manager", "Accountant"},
           "report": {"Owner", "Branch Manager", "Finance Manager", "Accountant"},
           "chart": {"Owner", "Finance Manager", "Accountant"},
           "write_journal": {"Owner", "Finance Manager", "Accountant"},
           "close": {"Owner", "Finance Manager"}}


@pytest.mark.parametrize("action", list(ALLOWED))
@pytest.mark.parametrize("role", ROLES)
def test_each_role_can_do_exactly_what_it_should(client, shop, role: str, action: str) -> None:  # type: ignore[no-untyped-def]
    status = call(client, shop, role, action).status_code
    if role in ALLOWED[action]:
        assert status in (200, 201), f"{role} should be able to {action}, got {status}"
    else:
        assert status == 403, f"{role} should not be able to {action}, got {status}"


def test_the_endpoints_are_off_when_finance_is_disabled(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import make_tenant, sign_in

    make_tenant("No Books")
    owner = sign_in(client, "no-books", "owner@no-books.test").headers
    r = client.get(f"{FIN}/accounts", headers=owner)
    assert r.status_code == 404 and r.json()["error"] == "unit_not_enabled"


# --------------------------------------------------------------------------- the integrity check
def test_a_healthy_set_of_books_has_no_problems(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.checks import run_integrity_checks

    results = run_integrity_checks(shop["tenant_id"])
    assert {r.check for r in results} == {"stock ledger", "books", "files"}
    assert [p for r in results for p in r.problems] == []


def test_the_check_finds_a_company_whose_books_were_tampered_with(shop) -> None:  # type: ignore[no-untyped-def]
    """Even the database owner cannot unbalance an entry normally; this adds a balanced-looking-but-wrong total by
    switching the trigger off, as an attacker with database access might, and the check still notices."""
    from sqlalchemy import text

    from ziira.kernel.checks import run_integrity_checks
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("alter table finance.journal_line disable trigger journal_line_balanced"))
        entry = s.execute(text("select id from finance.journal_entry limit 1")).scalar_one()
        s.execute(text("insert into finance.journal_line (tenant_id, entry_id, company_id, account_id, debit) "
                       "values (:t, :e, :c, :a, 7)"), {"t": str(shop["tenant_id"]), "e": str(entry),
                                                       "c": str(shop["company_id"]), "a": shop["acc"]["6900"]})
    try:
        problems = [p for r in run_integrity_checks(shop["tenant_id"], unit="finance") for p in r.problems]
        assert any("does not balance" in p for p in problems) and any("total debits" in p for p in problems)
    finally:
        with tenant_session(shop["tenant_id"], admin=True) as s:
            s.execute(text("alter table finance.journal_line disable trigger journal_line_immutable"))
            s.execute(text("delete from finance.journal_line where debit = 7 and account_id = :a"),
                      {"a": shop["acc"]["6900"]})
            s.execute(text("alter table finance.journal_line enable trigger journal_line_immutable"))
            s.execute(text("alter table finance.journal_line enable trigger journal_line_balanced"))
    assert [p for r in run_integrity_checks(shop["tenant_id"], unit="finance") for p in r.problems] == []


def test_default_rules_for_a_new_kind_of_document_are_added_but_removed_rules_stay_removed(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from ziira.kernel.db import tenant_session
    from ziira.modules.finance.services.books import ensure_books

    count = "select count(*) from finance.posting_rule where doc_type = :d"
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("delete from finance.posting_rule where doc_type = 'cash_deposit'"))       # as if never seeded
        s.execute(text("delete from finance.posting_rule where doc_type = 'sale' and line_role = 'card'"))
    with system(shop) as s:
        ensure_books(s, shop["company_id"])
        assert s.execute(text(count), {"d": "cash_deposit"}).scalar_one() == 2
        assert s.execute(text(count + " and line_role = 'card'"), {"d": "sale"}).scalar_one() == 0   # a removal stays
        s.execute(text("insert into finance.posting_rule (tenant_id, company_id, doc_type, line_role, account_id, side) "
                       "select tenant_id, company_id, 'sale', 'card', account_id, side from finance.posting_rule "
                       "where doc_type = 'sale' and line_role = 'mobile_money' limit 1"))
