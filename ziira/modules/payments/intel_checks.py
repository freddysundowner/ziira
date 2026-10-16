"""Intelligence checks over Payments data: money that matches nothing, provider transactions nobody matched, closes
with variances, missing settlements, duplicates, failing payment prompts, reversals after matching, and manual payments
with no provider evidence. Every check is read-only, bounded by a look-back window, and country-neutral: accounts,
providers and currency come from the business's own records."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import (
    BaselineMetric,
    Candidate,
    CheckContext,
    IntelCheck,
    Record,
    Sample,
    fingerprint,
    is_unusual,
)
from ziira.sdk import Session

# Allocations that only move money between the business's own accounts: they are not takings from a customer.
INTERNAL = "('settlement', 'cash_deposit')"
MIN_BASELINE_DAYS = 14


def _currency(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": company_id}).scalar_one())


def _money(currency: str, amount: Decimal) -> str:
    return f"{currency} {amount:,.2f}"


def _common_branch(branches: list[UUID | None]) -> UUID | None:
    """The branch all records share, or None when they differ (or have none)."""
    unique = set(branches)
    return unique.pop() if len(unique) == 1 else None


def _since(ctx: CheckContext) -> date:
    return ctx.today - timedelta(days=int(ctx.number("days")))


class UnlinkedReceipts(IntelCheck):
    """Money received that no sale, invoice or customer explains, after a waiting time."""

    code = "payments.unlinked_receipts"

    value_kind = "count"
    title = "Money received that matches nothing"
    area = "cash_sales"
    description = "Money was received but is not linked to any sale, invoice or customer."
    default_severity = "medium"
    params: dict[str, Any] = {"hours": 24, "days": 30}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per day and payment account, with the amount and the payments behind it."""
        rows = session.execute(text("""
            select p.id, p.number, p.branch_id, p.amount, p.business_date, a.id as account_id, a.name as account_name
              from payments.payment p join payments.payment_account a on a.id = p.payment_account_id
             where p.company_id = :c and p.direction = 'in' and p.status = 'posted' and p.party_id is null
               and not exists (select 1 from payments.payment_allocation x where x.payment_id = p.id)
               and p.business_date between :d1 and :d2
               and p.created_at < now() - make_interval(hours => :h)
             order by p.business_date, p.number"""),
            {"c": ctx.company_id, "d1": _since(ctx), "d2": ctx.today, "h": int(ctx.number("hours"))}).all()
        currency = _currency(session, ctx.company_id)
        groups: dict[tuple[UUID, date], list[Any]] = defaultdict(list)
        for r in rows:
            groups[(r.account_id, r.business_date)].append(r)
        found = []
        for (account_id, day), items in groups.items():
            total = sum((r.amount for r in items), Decimal(0))
            n = len(items)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, account_id, day), severity="medium",
                summary=(f"{n} payment{'s' if n != 1 else ''} totalling {_money(currency, total)} received on {day} "
                         f"through {items[0].account_name} {'are' if n != 1 else 'is'} not linked to any sale, "
                         f"invoice or customer."),
                recommended_action="Find out what these payments were for and link them.",
                company_id=ctx.company_id, branch_id=_common_branch([r.branch_id for r in items]),
                entity_type="payments.payment_account", entity_id=account_id, period_start=day, period_end=day,
                value=Decimal(n), amount=total,
                records=tuple(Record("payments.payment", r.id, f"Payment {r.number}") for r in items[:10]),
                figures={"payments": str(n), "total": str(total), "account": items[0].account_name}))
        return found


