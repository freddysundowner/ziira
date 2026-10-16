"""Use cases: move from a connected system into Ziira Core.

A business that connected its current system and now switches on Core units can bring over what it has already read:
products, customers and suppliers, the stock it holds, and who owes what (open invoices). Nothing is written here to
another unit's tables: the records are proposed from the canonical copy (`connect.src_*`), checked by the owning units'
importers (the Data Import module's dry run), and staged as Data Import batches, one per kind, tagged with their
connection. So every rule, permission, audit entry and number series of the owning unit applies, the work is
reconciled and (for opening balances) reversible by the existing batch reverse.

    preview  -->  commit: products, customers, suppliers --(imported)--> stock, customer and supplier balances

The second group refers to records of the first (a stock line names a product), so it is staged by a background job
only once the first group is imported. Running it again creates nothing twice: records already in Ziira are skipped,
and customers and suppliers keep the code they were given the first time.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.connect.domain import move as rules
from ziira.modules.connect.domain.move import Reason
from ziira.modules.connect.permissions import CONNECT_MANAGE
from ziira.modules.connect.repository import connect_repo
from ziira.modules.connect.repository import move_repo as repo
from ziira.modules.connect.services import connections
from ziira.modules.crm.public import find_customer_by_code
from ziira.modules.imports.public import (
    BatchSummary,
    available_importers,
    batch_summary,
    check_rows,
    discard_staged,
    find_existing,
    reverse_import,
    stage_rows,
    start_import,
    validate_staged,
)
from ziira.modules.inventory.public import locations_for_branch
from ziira.modules.purchasing.public import find_supplier_by_code
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    company_today,
    current_context,
    enqueue,
)

log = logging.getLogger("ziira.connect.move")
ADVANCE_JOB = "connect.move_advance"
IMPORTS_MANAGE = "imports.manage"
SOURCE = "connect.connection"
SAMPLE = 8
PRICE_PLACES = Decimal("0.01")
OPTIONAL_FIELDS = ("phone", "email", "tax_id")       # a party is brought over without one of these rather than lost


@dataclass(frozen=True)
class MoveOptions:
    """What the person chose: the kinds to bring, the go-live date, and the defaults Ziira cannot guess."""

    kinds: tuple[str, ...]
    as_of: date
    unit: str | None = None                         # code of the unit of measure new products get
    tax_code: str | None = None                     # code of the tax class new products get
    locations: Mapping[UUID, str] = field(default_factory=dict)      # Ziira branch -> stock location code

    def to_json(self) -> dict[str, Any]:
        return {"kinds": list(self.kinds), "unit": self.unit, "tax_code": self.tax_code,
                "locations": {str(k): v for k, v in self.locations.items()}}

    @staticmethod
    def from_row(row: Row[Any]) -> "MoveOptions":
        o = row.options
        return MoveOptions(tuple(o.get("kinds", [])), row.as_of, o.get("unit"), o.get("tax_code"),
                           {UUID(k): v for k, v in (o.get("locations") or {}).items()})


@dataclass
class KindPlan:
    """What the move would do for one kind of record."""

    kind: str
    title: str
    selected: bool
    available: bool                                 # the unit that keeps it is switched on
    allowed: bool                                   # the person may create it
    needs: list[str] = field(default_factory=list)  # units to switch on first
    candidates: int = 0                             # records read from the other system that could become this
    create: int = 0
    exists: int = 0
    skipped: int = 0
    reasons: list[Reason] = field(default_factory=list)
    sample: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)         # what would be staged (the valid rows)


@dataclass
class BranchLine:
    external_ref: str
    external_name: str | None
    branch_id: UUID | None
    branch_name: str | None
    ignored: bool


@dataclass
class Plan:
    connection_id: UUID
    company_id: UUID
    as_of: date
    kinds: list[KindPlan]
    branches: list[BranchLine]
    users: int
    codes: dict[str, dict[str, tuple[str, bool]]]

    def kind(self, kind: str) -> KindPlan:
        return next(k for k in self.kinds if k.kind == kind)


@dataclass(frozen=True)
class Proposal:
    """One record proposed from the other system: where it came from, what to call it, and the row for the importer."""

    ref: str
    label: str
    row: dict[str, str]


# --------------------------------------------------------------------------- reading and proposing
def _connection(session: Session, connection_id: UUID) -> Row[Any]:
    row = connections.get(session, connection_id, manage=True)
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected: there is nothing to move from it")
    return row


def _branch_codes(session: Session, company_id: UUID, branch_id: UUID, options: MoveOptions) -> str | None:
    """The stock location a branch's stock goes to: the one chosen, else the branch's first store."""
    chosen = options.locations.get(branch_id)
    if chosen:
        return chosen
    found = locations_for_branch(session, company_id, branch_id)
    return found[0].code if found else None


def _propose_products(session: Session, connection_id: UUID, options: MoveOptions,
                      skips: list[tuple[str, str]]) -> list[Proposal]:
    found: list[Proposal] = []
    for r in repo.products(session, connection_id):
        sku, name = rules.sku_of(r.sku), (r.name or "").strip()
        if not name:
            skips.append(("The product has no name", r.sku or r.ref))
        elif not sku:
            skips.append(("The product has no product code", name))
        elif not options.unit or not options.tax_code:
            skips.append(("Choose the unit and the tax code new products get", name))
        else:
            price = Decimal(r.unit_price) if r.unit_price is not None and Decimal(r.unit_price) >= 0 else None
            found.append(Proposal(r.ref, f"{name} ({sku})", {
                "sku": sku, "name": name, "unit": options.unit, "tax_code": options.tax_code, "type": "stock",
                "price": rules.money_text(price) if price is not None else ""}))
    return found


def _propose_parties(session: Session, connection_id: UUID, word: str, skips: list[tuple[str, str]]
                     ) -> list[Proposal]:
    found: list[Proposal] = []
    for r in repo.parties(session, connection_id, word):
        name = (r.name or "").strip()
        if r.erased:
            skips.append(("Anonymised after a privacy request", r.ref))
        elif not name:
            skips.append((f"The {word} has no name", r.ref))
        else:
            found.append(Proposal(r.ref, name, {"name": name, "phone": r.phone or "", "email": r.email or "",
                                                "tax_id": r.tax_id or ""}))
    return found


def _propose_stock(session: Session, conn: Row[Any], options: MoveOptions, names: Mapping[UUID, str],
                   skips: list[tuple[str, str]]) -> list[Proposal]:
    zone = str(company_setting(session, conn.company_id, "timezone"))
    found: list[Proposal] = []
    places: dict[UUID, str | None] = {}
    for r in repo.stock_positions(session, conn.id, options.as_of, zone):
        label = f"{r.name or r.product_ref} ({r.sku})" if r.sku else str(r.name or r.product_ref)
        quantity = Decimal(r.quantity)
        if quantity == 0:
            continue                                        # nothing on the shelf at that date: nothing to bring
        if r.sku is None or not rules.sku_of(r.sku):
            skips.append(("The product is not in the other system's product list, or has no product code", label))
        elif r.branch_id is None:
            skips.append(("The stock is at a branch that is not mapped to a Ziira branch", label))
        elif quantity < 0:
            skips.append((f"The other system's stock is negative ({rules.number_text(quantity)})", label))
        else:
            if r.branch_id not in places:
                places[r.branch_id] = _branch_codes(session, conn.company_id, r.branch_id, options)
            code = places[r.branch_id]
            if code is None:
                skips.append((f"There is no stock location at {names.get(r.branch_id, 'the branch')}", label))
                continue
            if r.cost_quantity and Decimal(r.cost_quantity) > 0:
                cost = Decimal(r.cost_value) / Decimal(r.cost_quantity)
            elif r.product_cost is not None:
                cost = Decimal(r.product_cost)
            else:
                skips.append(("No cost is known for the product", label))
                continue
            found.append(Proposal(f"{r.product_ref}@{r.branch_id}", f"{label} at {names.get(r.branch_id, code)}", {
                "sku": rules.sku_of(r.sku), "location": code, "quantity": rules.number_text(quantity),
                "unit_cost": rules.number_text(cost), "as_of": options.as_of.isoformat()}))
    return found


def _propose_balances(session: Session, conn: Row[Any], word: str, options: MoveOptions,
                      codes: Mapping[str, tuple[str, bool]], skips: list[tuple[str, str]]) -> list[Proposal]:
    field_name = "customer_code" if word == "customer" else "supplier_code"
    found: list[Proposal] = []
    for r in repo.open_invoices(session, conn.id, word, options.as_of):
        reference = (r.number or r.ref or "").strip()
        label = f"{reference} ({r.party_name})" if r.party_name else reference
        if not r.party_ref:
            skips.append((f"The invoice names no {word}", reference))
        elif r.party_ref not in codes:
            skips.append((f"The {word} is not in Ziira: bring over the {word}s as well", label))
        else:
            owed = rules.outstanding(Decimal(r.total), Decimal(r.paid)).quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)
            found.append(Proposal(r.ref, label, {
                field_name: codes[r.party_ref][0], "reference": reference,
                "invoice_date": r.issue_date.isoformat(), "due_date": r.due_date.isoformat() if r.due_date else "",
                "amount": rules.money_text(owed)}))
    return found


# --------------------------------------------------------------------------- customers and suppliers: codes
def _in_ziira(session: Session, company_id: UUID, word: str) -> Any:
    if word == "customer":
        return lambda code: find_customer_by_code(session, company_id, code) is not None
    return lambda code: find_supplier_by_code(session, company_id, code) is not None


def _assign_codes(session: Session, conn: Row[Any], kind: str, word: str, proposals: list[Proposal],
                  matches: dict[str, str]) -> dict[str, tuple[str, bool]]:
    """source ref -> (code, matched). Codes given in an earlier run are kept; a party the same as a record already in
    Ziira takes that record's code (and is not created again); the rest get the next free codes."""
    found = dict(repo.codes(session, conn.id, word))
    fresh = [p for p in proposals if p.ref not in found]
    unmatched: list[Proposal] = []
    for p in fresh:
        match = find_existing(session, kind, conn.company_id, p.row)
        if match is not None:
            found[p.ref] = (match.code, True)
            matches[p.ref] = match.reason
        else:
            unmatched.append(p)
    codes = rules.next_codes(word, [c for c, _ in found.values()], _in_ziira(session, conn.company_id, word),
                             len(unmatched))
    for p, code in zip(unmatched, codes, strict=True):
        found[p.ref] = (code, False)
    return found


