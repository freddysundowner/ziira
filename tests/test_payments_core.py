"""Payments: accounts, recording payments, what the provider reports, statements, matching and who may do what."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest

from tests.payments_helpers import (
    PAY,
    SHORTCODE,
    c2b,
    due_now,
    eat_now,
    fresh_ref,
    make_payments_shop,
    one,
    post_c2b,
    record,
    work,
)
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_payments_shop(client, registry, "Pay Co")


# --------------------------------------------------------------------------- accounts
def test_accounts_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co, hq = shop["owner"], str(shop["company_id"]), str(shop["branch_id"])

    def create(**kw):  # type: ignore[no-untyped-def]
        return client.post(f"{PAY}/accounts", headers=owner, json={"company_id": co, "kind": "bank", "name": "x", **kw})

    assert create(kind="cash").status_code == 422                                    # a till belongs to a branch
    assert create(kind="mpesa_till", name="No code").status_code == 422
    assert create(kind="mpesa_till", shortcode="12").status_code == 422
    assert create(kind="mpesa_till", shortcode="123456", name="Bad env", environment="mars").status_code == 422
    assert create(kind="gadget").status_code == 422
    assert create(name="  ").status_code == 422
    assert create(name="x" * 201).status_code == 422
    assert create(branch_id=str(uuid4())).status_code == 422
    assert create(kind="cash", branch_id=hq, name="Second till").status_code == 201
    assert client.get(f"{PAY}/accounts", headers=owner, params={"kind": "bank"}).json()[0]["name"] == "Main bank account"


def test_credentials_are_stored_encrypted_and_never_returned(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    assert "ck-123" not in client.get(f"{PAY}/accounts/{shop['till']}", headers=owner).text
    ciphertext = one(shop, "select secret_ciphertext from kernel.integration_credential limit 1")
    assert b"ck-123" not in bytes(ciphertext) and b"pk-789" not in bytes(ciphertext)
    bad = client.put(f"{PAY}/accounts/{shop['till']}/credentials", headers=owner, json={
        "consumer_key": "a", "consumer_secret": "b", "passkey": ""})
    assert bad.status_code == 422
    assert client.put(f"{PAY}/accounts/{shop['bank']}/credentials", headers=owner, json={
        "consumer_key": "a", "consumer_secret": "b", "passkey": "c"}).status_code == 422       # not an M-Pesa account
    assert client.put(f"{PAY}/accounts/{uuid4()}/credentials", headers=owner, json={
        "consumer_key": "a", "consumer_secret": "b", "passkey": "c"}).status_code == 404
    from ziira.modules.payments.repository import payments_repo
    from ziira.modules.payments.services.accounts import credentials_of

    with system(shop) as s:
        account = payments_repo.get_account(s, shop["till"].__class__(shop["till"]) if False else __import__("uuid").UUID(shop["till"]))
        assert credentials_of(s, account) == {"consumer_key": "ck-123", "consumer_secret": "cs-456", "passkey": "pk-789"}


def test_the_callback_token_works_until_it_is_replaced(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    assert shop["callback_urls"]["c2b_confirmation"].endswith(f"/callbacks/{shop['token']}/c2b/confirmation")
    ref = fresh_ref()
    assert post_c2b(client, shop, c2b(ref, when=eat_now())).json() == {"ResultCode": 0, "ResultDesc": "Accepted"}
    old = shop["token"]
    new = client.post(f"{PAY}/accounts/{shop['till']}/callback-token", headers=owner).json()["token"]
    assert new != old
    assert client.post(f"{PAY}/callbacks/{old}/c2b/confirmation", json=c2b(fresh_ref())).status_code == 404
    assert client.post(f"{PAY}/callbacks/{new}/c2b/confirmation", json=c2b(fresh_ref(), when=eat_now())).status_code == 200
    shop["token"] = new
    assert client.post(f"{PAY}/accounts/{shop['bank']}/callback-token", headers=owner).status_code == 422


# --------------------------------------------------------------------------- recording payments
def test_a_cash_payment_uses_the_branch_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{PAY}/payments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "method": "cash", "amount": "50"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["number"].startswith("PAY-HQ-") and p["payment_account_id"] == shop["cash"] and p["status"] == "posted"
    assert Dec(p["amount"]) == 50


def test_payment_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co, hq = shop["owner"], str(shop["company_id"]), str(shop["branch_id"])

    def pay(**kw):  # type: ignore[no-untyped-def]
        return client.post(f"{PAY}/payments", headers=owner, json={
            "company_id": co, "branch_id": hq, "method": "mpesa", "amount": "10", "payment_account_id": shop["till"],
            **kw})

    assert pay(amount="0").status_code == 422 and pay(amount="-5").status_code == 422
    assert pay(amount="1.005").status_code == 422 and pay(amount="1e20").status_code == 422
    assert pay(method="bitcoin").status_code == 422
    assert pay(payment_account_id=None).status_code == 422                         # which account?
    assert pay(payment_account_id=shop["bank"]).status_code == 422                 # M-Pesa money through a bank account
    assert pay(payment_account_id=str(uuid4())).status_code == 422
    assert pay(party_type="martian").status_code == 422
    assert pay(phone="12345").status_code == 422
    assert pay(external_ref="x" * 61).status_code == 422
    assert pay(branch_id=str(uuid4())).status_code == 422
    assert pay(direction="sideways").status_code == 422


def test_the_same_mpesa_code_for_the_same_amount_is_not_recorded_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    assert record(client, shop, external_ref=ref.lower(), amount="75").status_code == 201
    r = record(client, shop, external_ref=ref, amount="75")
    assert r.status_code == 409 and "already been recorded" in r.json()["message"]
    assert record(client, shop, external_ref=ref, amount="25").status_code == 201      # a part payment is different


def test_payments_can_be_listed_read_and_reversed(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    p = record(client, shop, external_ref=fresh_ref(), amount="33").json()
    assert client.get(f"{PAY}/payments/{p['id']}", headers=owner).json()["number"] == p["number"]
    assert p["id"] in {x["id"] for x in client.get(f"{PAY}/payments", headers=owner, params={"method": "mpesa"}).json()}
    assert client.get(f"{PAY}/payments/{uuid4()}", headers=owner).status_code == 404
    assert client.post(f"{PAY}/payments/{p['id']}/reverse", headers=owner, json={"reason": " "}).status_code == 422
    r = client.post(f"{PAY}/payments/{p['id']}/reverse", headers=owner, json={"reason": "Typed twice"})
    assert r.json()["status"] == "reversed"
    assert client.post(f"{PAY}/payments/{p['id']}/reverse", headers=owner, json={"reason": "again"}).status_code == 409


# --------------------------------------------------------------------------- what the provider reports
def test_a_c2b_confirmation_is_recorded_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    payload = c2b(ref, amount="250.00", bill="INV-77", when=eat_now())
    for _ in range(3):                                                                # Safaricom retries
        assert post_c2b(client, shop, payload).status_code == 200
    rows = client.get(f"{PAY}/transactions", headers=shop["owner"], params={"payment_account_id": shop["till"]}).json()
    mine = [r for r in rows if r["external_ref"] == ref]
    assert len(mine) == 1 and Dec(mine[0]["amount"]) == 250 and mine[0]["bill_ref"] == "INV-77"
    assert mine[0]["counterparty_name"] == "Jane Wanjiru" and mine[0]["counterparty_phone_masked"] == "2547****678"
    raw = one(shop, "select raw::text from payments.external_transaction where external_ref = :r", r=ref)
    assert "254712345678" not in raw and "Jane" not in raw                            # no personal data kept in the clear


def test_the_same_reference_with_another_amount_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    post_c2b(client, shop, c2b(ref, amount="100.00", when=eat_now()))
    post_c2b(client, shop, c2b(ref, amount="150.00", when=eat_now()))
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "transaction_conflict"}).json()
    assert any(ref in i["message"] and i["severity"] == "high" for i in items)


def test_bad_callbacks_are_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"{PAY}/callbacks/{shop['token']}/c2b/confirmation"
    assert client.post(url, json={"nonsense": 1}).status_code == 422
    assert client.post(url, json=c2b("", when=eat_now())).status_code == 422
    assert client.post(url, json=c2b(fresh_ref(), amount="-5", when=eat_now())).status_code == 422
    assert client.post(f"{PAY}/callbacks/not-a-token/c2b/confirmation", json=c2b(fresh_ref())).status_code == 404
    assert client.post(f"{PAY}/callbacks/{uuid4().hex}.guess/c2b/confirmation", json=c2b(fresh_ref())).status_code == 404
    assert client.post(f"{PAY}/callbacks/{shop['token']}x/c2b/confirmation", json=c2b(fresh_ref())).status_code == 404
    assert client.post(url, content=b"[1,2", headers={"Content-Type": "application/json"}).status_code == 422


def test_a_confirmation_for_another_shortcode_is_flagged_not_recorded(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    assert post_c2b(client, shop, c2b(ref, shortcode="999999", when=eat_now())).status_code == 200
    assert one(shop, "select count(*) from payments.external_transaction where external_ref = :r", r=ref) == 0
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "callback_misrouted"}).json()
    assert any(SHORTCODE in i["message"] for i in items)


def test_the_validation_callback_accepts_everything(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{PAY}/callbacks/{shop['token']}/c2b/validation", json=c2b(fresh_ref()))
    assert r.status_code == 200 and r.json()["ResultCode"] == 0


# --------------------------------------------------------------------------- statements
MPESA_CSV = """Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance
{a},2026-10-13 10:15:30,Funds received from 2547****678 - JANE WANJIRU,Completed,"1,160.00",,5000.00
{b},2026-10-13 10:20:00,Business Payment to 254722000000,Completed,,300.00,4700.00
{c},2026-10-13 10:25:00,Funds received from 2547****111 - JOHN,Failed,500.00,,4700.00
"""


def test_an_mpesa_statement_is_imported_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    a, b, c = fresh_ref(), fresh_ref(), fresh_ref()
    body = {"format": "mpesa", "content": MPESA_CSV.format(a=a, b=b, c=c)}
    r = client.post(f"{PAY}/accounts/{shop['till']}/statements", headers=shop["owner"], json=body)
    assert r.status_code == 200 and (r.json()["created"], r.json()["duplicates"]) == (2, 0)
    again = client.post(f"{PAY}/accounts/{shop['till']}/statements", headers=shop["owner"], json=body).json()
    assert (again["created"], again["duplicates"]) == (0, 2)
    rows = {x["external_ref"]: x for x in client.get(f"{PAY}/transactions", headers=shop["owner"],
                                                      params={"payment_account_id": shop["till"]}).json()}
    assert rows[a]["direction"] == "in" and Dec(rows[a]["amount"]) == 1160 and rows[a]["source"] == "mpesa_statement"
    assert rows[b]["direction"] == "out" and c not in rows


def test_a_bank_statement_and_bad_uploads(client, shop) -> None:  # type: ignore[no-untyped-def]
    csv_text = "Date,Description,Reference,Debit,Credit\n13/10/2026,SETTLEMENT,ST1,,58000.00\n14/10/2026,FEE,,250.00,\n"
    r = client.post(f"{PAY}/accounts/{shop['bank']}/statements", headers=shop["owner"],
                    json={"format": "bank", "content": csv_text})
    assert r.json()["created"] == 2
    assert client.post(f"{PAY}/accounts/{shop['bank']}/statements", headers=shop["owner"],
                       json={"format": "bank", "content": "no header here"}).status_code == 422
    assert client.post(f"{PAY}/accounts/{shop['bank']}/statements", headers=shop["owner"],
                       json={"format": "mpesa", "content": csv_text}).status_code == 422
    assert client.post(f"{PAY}/accounts/{shop['bank']}/statements", headers=shop["owner"],
                       json={"format": "pdf", "content": "x"}).status_code == 422
    assert client.post(f"{PAY}/accounts/{uuid4()}/statements", headers=shop["owner"],
                       json={"format": "bank", "content": csv_text}).status_code == 404


# --------------------------------------------------------------------------- matching
def tx_status(client, shop, ref: str) -> str:  # type: ignore[no-untyped-def]
    rows = client.get(f"{PAY}/transactions", headers=shop["owner"], params={"payment_account_id": shop["till"]}).json()
    return next(r["match_status"] for r in rows if r["external_ref"] == ref)


def test_a_payment_and_its_confirmation_match_by_reference_in_either_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    first, second = fresh_ref(), fresh_ref()
    record(client, shop, external_ref=first, amount="116")                     # the cashier typed the code first...
    post_c2b(client, shop, c2b(first, amount="116.00", when=eat_now()))        # ...then the provider's record arrived
    post_c2b(client, shop, c2b(second, amount="200.00", when=eat_now()))       # here it arrived first...
    record(client, shop, external_ref=second, amount="200")
    due_now(shop)
    assert work(shop) >= 1
    assert tx_status(client, shop, first) == "matched" and tx_status(client, shop, second) == "matched"
    matches = client.get(f"{PAY}/matches", headers=shop["owner"], params={"status": "applied"}).json()
    assert {m["stage"] for m in matches} == {"exact_reference"}


def test_matching_by_the_paybill_account_number(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = record(client, shop, amount="500", external_ref=None).json()
    post_c2b(client, shop, c2b(fresh_ref(), amount="500.00", bill=p["number"], when=eat_now()))
    ref = one(shop, "select external_ref from payments.external_transaction where bill_ref = :b", b=p["number"])
    due_now(shop)
    work(shop)
    assert tx_status(client, shop, ref) == "matched"
    stage = one(shop, "select stage from payments.match where payment_id = :p", p=p["id"])
    assert stage == "account_number"


def test_a_confident_rule_match_is_applied_a_weak_one_is_only_proposed(client, shop) -> None:  # type: ignore[no-untyped-def]
    strong_ref, weak_ref = fresh_ref(), fresh_ref()
    record(client, shop, amount="321", phone="0712345678")                       # no reference, but the phone is known
    post_c2b(client, shop, c2b(strong_ref, amount="321.00", when=eat_now()))      # the payer's phone hash is the same
    due_now(shop)
    work(shop)
    assert tx_status(client, shop, strong_ref) == "matched"
    assert one(shop, "select rule_code from payments.match m join payments.external_transaction t on t.id = "
                     "m.external_transaction_id where t.external_ref = :r", r=strong_ref) == "amount_account_phone_time"
    record(client, shop, amount="654")                                           # no phone on the payment
    post_c2b(client, shop, c2b(weak_ref, amount="654.00", when=eat_now()))
    due_now(shop)
    work(shop)
    assert tx_status(client, shop, weak_ref) == "proposed"                       # a person must confirm it
    proposal = client.get(f"{PAY}/matches", headers=shop["owner"], params={"status": "proposed"}).json()[0]
    assert proposal["stage"] == "rule" and Dec(proposal["confidence"]) == Dec("0.7")
    r = client.post(f"{PAY}/matches", headers=shop["owner"], json={
        "external_transaction_id": proposal["external_transaction_id"], "payment_id": proposal["payment_id"]})
    assert r.status_code == 201 and r.json()["stage"] == "manual" and r.json()["status"] == "applied"
    assert tx_status(client, shop, weak_ref) == "matched"


def test_manual_matching_and_undoing_keep_the_history(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, ref = shop["owner"], fresh_ref()
    post_c2b(client, shop, c2b(ref, amount="900.00", when=eat_now()))
    p = record(client, shop, amount="900").json()
    txn = next(r for r in client.get(f"{PAY}/transactions", headers=owner,
                                     params={"payment_account_id": shop["till"]}).json() if r["external_ref"] == ref)
    body = {"external_transaction_id": txn["id"], "payment_id": p["id"]}
    assert client.post(f"{PAY}/matches", headers=owner, json={**body, "amount": "1000"}).status_code == 422   # too much
    m = client.post(f"{PAY}/matches", headers=owner, json=body)
    assert m.status_code == 201 and Dec(m.json()["amount"]) == 900
    assert client.post(f"{PAY}/matches", headers=owner, json=body).status_code == 409                       # already
    assert tx_status(client, shop, ref) == "matched"
    assert client.post(f"{PAY}/payments/{p['id']}/reverse", headers=owner, json={"reason": "x"}).status_code == 422
    assert client.post(f"{PAY}/matches/{m.json()['id']}/undo", headers=owner, json={"reason": " "}).status_code == 422
    undone = client.post(f"{PAY}/matches/{m.json()['id']}/undo", headers=owner, json={"reason": "Wrong customer"})
    assert undone.json()["status"] == "undone" and tx_status(client, shop, ref) == "unmatched"
    assert client.post(f"{PAY}/matches/{m.json()['id']}/undo", headers=owner, json={"reason": "again"}).status_code == 409
    history = client.get(f"{PAY}/matches", headers=owner, params={"payment_id": p["id"]}).json()
    assert [x["status"] for x in history] == ["undone"]                                                      # kept


def test_part_payments_and_one_payment_for_several_documents(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, ref = shop["owner"], fresh_ref()
    post_c2b(client, shop, c2b(ref, amount="300.00", when=eat_now()))
    txn = next(r for r in client.get(f"{PAY}/transactions", headers=owner,
                                     params={"payment_account_id": shop["till"]}).json() if r["external_ref"] == ref)
    parts = [record(client, shop, amount="100").json() for _ in range(3)]
    for part in parts:                                                         # one transaction, three payments
        r = client.post(f"{PAY}/matches", headers=owner, json={"external_transaction_id": txn["id"],
                                                               "payment_id": part["id"]})
        assert r.status_code == 201 and Dec(r.json()["amount"]) == 100
    assert tx_status(client, shop, ref) == "matched"
    extra = record(client, shop, amount="50").json()
    assert client.post(f"{PAY}/matches", headers=owner, json={"external_transaction_id": txn["id"],
                                                              "payment_id": extra["id"]}).status_code == 422


def test_ignoring_a_transaction(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, ref = shop["owner"], fresh_ref()
    post_c2b(client, shop, c2b(ref, amount="12.00", when=eat_now()))
    txn = next(r for r in client.get(f"{PAY}/transactions", headers=owner,
                                     params={"payment_account_id": shop["till"]}).json() if r["external_ref"] == ref)
    assert client.post(f"{PAY}/transactions/{txn['id']}/ignore", headers=owner, json={"reason": "Owner's own"}
                       ).json()["match_status"] == "ignored"
    p = record(client, shop, amount="12").json()
    assert client.post(f"{PAY}/matches", headers=owner, json={"external_transaction_id": txn["id"],
                                                              "payment_id": p["id"]}).status_code == 422
    assert client.post(f"{PAY}/transactions/{txn['id']}/unignore", headers=owner, json={"reason": "No, it is ours"}
                       ).json()["match_status"] == "unmatched"


def test_what_nobody_claims_becomes_an_exception(client, shop) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from ziira.modules.payments.services import matching

    ref = fresh_ref()
    post_c2b(client, shop, c2b(ref, amount="777.00", when=eat_now()))
    with system(shop) as s:
        assert matching.run_matching(s).flagged == 0                                 # too recent to worry about
    with system(shop) as s:
        run = matching.run_matching(s, now=datetime.now(UTC) + timedelta(hours=3))
    assert run.flagged >= 1
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "unmatched_transaction"}).json()
    assert any(ref in i["message"] and i["amount"] is not None for i in items)
    with system(shop) as s:                                                           # raised once, not every run
        matching.run_matching(s, now=datetime.now(UTC) + timedelta(hours=4))
    again = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "unmatched_transaction"}).json()
    assert len([i for i in again if ref in i["message"]]) == 1
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'payment.unmatched'") >= 1


# --------------------------------------------------------------------------- who may do what
def test_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, hq = str(shop["company_id"]), str(shop["branch_id"])
    pay_body = {"company_id": co, "branch_id": hq, "method": "cash", "amount": "5"}
    assert client.get(f"{PAY}/accounts", headers=shop["cashier"]).status_code == 200            # may view
    assert client.get(f"{PAY}/payments", headers=shop["storekeeper"]).status_code == 403        # no payments permission
    assert client.post(f"{PAY}/payments", headers=shop["cashier"], json=pay_body).status_code == 403
    assert client.post(f"{PAY}/accounts", headers=shop["manager"], json={
        "company_id": co, "kind": "bank", "name": "x"}).status_code == 403                      # not payments.manage
    assert client.post(f"{PAY}/payments", headers=shop["manager"], json=pay_body).status_code == 201
    assert client.post(f"{PAY}/matching/run", headers=shop["cashier"]).status_code == 403
    assert client.post(f"{PAY}/matching/run", headers=shop["manager"]).status_code == 200
    juja = shop["user"]("jujapay", "Branch Manager", shop["juja"])
    assert client.post(f"{PAY}/payments", headers=juja, json=pay_body).status_code == 403       # another branch
    assert client.get(f"{PAY}/payments", headers=juja).json() == []                              # and cannot see HQ's
    assert client.get(f"{PAY}/accounts/{shop['cash']}", headers=juja).status_code == 404
    assert client.get(f"{PAY}/accounts/{shop['cash']}").status_code in (401, 403)