class UnmatchedTransactions(IntelCheck):
    """Money the provider reported that was never matched to a payment recorded in the business."""

    code = "payments.unmatched_transactions"

    value_kind = "count"
    title = "Provider transactions nobody matched"
    area = "cash_sales"
    description = "The mobile money provider or bank reported money in that no recorded payment accounts for."
    default_severity = "medium"
    params: dict[str, Any] = {"unmatched_days": 2, "days": 30}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per account and day of transactions still unmatched after the waiting time."""
        rows = session.execute(text("""
            select t.id, t.external_ref, t.amount, (t.txn_time at time zone :tz)::date as day,
                   a.id as account_id, a.name as account_name, a.branch_id
              from payments.external_transaction t join payments.payment_account a on a.id = t.payment_account_id
             where a.company_id = :c and t.direction = 'in' and t.match_status in ('unmatched', 'proposed')
               and t.txn_time >= (cast(:d1 as date)::timestamp at time zone :tz)
               and t.txn_time < now() - make_interval(days => :u)
             order by t.txn_time"""),
            {"c": ctx.company_id, "tz": ctx.timezone, "d1": _since(ctx), "u": int(ctx.number("unmatched_days"))}).all()
        currency = _currency(session, ctx.company_id)
        groups: dict[tuple[UUID, date], list[Any]] = defaultdict(list)
        for r in rows:
            groups[(r.account_id, r.day)].append(r)
        found = []
        for (account_id, day), items in groups.items():
            total = sum((r.amount for r in items), Decimal(0))
            n = len(items)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, account_id, day), severity="medium",
                summary=(f"{n} transaction{'s' if n != 1 else ''} totalling {_money(currency, total)} reported on "
                         f"{day} by {items[0].account_name} {'have' if n != 1 else 'has'} not been matched to any "
                         f"recorded payment."),
                recommended_action="Match each transaction to a sale or payment, or record what it was for.",
                company_id=ctx.company_id, branch_id=items[0].branch_id, entity_type="payments.payment_account",
                entity_id=account_id, period_start=day, period_end=day, value=Decimal(n), amount=total,
                records=tuple(Record("payments.external_transaction", r.id, f"Transaction {r.external_ref}")
                              for r in items[:10]),
                figures={"transactions": str(n), "total": str(total), "account": items[0].account_name}))
        return found


class CloseVariance(IntelCheck):
    """A branch's daily close that ended with money missing or extra beyond a limit."""

    code = "payments.close_variance"

    value_kind = "money"
    title = "Daily close with a variance"
    area = "cash_sales"
    description = "A branch closed its day with more or less money than the records say it should have."
    default_severity = "medium"
    params: dict[str, Any] = {"variance_limit": "100.00", "days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per close whose variance (either way) is beyond the limit; five times the limit is high."""
        limit = ctx.number("variance_limit")
        rows = session.execute(text("""
            select c.id, c.branch_id, c.business_date, c.variance, c.explanation, b.name as branch_name
              from payments.daily_close c join kernel.branch b on b.id = c.branch_id
             where c.company_id = :c and c.status <> 'open' and abs(c.variance) > :limit
               and c.business_date between :d1 and :d2
             order by c.business_date"""),
            {"c": ctx.company_id, "limit": limit, "d1": _since(ctx), "d2": ctx.today}).all()
        currency = _currency(session, ctx.company_id)
        found = []
        for r in rows:
            size = abs(r.variance)
            direction = "short" if r.variance > 0 else "over"
            note = f" The explanation given: {r.explanation}" if r.explanation else " No explanation was given."
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if limit > 0 and size >= 5 * limit else "medium",
                summary=(f"The close for {r.branch_name} on {r.business_date} ended {_money(currency, size)} "
                         f"{direction} (the limit is {_money(currency, limit)}).{note}"),
                recommended_action="Check the day's takings and confirm the explanation.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="payments.daily_close", entity_id=r.id,
                period_start=r.business_date, period_end=r.business_date, value=size, expected_value=limit,
                amount=size, records=(Record("payments.daily_close", r.id, f"Close {r.business_date}"),),
                figures={"variance": str(r.variance), "limit": str(limit)}))
        return found