# --------------------------------------------------------------------------- checking a kind
def _lenient(session: Session, kind: str, company_id: UUID, row: dict[str, str], as_of: date) -> int:
    """For a party whose row is refused: blank the optional details (phone, email, tax number) that Ziira cannot read
    and say how many were. 0 when the row is refused for something else (then it stays refused)."""
    present = [n for n in OPTIONAL_FIELDS if row.get(n)]
    bare = {**row, **dict.fromkeys(present, "")}
    if not present or check_rows(session, kind, company_id, [bare], as_of=as_of)[0].status == "invalid":
        return 0
    bad = [n for n in present if check_rows(session, kind, company_id, [{**bare, n: row[n]}],
                                            as_of=as_of)[0].status == "invalid"]
    for name in bad:
        row[name] = ""
    return len(bad)


def _check_kind(session: Session, conn: Row[Any], kp: KindPlan, proposals: list[Proposal],
                skips: list[tuple[str, str]], options: MoveOptions, planned: dict[str, set[str]],
                matches: dict[str, str]) -> None:
    """The dry run by the owning unit's own importer, folded into counts, reasons and a sample."""
    entries: list[tuple[str, str, str]] = [("skipped", reason, label) for reason, label in skips]
    kp.candidates = len(proposals) + len(skips)
    labels = {p.ref: p.label for p in proposals}
    for ref, why in matches.items():
        entries.append(("exists", f"Already in Ziira: {why}", labels.get(ref, "")))
    todo = [p for p in proposals if p.ref not in matches]
    results = check_rows(session, kp.kind, conn.company_id, [p.row for p in todo], as_of=options.as_of)
    dropped = 0
    for p, result in zip(todo, results, strict=True):
        messages = rules.forgive_lookup(result.messages, planned)
        status = result.status
        if status == "invalid" and not messages:
            status = "valid"                                # only "not there yet" for records this move will make
        elif status == "invalid" and kp.kind in ("customers", "suppliers") and _lenient(
                session, kp.kind, conn.company_id, p.row, options.as_of):
            again = check_rows(session, kp.kind, conn.company_id, [p.row], as_of=options.as_of)[0]
            status, messages = again.status, again.messages
            dropped += 1 if status == "valid" else 0
        if status == "valid":
            kp.rows.append(p.row)
            kp.create += 1
            if len(kp.sample) < SAMPLE:
                kp.sample.append(dict(p.row))
        elif status == "skipped":
            entries.append(("exists", messages[0] if messages else "Already in Ziira", p.label))
        else:
            entries.append(("skipped", "; ".join(messages), p.label))
    kp.exists = sum(1 for e in entries if e[0] == "exists")
    kp.skipped = sum(1 for e in entries if e[0] == "skipped")
    kp.reasons = rules.tally(entries)
    if dropped:
        kp.warnings.append(f"{dropped} had a phone number, email or tax number Ziira could not read; they are "
                           "brought over without it")


