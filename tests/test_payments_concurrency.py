"""Payments under simultaneous requests: duplicate callbacks, and money that cannot be used twice."""

from collections import Counter
from decimal import Decimal as Dec  # noqa: N817

import pytest

from tests.payments_helpers import PAY, c2b, fresh_ref, make_payments_shop, one, post_c2b, record, work
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_payments_shop(client, registry, "Race Pay Co")


def test_the_same_confirmation_arriving_many_times_at_once_is_recorded_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    results = together([lambda: post_c2b(client, shop, c2b(ref, "250.00")) for _ in range(8)])
    assert all(r.status_code == 200 for r in results)                       # Safaricom is always told "accepted"
    assert one(shop, "select count(*) from payments.external_transaction where external_ref = :r", r=ref) == 1


def test_one_transaction_cannot_be_matched_to_two_payments_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    ref = fresh_ref()
    post_c2b(client, shop, c2b(ref, "100.00"))
    payments = [record(client, shop, amount="100.00", external_ref=None).json()["id"] for _ in range(4)]
    txn = client.get(f"{PAY}/transactions", headers=shop["owner"], params={"payment_account_id": shop["till"]}).json()
    txn_id = next(t["id"] for t in txn if t["external_ref"] == ref)
    results = together([lambda p=p: client.post(f"{PAY}/matches", headers=shop["owner"], json={
        "external_transaction_id": txn_id, "payment_id": p, "amount": "100.00"}) for p in payments])
    assert Counter(r.status_code for r in results)[201] == 1, [r.text for r in results]
    assert one(shop, "select coalesce(sum(amount), 0) from payments.match where external_transaction_id = :t "
                     "and status = 'applied'", t=txn_id) == Dec("100.00")
    work(shop)


def test_no_match_ever_uses_more_than_either_side_has(client, shop) -> None:  # type: ignore[no-untyped-def]
    work(shop)
    over_external = one(shop, "select count(*) from (select e.id from payments.external_transaction e join "
                              "payments.match m on m.external_transaction_id = e.id and m.status = 'applied' "
                              "group by e.id, e.amount having sum(m.amount) > e.amount) x")
    over_payment = one(shop, "select count(*) from (select p.id from payments.payment p join payments.match m on "
                             "m.payment_id = p.id and m.status = 'applied' group by p.id, p.amount "
                             "having sum(m.amount) > p.amount) x")
    assert over_external == 0 and over_payment == 0