class MissingClose(IntelCheck):
    """A branch took money on a day and never closed that day."""

    code = "payments.missing_close"

    value_kind = "count"
    title = "Day with takings but no close"
    area = "controls"
    description = "A branch received money on a day but its daily close was never submitted."
    default_severity = "medium"
    params: dict[str, Any] = {"grace_days": 1, "days": 7}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per branch and day with takings and no submitted or locked close, once past the grace days."""
        newest = ctx.today - timedelta(days=int(ctx.number("grace_days")))
        rows = session.execute(text(f"""
            select p.branch_id, p.business_date, count(*) as n, sum(p.amount) as total, b.name as branch_name
              from payments.payment p join kernel.branch b on b.id = p.branch_id
             where p.company_id = :c and p.direction = 'in' and p.status = 'posted'
               and p.business_date between :d1 and :d2
               and not exists (select 1 from payments.payment_allocation x
                                where x.payment_id = p.id and x.doc_type in {INTERNAL})
               and not exists (select 1 from payments.daily_close c
                                where c.branch_id = p.branch_id and c.business_date = p.business_date
                                  and c.status in ('submitted', 'locked'))
             group by p.branch_id, p.business_date, b.name order by p.business_date"""),
            {"c": ctx.company_id, "d1": _since(ctx), "d2": newest}).all()
        currency = _currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.branch_id, r.business_date), severity="medium",
            summary=(f"{r.branch_name} received {_money(currency, r.total)} in {r.n} payment{'s' if r.n != 1 else ''}"
                     f" on {r.business_date}, but its daily close was not made."),
            recommended_action="Ask the branch manager to submit the close for that day.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="kernel.branch", entity_id=r.branch_id,
            period_start=r.business_date, period_end=r.business_date, value=Decimal(r.n), amount=r.total,
            figures={"payments": str(r.n), "total": str(r.total)}) for r in rows]


class SettlementMismatch(IntelCheck):
    """Mobile money takings that never reached the bank, or a bank settlement that differs from what was received."""

    code = "payments.settlement_mismatch"

    value_kind = "money"
    title = "Settlement missing or different"
    area = "cash_sales"
    description = "What a mobile money account received does not agree with what was settled to the bank."
    default_severity = "medium"
    params: dict[str, Any] = {"grace_days": 3, "tolerance_percent": "2.0", "days": 30}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Per mobile money account over the window: transactions received (up to the grace days ago) against the
        settlements recorded. Different by more than the tolerance either way is reported."""
        tol = ctx.number("tolerance_percent") / 100
        newest = ctx.today - timedelta(days=int(ctx.number("grace_days")))
        accounts = session.execute(text("""
            select id, name, branch_id from payments.payment_account
             where company_id = :c and kind = 'mobile_money' and is_active"""), {"c": ctx.company_id}).all()
        currency = _currency(session, ctx.company_id)
        found = []
        for a in accounts:
            received = session.execute(text("""
                select coalesce(sum(amount), 0) from payments.external_transaction
                 where payment_account_id = :a and direction = 'in'
                   and (txn_time at time zone :tz)::date between :d1 and :d2"""),
                {"a": a.id, "tz": ctx.timezone, "d1": _since(ctx), "d2": newest}).scalar_one()
            settled_rows = session.execute(text("""
                select p.id, p.number, p.amount from payments.payment p
                 where p.payment_account_id = :a and p.direction = 'out' and p.status = 'posted'
                   and p.business_date between :d1 and :d2
                   and exists (select 1 from payments.payment_allocation x
                                where x.payment_id = p.id and x.doc_type = 'settlement')"""),
                {"a": a.id, "d1": _since(ctx), "d2": ctx.today}).all()
            settled = sum((r.amount for r in settled_rows), Decimal(0))
            if received == 0 and settled == 0:
                continue
            if received - settled > received * tol:
                what = "short"
                summary = (f"{a.name} received {_money(currency, received)} between {_since(ctx)} and {newest}, but "
                           f"only {_money(currency, settled)} was settled to the bank: "
                           f"{_money(currency, received - settled)} is not accounted for.")
            elif settled > received * (1 + tol):
                what = "more"
                summary = (f"{_money(currency, settled)} was settled to the bank from {a.name}, more than the "
                           f"{_money(currency, received)} it received between {_since(ctx)} and {newest}.")
            else:
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, a.id, what), severity="medium", summary=summary,
                recommended_action="Compare the provider's settlement report with the bank statement.",
                company_id=ctx.company_id, branch_id=a.branch_id, entity_type="payments.payment_account",
                entity_id=a.id, period_start=_since(ctx), period_end=newest, value=settled, expected_value=received,
                amount=abs(received - settled),
                records=tuple(Record("payments.payment", r.id, f"Settlement {r.number}") for r in settled_rows[:10]),
                figures={"received": str(received), "settled": str(settled), "account": a.name}))
        return found