def build_plan(session: Session, conn: Row[Any], options: MoveOptions, *, only: tuple[str, ...] | None = None) -> Plan:
    """Everything a move would do, without doing it: per kind what would be created, what is already in Ziira and what
    cannot be brought over, and why. `only` limits it to those kinds (the second step of a move)."""
    ctx = current_context()
    importers = available_importers(session)
    units = repo.enabled_units(session)
    names = {r.branch_id: r.branch_name for r in repo.mapped_branches(session, conn.id) if r.branch_id}
    plan = Plan(conn.id, conn.company_id, options.as_of, [],
                [BranchLine(r.external_ref, r.external_name, r.branch_id, r.branch_name, r.ignored)
                 for r in repo.mapped_branches(session, conn.id)], repo.count_users(session, conn.id), {})
    planned: dict[str, set[str]] = {"product": set(), "customer": set(), "supplier": set()}
    for kind in rules.KINDS:
        importer = importers.get(kind)
        needs = [u for u in rules.NEEDS[kind] if u not in units]
        chosen = kind in options.kinds and (only is None or kind in only)
        kp = KindPlan(kind, importer.title if importer else kind, chosen, importer is not None and not needs, False,
                      needs)
        plan.kinds.append(kp)
        if importer is not None:
            kp.allowed = ctx.can(IMPORTS_MANAGE, company_id=conn.company_id) and ctx.can(
                importer.permission, company_id=conn.company_id)
    # customers and suppliers first: balances need their codes, even when they are not brought over again
    for kind, word in (("customers", "customer"), ("suppliers", "supplier")):
        kp = plan.kind(kind)
        wanted = kp.selected or plan.kind(f"{word}_balances").selected
        if not (kp.available and kp.allowed and wanted):
            continue
        skips: list[tuple[str, str]] = []
        proposals = _propose_parties(session, conn.id, word, skips)
        matches: dict[str, str] = {}
        plan.codes[word] = _assign_codes(session, conn, kind, word, proposals, matches)
        if not kp.selected:
            continue
        for p in proposals:
            p.row["code"] = plan.codes[word][p.ref][0]
        _check_kind(session, conn, kp, proposals, skips, options, planned, matches)
        planned[word] = {r["code"] for r in kp.rows}
    kp = plan.kind("products")
    if kp.selected and kp.available and kp.allowed:
        skips = []
        proposals = _propose_products(session, conn.id, options, skips)
        _check_kind(session, conn, kp, proposals, skips, options, planned, {})
        planned["product"] = {r["sku"] for r in kp.rows}
        if kp.rows and any(r["price"] for r in kp.rows):
            kp.warnings.append("Selling prices are taken as they are in the other system: check whether they include "
                               "tax")
    if kp.selected and kp.available and kp.allowed:
        kp.warnings.append("Product categories are not brought over: add them in Products")
    _plan_second_group(session, conn, plan, options, planned, names)
    return plan


