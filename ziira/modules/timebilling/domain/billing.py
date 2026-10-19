"""Turning approved time into invoice lines: grouping, rounding and amounts. Pure rules.

An invoice line for time has one rate (entries at different rates are never mixed in one line), so its amount is
`billed hours x rate`, rounded to cents. The line's billed minutes are the sum of its entries' billable minutes (what is
left after any time covered by a prepaid retainer), rounded **up** to the business's invoice increment when it has one:
rounding is applied to the line, never entry by entry, so ten 7-minute entries billed in 15-minute steps are 75 minutes
(70 rounded up), not 150.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from ziira.modules.timebilling.domain.timesheet import round_to_step

GROUPINGS = ("project", "person", "task", "day")
CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def amount_for(minutes: int, rate: Decimal) -> Decimal:
    """What `minutes` of work costs at an hourly `rate`."""
    return cents(Decimal(minutes) * rate / 60)


def expense_amount(amount: Decimal, markup_percent: Decimal) -> Decimal:
    """An expense as billed: the cost plus the markup, to cents (100.00 at 10% is 110.00)."""
    return cents(amount * (100 + markup_percent) / 100)


def gross_amount(net: Decimal, vat_percent: Decimal, includes_tax: bool) -> Decimal:
    """The tax-inclusive figure the invoice service wants for a line. Rates that already include tax pass through."""
    return net if includes_tax else cents(net * (100 + vat_percent) / 100)


@dataclass(frozen=True)
class BillableEntry:
    """One approved, unbilled entry as the grouping sees it."""

    id: UUID
    project_id: UUID
    user_id: UUID
    user_name: str
    task: str
    work_date: date
    minutes: int                    # billable minutes still to bill (after retainer cover)
    rate: Decimal | None
    note: str = ""


@dataclass
class TimeLine:
    """A proposed invoice line for time."""

    project_id: UUID
    rate: Decimal | None
    label: str
    entry_ids: list[UUID] = field(default_factory=list)
    raw_minutes: int = 0
    minutes: int = 0                # after rounding
    amount: Decimal = Decimal(0)
    dates: tuple[date, date] | None = None


def _key(entry: BillableEntry, group_by: str) -> tuple[object, ...]:
    base: tuple[object, ...] = (entry.project_id, entry.rate)
    if group_by == "person":
        return (*base, entry.user_id)
    if group_by == "task":
        return (*base, entry.task.strip().casefold())
    if group_by == "day":
        return (*base, entry.work_date)
    return base


def _label(entry: BillableEntry, group_by: str) -> str:
    if group_by == "person":
        return entry.user_name
    if group_by == "task":
        return entry.task.strip() or "General"
    if group_by == "day":
        return entry.work_date.isoformat()
    return ""


def build_lines(entries: list[BillableEntry], group_by: str = "project", round_minutes: int = 0) -> list[TimeLine]:
    """Group entries into lines (`group_by` is project, person, task or day), round each line up to `round_minutes`
    (0: no rounding) and price it. Entries with no rate make lines with `rate None` and amount 0: they must be priced
    before they can be invoiced. The order of lines follows the earliest entry."""
    if group_by not in GROUPINGS:
        raise ValueError(f"Group by one of: {', '.join(GROUPINGS)}")
    groups: OrderedDict[tuple[object, ...], TimeLine] = OrderedDict()
    for e in sorted(entries, key=lambda x: x.work_date):
        line = groups.setdefault(_key(e, group_by), TimeLine(e.project_id, e.rate, _label(e, group_by)))
        line.entry_ids.append(e.id)
        line.raw_minutes += e.minutes
        line.dates = (e.work_date, e.work_date) if line.dates is None else (
            min(line.dates[0], e.work_date), max(line.dates[1], e.work_date))
    for line in groups.values():
        line.minutes = round_to_step(line.raw_minutes, round_minutes, "up")
        line.amount = amount_for(line.minutes, line.rate) if line.rate is not None else Decimal(0)
    return list(groups.values())


def cap_write_downs(amounts: list[Decimal], remaining: Decimal) -> list[Decimal]:
    """A capped fee never bills more than `remaining`. Given the amounts of lines in date order, how much to write
    down on each so they add up to at most `remaining`: the excess comes off the newest lines first (a line can be
    written down to nothing). A negative `remaining` counts as nothing left."""
    left = max(Decimal(0), remaining)
    kept: list[Decimal] = []
    for amount in amounts:
        take = min(amount, left)
        kept.append(take)
        left -= take
    return [amount - take for amount, take in zip(amounts, kept, strict=True)]


def narrative(entries: list[BillableEntry], *, limit: int = 4000) -> str:
    """A plain-words account of the work behind an invoice: one paragraph per project, entries by date with their
    notes (or task), never more than `limit` characters. Entries without a note or task are summed in one closing
    sentence so that no hours disappear from the story."""
    from ziira.modules.timebilling.domain.timesheet import hours

    by_project: OrderedDict[UUID, list[BillableEntry]] = OrderedDict()
    for e in sorted(entries, key=lambda x: (x.work_date, x.user_name)):
        by_project.setdefault(e.project_id, []).append(e)
    parts: list[str] = []
    for rows in by_project.values():
        told: list[str] = []
        silent = 0
        for e in rows:
            said = (e.note or e.task).strip()
            if said:
                told.append(f"{e.work_date.isoformat()} {e.user_name}: {said} ({hours(e.minutes)} h)")
            else:
                silent += e.minutes
        if silent:
            told.append(f"Other work: {hours(silent)} h")
        parts.append("\n".join(told))
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