class PossibleDuplicatePayments(IntelCheck):
    """The same payer paying the same amount twice in a few minutes."""

    code = "payments.possible_duplicates"
    title = "Possible duplicate payments"
    area = "controls"
    description = "Two payments of the same amount from the same payer were recorded within minutes of each other."
    default_severity = "medium"
    params: dict[str, Any] = {"window_minutes": 10, "days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per pair: same account, same amount and same payer (phone fingerprint, or the party)."""
        rows = session.execute(text(f"""
            select p1.id as id1, p1.number as n1, p2.id as id2, p2.number as n2, p1.amount, p1.branch_id,
                   p1.business_date, a.name as account_name
              from payments.payment p1
              join payments.payment p2 on p2.id > p1.id and p2.payment_account_id = p1.payment_account_id
                   and p2.amount = p1.amount and p2.direction = 'in' and p2.status = 'posted'
                   and coalesce(p2.phone_hash, p2.party_id::text) = coalesce(p1.phone_hash, p1.party_id::text)
                   and abs(extract(epoch from p2.created_at - p1.created_at)) <= :w * 60
              join payments.payment_account a on a.id = p1.payment_account_id
             where p1.company_id = :c and p1.direction = 'in' and p1.status = 'posted' and p1.method <> 'cash'
               and coalesce(p1.phone_hash, p1.party_id::text) is not null
               and p1.business_date between :d1 and :d2
               and not exists (select 1 from payments.payment_allocation x
                                where x.payment_id in (p1.id, p2.id) and x.doc_type in {INTERNAL})
             order by p1.business_date, p1.number"""),
            {"c": ctx.company_id, "w": int(ctx.number("window_minutes")), "d1": _since(ctx), "d2": ctx.today}).all()
        currency = _currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id1, r.id2), severity="medium",
            summary=(f"Payments {r.n1} and {r.n2}, both {_money(currency, r.amount)} through {r.account_name} from "
                     f"the same payer, were recorded within {int(ctx.number('window_minutes'))} minutes of each "
                     f"other on {r.business_date}."),
            recommended_action="Check whether the customer paid twice and refund or reverse one if so.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="payments.payment", entity_id=r.id2,
            period_start=r.business_date, period_end=r.business_date, amount=r.amount,
            records=(Record("payments.payment", r.id1, f"Payment {r.n1}"),
                     Record("payments.payment", r.id2, f"Payment {r.n2}")),
            figures={"amount": str(r.amount), "account": r.account_name}) for r in rows]


def _prompt_stats(session: Session, company_id: UUID, tz: str, d1: date, d2: date) -> list[Any]:
    return list(session.execute(text("""
        select i.payment_account_id as account_id, a.name as account_name, a.branch_id,
               (i.created_at at time zone :tz)::date as day, count(*) as total,
               count(*) filter (where i.status in ('failed', 'timeout')) as failed
          from payments.payment_intent i join payments.payment_account a on a.id = i.payment_account_id
         where a.company_id = :c and i.kind = 'stk_push' and i.status <> 'pending'
           and (i.created_at at time zone :tz)::date between :d1 and :d2
         group by 1, 2, 3, 4"""), {"c": company_id, "tz": tz, "d1": d1, "d2": d2}).all())


class FailingPaymentPrompts(IntelCheck):
    """Payment requests sent to customers' phones failing or timing out far more than usual on a day."""

    code = "payments.failing_prompts"

    value_kind = "percent"
    title = "Payment prompts failing"
    area = "cash_sales"
    description = "Many payment requests sent to customers' phones failed or timed out on the same day."
    default_severity = "medium"
    params: dict[str, Any] = {"min_attempts": 5, "failure_percent": "50.0", "days": 3}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per account and day with enough attempts and a failure rate over the limit (and, when the
        business has a history for the account, also unusual against it)."""
        found = []
        for r in _prompt_stats(session, ctx.company_id, ctx.timezone, _since(ctx), ctx.today):
            if r.total < int(ctx.number("min_attempts")):
                continue
            rate = Decimal(r.failed) * 100 / Decimal(r.total)
            if rate < ctx.number("failure_percent"):
                continue
            baseline = ctx.baseline(PromptFailureRate.code, str(r.account_id))
            if baseline is not None and baseline.sample_size >= MIN_BASELINE_DAYS and not is_unusual(rate, baseline):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.account_id, r.day), severity="medium",
                summary=(f"{r.failed} of {r.total} payment requests sent through {r.account_name} on {r.day} failed "
                         f"or timed out ({rate:.0f}%)."),
                recommended_action="Check the account's credentials and the provider's status, and tell the tills.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="payments.payment_account",
                entity_id=r.account_id, period_start=r.day, period_end=r.day, value=rate.quantize(Decimal("0.1")),
                expected_value=baseline.mean.quantize(Decimal("0.1")) if baseline else None,
                figures={"attempts": str(r.total), "failed": str(r.failed), "account": r.account_name}))
        return found


class ReversedAfterMatch(IntelCheck):
    """A payment that was matched to money from the provider and then cancelled."""

    code = "payments.reversed_after_match"
    title = "Payment reversed after it was matched"
    area = "controls"
    description = "A payment confirmed by the provider's records was undone and then reversed."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per reversed payment that had a match (now undone) to a provider transaction."""
        rows = session.execute(text("""
            select p.id, p.number, p.amount, p.branch_id, p.business_date, a.name as account_name,
                   t.external_ref, m.undone_by, u.full_name as undone_by_name
              from payments.payment p
              join payments.payment_account a on a.id = p.payment_account_id
              join payments.match m on m.payment_id = p.id and m.status = 'undone'
              join payments.external_transaction t on t.id = m.external_transaction_id
              left join kernel.app_user u on u.id = m.undone_by
             where p.company_id = :c and p.status = 'reversed' and p.direction = 'in'
               and p.business_date between :d1 and :d2
             order by p.business_date, p.number"""),
            {"c": ctx.company_id, "d1": _since(ctx), "d2": ctx.today}).all()
        currency = _currency(session, ctx.company_id)
        seen: set[UUID] = set()
        found = []
        for r in rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            who = f" The match was undone by {r.undone_by_name}." if r.undone_by_name else ""
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium",
                summary=(f"Payment {r.number} of {_money(currency, r.amount)} through {r.account_name} was reversed "
                         f"after it had been matched to {r.external_ref}.{who}"),
                recommended_action="Ask who reversed it and why, and check the money is accounted for.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="payments.payment", entity_id=r.id,
                period_start=r.business_date, period_end=r.business_date, amount=r.amount,
                records=(Record("payments.payment", r.id, f"Payment {r.number}"),),
                figures={"amount": str(r.amount), "transaction": r.external_ref}))
        return found