def _plan_second_group(session: Session, conn: Row[Any], plan: Plan, options: MoveOptions,
                       planned: dict[str, set[str]], names: Mapping[UUID, str]) -> None:
    kp = plan.kind("opening_stock")
    if kp.selected and kp.available and kp.allowed:
        skips: list[tuple[str, str]] = []
        proposals = _propose_stock(session, conn, options, names, skips)
        _check_kind(session, conn, kp, proposals, skips, options, planned, {})
        kp.warnings.append("Cost is the average of what the other system recorded for stock coming in; "
                           "products without it use their cost price")
    for kind, word in (("customer_balances", "customer"), ("supplier_balances", "supplier")):
        kp = plan.kind(kind)
        if kp.selected and kp.available and kp.allowed:
            skips = []
            proposals = _propose_balances(session, conn, word, options, plan.codes.get(word, {}), skips)
            _check_kind(session, conn, kp, proposals, skips, options, planned, {})


def check_options(session: Session, company_id: UUID, options: MoveOptions) -> None:
    unknown = [k for k in options.kinds if k not in rules.KINDS]
    if unknown:
        raise ValidationFailed(f"Unknown kind(s): {', '.join(unknown)}")
    if not options.kinds:
        raise ValidationFailed("Choose what to bring over")
    if options.as_of > company_today(session, company_id):
        raise ValidationFailed("The go-live date cannot be in the future")


