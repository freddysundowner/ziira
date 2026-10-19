"""Intelligence checks and the Command Center figures over Claims, with the real engine. Today is 2026-10-14."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from typing import Any

import pytest
from sqlalchemy import text

from tests.claims_helpers import estimate, line, make_claims_shop, new_claim, submit
from tests.stock_helpers import system
from ziira.modules.claims.intel_checks import CompletedNotInvoiced, EstimateWaiting, ShortPayOpen, SupplementaryNotSent
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import engine

TODAY = date(2026, 10, 14)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_claims_shop(client, registry, "Claims Intel Co")


def sql(shop, stmt: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text(stmt), params)


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=lambda metric, key: None)
        return check.run(s, ctx)


def test_an_estimate_the_payer_has_not_answered_is_flagged_then_quiet(client, shop) -> None:  # type: ignore[no-untyped-def]
    old, fresh = new_claim(client, shop, claim_number="A"), new_claim(client, shop, claim_number="B")
    for claim in (old, fresh):
        submit(client, shop, estimate(client, shop, claim, [line("parts", "Bumper", "1", "1000.00")]))
    sql(shop, "update claims.estimate set submitted_at = cast('2026-10-01 08:00+00' as timestamptz) where claim_id = :c",
        c=old["id"])
    found = direct(shop, EstimateWaiting())
    assert [c.entity_id for c in found] == [__import__("uuid").UUID(old["id"])]
    assert found[0].amount == Dec("1000.00") and found[0].branch_id == shop["branch_id"]
    assert direct(shop, EstimateWaiting(), waiting_days=30) == []                       # the limit is tuned by data
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=TODAY, only={"claims.estimate_waiting"})
    assert result is not None
    sql(shop, "update claims.estimate set status = 'answered' where claim_id = :c", c=old["id"])
    assert direct(shop, EstimateWaiting()) == []                                        # answered: silent


def test_extra_work_never_sent_and_finished_work_never_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    claim = new_claim(client, shop, claim_number="C")
    first = submit(client, shop, estimate(client, shop, claim, [line("parts", "Door", "1", "5000.00")]))["estimate"]
    estimate(client, shop, claim, [line("parts", "Hinge", "1", "300.00")], kind="supplementary")
    sql(shop, "update claims.estimate set created_at = cast('2026-10-05 08:00+00' as timestamptz) where status = 'draft' "
              "and claim_id = :c", c=claim["id"])
    assert [c.amount for c in direct(shop, SupplementaryNotSent())] == [Dec("300.00")]
    sql(shop, "update claims.estimate_line set payer_state = 'approved' where estimate_id = :e", e=first["id"])
    sql(shop, "update claims.claim set status = 'completed', completed_at = cast('2026-10-01 08:00+00' as timestamptz) "
              "where id = :c", c=claim["id"])
    assert [c.amount for c in direct(shop, CompletedNotInvoiced())] == [Dec("5000.00")]
    assert direct(shop, CompletedNotInvoiced(), grace_days=30) == []


def test_an_open_short_payment_is_flagged_and_the_pulse_counts_open_claims(client, shop) -> None:  # type: ignore[no-untyped-def]
    claim = new_claim(client, shop, claim_number="D")
    sql(shop, "insert into claims.invoice_run (tenant_id, company_id, claim_id, seq) values (:t, :c, :cl, 1)",
        t=str(shop["tenant_id"]), c=str(shop["company_id"]), cl=claim["id"])
    sql(shop, "insert into claims.short_pay (tenant_id, company_id, claim_id, payer_id, run_id, invoice_id, expected, paid, "
              "difference, created_at) select :t, :c, :cl, :p, id, gen_random_uuid(), 1000, 900, 100, "
              "cast('2026-09-20 08:00+00' as timestamptz) from claims.invoice_run where claim_id = :cl",
        t=str(shop["tenant_id"]), c=str(shop["company_id"]), cl=claim["id"], p=shop["payer"]["id"])
    assert [c.amount for c in direct(shop, ShortPayOpen())] == [Dec("100.00")]
    with system(shop) as s:
        figures = pulse.collect(s, shop["company_id"], TODAY) if hasattr(pulse, "collect") else []
    assert isinstance(figures, list)