class ManualPaymentWithoutEvidence(IntelCheck):
    """A mobile money, bank or card payment typed in with nothing from the provider to back it up."""

    code = "payments.manual_without_evidence"

    value_kind = "money"
    title = "Payment with no provider evidence"
    area = "controls"
    description = "A large mobile money, bank or card payment was recorded but no provider transaction supports it."
    default_severity = "medium"
    params: dict[str, Any] = {"amount_limit": "1000.00", "hours": 24, "days": 30}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per payment at or above the limit with no applied match, once past the waiting time. It closes
        by itself when the provider's transaction arrives and is matched."""
        rows = session.execute(text(f"""
            select p.id, p.number, p.amount, p.branch_id, p.business_date, p.method, a.name as account_name,
                   u.full_name as recorded_by
              from payments.payment p
              join payments.payment_account a on a.id = p.payment_account_id
              left join kernel.app_user u on u.id = p.created_by
             where p.company_id = :c and p.direction = 'in' and p.status = 'posted'
               and p.method in ('mobile_money', 'bank', 'card') and p.amount >= :limit
               and p.business_date between :d1 and :d2
               and p.created_at < now() - make_interval(hours => :h)
               and not exists (select 1 from payments.match m where m.payment_id = p.id and m.status = 'applied')
               and not exists (select 1 from payments.payment_allocation x
                                where x.payment_id = p.id and x.doc_type in {INTERNAL})
             order by p.business_date, p.number"""),
            {"c": ctx.company_id, "limit": ctx.number("amount_limit"), "h": int(ctx.number("hours")),
             "d1": _since(ctx), "d2": ctx.today}).all()
        currency = _currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="medium",
            summary=(f"Payment {r.number} of {_money(currency, r.amount)} ({r.method.replace('_', ' ')}, "
                     f"{r.account_name}) recorded on {r.business_date}"
                     f"{' by ' + r.recorded_by if r.recorded_by else ''} has no matching transaction from the "
                     f"provider."),
            recommended_action="Ask for the provider's confirmation (receipt or statement line) for this payment.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="payments.payment", entity_id=r.id,
            period_start=r.business_date, period_end=r.business_date, value=r.amount,
            expected_value=ctx.number("amount_limit"), amount=r.amount,
            records=(Record("payments.payment", r.id, f"Payment {r.number}"),),
            figures={"amount": str(r.amount), "method": r.method}) for r in rows]


class PromptFailureRate(BaselineMetric):
    """Share of a payment account's prompts that failed or timed out, per day (percent)."""

    code = "payments.prompt_failure_rate"
    title = "Payment prompt failure rate"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        """One sample per account per day with at least three finished prompts (UTC days)."""
        return [Sample(str(r.account_id), Decimal(r.failed) * 100 / Decimal(r.total))
                for r in _prompt_stats(session, company_id, "UTC", date_from, date_to) if r.total >= 3]