def preview(session: Session, connection_id: UUID, options: MoveOptions) -> Plan:
    """What a move would do (nothing is written, nothing is staged)."""
    conn = _connection(session, connection_id)
    check_company(session, conn.company_id)
    check_options(session, conn.company_id, options)
    return build_plan(session, conn, options)


# --------------------------------------------------------------------------- committing
def _stage(session: Session, conn: Row[Any], move_id: UUID, kp: KindPlan, options: MoveOptions, phase: int) -> None:
    """Stage one kind's valid rows as a batch tagged with the connection, check it again, and start the import. A kind
    with nothing new makes no batch."""
    if not kp.rows:
        repo.add_move_batch(session, move_id=move_id, kind=kp.kind, phase=phase, batch_id=None, staged=0,
                            note="nothing_new")
        return
    batch_id = stage_rows(session, kind=kp.kind, company_id=conn.company_id, rows=kp.rows,
                          name=f"From {conn.name}: {kp.title}", as_of=options.as_of, source=(SOURCE, conn.id))
    if validate_staged(session, batch_id).counts["valid"] == 0:
        discard_staged(session, batch_id)
        repo.add_move_batch(session, move_id=move_id, kind=kp.kind, phase=phase, batch_id=None, staged=len(kp.rows),
                            note="nothing_new")
        return
    start_import(session, batch_id)
    repo.add_move_batch(session, move_id=move_id, kind=kp.kind, phase=phase, batch_id=batch_id, staged=len(kp.rows),
                        note=None)


def start(session: Session, connection_id: UUID, options: MoveOptions) -> UUID:
    """Begin the move: stage the first group of kinds now, and let a background job stage the rest once those are
    imported. Refused when a kind needs a unit that is off, or the person may not create it."""
    conn = _connection(session, connection_id)
    connect_repo.get_connection(session, connection_id, lock=True)     # two people starting a move queue up here
    check_company(session, conn.company_id)
    check_options(session, conn.company_id, options)
    if repo.running_move(session, connection_id) is not None:
        raise Conflict("A move from this connection is already running: wait until it has finished")
    plan = build_plan(session, conn, options)
    for kp in plan.kinds:
        if kp.selected and not kp.available:
            raise ValidationFailed(f"{kp.title} cannot be brought over yet: switch on {', '.join(kp.needs) or kp.kind} "
                                   "under Add-ons first")
        if kp.selected and not kp.allowed:
            raise ValidationFailed(f"You may not bring over {kp.title.lower()}")
    move_id = repo.add_move(session, connection_id=connection_id, company_id=conn.company_id, as_of=options.as_of,
                            options=options.to_json(), created_by=current_context().user_id)
    for word in ("customer", "supplier"):
        if word in plan.codes:
            repo.save_codes(session, connection_id, word, plan.codes[word])
    for kind in rules.PHASE_ONE:
        if plan.kind(kind).selected:
            _stage(session, conn, move_id, plan.kind(kind), options, 1)
    audit_record(session, "move.start", "connect.move", move_id, {
        "connection": str(connection_id), "as_of": options.as_of.isoformat(),
        "kinds": {k.kind: {"create": k.create, "exists": k.exists, "skipped": k.skipped}
                  for k in plan.kinds if k.selected}})
    enqueue(session, ADVANCE_JOB, {"move_id": str(move_id), "attempt": 0}, dedupe_key=f"{ADVANCE_JOB}:{move_id}:0")
    return move_id


# --------------------------------------------------------------------------- the second group, and finishing
@dataclass(frozen=True)
class BatchState:
    kind: str
    title: str
    phase: int
    batch_id: UUID | None
    status: str                                 # the batch's status, or "nothing_new" / "waiting"
    staged: int
    counts: dict[str, int]
    reversible: bool
    reversal_note: str


@dataclass(frozen=True)
class MoveState:
    id: UUID
    connection_id: UUID
    company_id: UUID
    as_of: date
    state: str                                  # running | done
    needs_attention: bool                       # rows failed or were refused while importing
    batches: list[BatchState]
    created_at: Any
    finished_at: Any


def _states(session: Session, move: Row[Any], options: MoveOptions) -> list[BatchState]:
    importers = available_importers(session)
    have = {b.kind: b for b in repo.move_batches(session, move.id)}
    out: list[BatchState] = []
    for kind in rules.KINDS:
        if kind not in options.kinds:
            continue
        importer = importers.get(kind)
        title = importer.title if importer else kind
        phase = 1 if kind in rules.PHASE_ONE else 2
        b = have.get(kind)
        if b is None:
            out.append(BatchState(kind, title, phase, None, "waiting", 0, {}, bool(importer and importer.reversible),
                                  importer.reversal_note if importer else ""))
        elif b.batch_id is None:
            out.append(BatchState(kind, title, phase, None, "nothing_new", b.staged, {}, False, ""))
        else:
            s: BatchSummary = batch_summary(session, b.batch_id)
            out.append(BatchState(kind, title, phase, b.batch_id, s.status, b.staged, s.counts, s.reversible,
                                  s.reversal_note))
    return out


def advance(session: Session, move_id: UUID) -> bool:
    """Take a move a step on: once the first group is imported, stage the second; once everything is imported, finish.
    Safe to run any number of times. Returns whether the move is still running."""
    move = repo.get_move(session, move_id, lock=True)
    if move is None or move.status != "running":
        return False
    options = MoveOptions.from_row(move)
    states = _states(session, move, options)
    first = [s for s in states if s.phase == 1]
    if any(s.status in ("committing", "uploaded", "validated") for s in first):
        return True
    second = [s for s in states if s.phase == 2]
    if any(s.status == "waiting" for s in second):
        conn = connect_repo.get_connection(session, move.connection_id)
        assert conn is not None
        plan = build_plan(session, conn, options, only=rules.PHASE_TWO)
        for kp in plan.kinds:
            if kp.kind in rules.PHASE_TWO and kp.selected:
                if kp.available:
                    _stage(session, conn, move.id, kp, options, 2)
                else:
                    repo.add_move_batch(session, move_id=move.id, kind=kp.kind, phase=2, batch_id=None, staged=0,
                                        note="unavailable")
        states = _states(session, move, options)
        return True
    if any(s.status == "committing" for s in states):
        return True
    repo.finish_move(session, move.id)
    audit_record(session, "move.finish", "connect.move", move.id, {
        "imported": {s.kind: s.counts.get("imported", 0) for s in states if s.batch_id}})
    return False


def status(session: Session, move_id: UUID, *, nudge: bool = True) -> MoveState:
    """Where a move stands. Asking also takes it a step on, so the screen does not wait for the background job."""
    move = repo.get_move(session, move_id)
    if move is None:
        raise NotFound("Move not found")
    current_context().require(CONNECT_MANAGE, company_id=move.company_id)
    if nudge and move.status == "running":
        advance(session, move_id)
        move = repo.get_move(session, move_id)
        assert move is not None
    options = MoveOptions.from_row(move)
    states = _states(session, move, options)
    trouble = any(s.counts.get("failed", 0) or s.status == "unavailable" for s in states)
    return MoveState(move.id, move.connection_id, move.company_id, move.as_of, move.status, trouble, states,
                     move.created_at, move.finished_at)


def list_moves(session: Session, connection_id: UUID) -> list[MoveState]:
    connections.get(session, connection_id, manage=True)
    return [status(session, m.id, nudge=False) for m in repo.list_moves(session, connection_id)]


def undo(session: Session, move_id: UUID, reason: str) -> MoveState:
    """Reverse what a finished move can take back: opening balances, through the Data Import module's reverse (all or
    nothing, refused with the reason when later activity makes it unsafe). Products, customers, suppliers and stock
    cannot be deleted; the answer says so."""
    state = status(session, move_id, nudge=False)
    if state.state != "done":
        raise Conflict("The move is still running")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    reversible = [b for b in state.batches if b.batch_id and b.reversible and b.status == "done"]
    if not reversible:
        raise ValidationFailed("Nothing in this move can be taken back: only opening balances can, and none is left")
    for b in reversed(reversible):
        assert b.batch_id is not None
        reverse_import(session, b.batch_id, reason.strip())
    audit_record(session, "move.undo", "connect.move", move_id, {"reason": reason.strip()[:500],
                                                               "kinds": [b.kind for b in reversible]})
    return status(session, move_id, nudge=False)


# --------------------------------------------------------------------------- what the wizard asks first
@dataclass(frozen=True)
class Options:
    connection: Row[Any]
    as_of: date
    kinds: list[KindPlan]
    source_counts: dict[str, int]
    branches: list[tuple[UUID, str | None, list[tuple[str, str]]]]       # (branch, name, [(location code, name)])
    unmapped_branches: int
    running_move_id: UUID | None
    last_move_id: UUID | None


def options(session: Session, connection_id: UUID) -> Options:
    """What a person needs to start a move: which kinds can be brought over right now (and which need a unit switched
    on), what the other system holds, and the branches' stock locations to choose from."""
    conn = _connection(session, connection_id)
    ctx = current_context()
    importers = available_importers(session)
    units = repo.enabled_units(session)
    kinds: list[KindPlan] = []
    for kind in rules.KINDS:
        importer = importers.get(kind)
        needs = [u for u in rules.NEEDS[kind] if u not in units]
        allowed = importer is not None and ctx.can(IMPORTS_MANAGE, company_id=conn.company_id) and ctx.can(
            importer.permission, company_id=conn.company_id)
        kinds.append(KindPlan(kind, importer.title if importer else kind, False, importer is not None and not needs,
                              allowed, needs))
    mapped = [r for r in repo.mapped_branches(session, connection_id) if r.branch_id]
    places = "inventory" in units
    branches = [(r.branch_id, r.branch_name, [(x.code, x.name) for x in locations_for_branch(
        session, conn.company_id, r.branch_id)] if places else []) for r in mapped]
    moves = repo.list_moves(session, connection_id, 20)
    running = next((m.id for m in moves if m.status == "running"), None)
    last = next((m.id for m in moves if m.status == "done"), None)
    return Options(conn, company_today(session, conn.company_id), kinds, repo.source_counts(session, connection_id),
                   branches, sum(1 for r in repo.mapped_branches(session, connection_id)
                                 if r.branch_id is None and not r.ignored), running, last)


def suggestion(session: Session, company_id: UUID) -> tuple[bool, UUID | None]:
    """Whether to offer "Ready to run on Ziira? Move your data": a live connection has read records, a Core unit that
    can take them is switched on, and nothing was moved from it yet. Quiet for people who may not move data."""
    ctx = current_context()
    if not ctx.can(CONNECT_MANAGE, company_id=company_id) or not ctx.can(IMPORTS_MANAGE, company_id=company_id):
        return False, None
    importers = available_importers(session)
    usable = [k for k in rules.KINDS if k in importers and ctx.can(importers[k].permission, company_id=company_id)]
    if not usable:
        return False, None
    for row in connect_repo.list_connections(session, {company_id}):
        if row.status in ("disconnected", "paused") or repo.has_finished_move(session, row.id):
            continue
        counts = repo.source_counts(session, row.id)
        if counts["products"] + counts["customers"] + counts["suppliers"] + counts["stock_movements"] + counts[
                "customer_invoices"] + counts["supplier_invoices"] > 0:
            return True, row.id
    return False, None
