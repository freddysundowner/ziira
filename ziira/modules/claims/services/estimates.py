"""Use cases: estimates sent to the payer, in numbered versions.

The first estimate of a claim is version 1 of its *original* chain. When the payer counters or rejects lines, the
business
makes the next version (a revision): lines the payer already accepted stay as they were, the others are asked again with
a note. Extra damage found later is a *supplementary* chain with its own versions, approved separately. Only a draft can
be edited; sending it makes the older version of the chain superseded and ends that version's response links.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain import rates
from ziira.modules.claims.domain.money import ZERO, line_total
from ziira.modules.claims.permissions import CLAIMS_ESTIMATE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLine, Payer
from ziira.modules.claims.services import links, status
from ziira.modules.claims.services import settings as claim_settings
from ziira.modules.claims.services.common import MAX_LINES, add_event, clean, load_claim, load_estimate, now
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
    publish,
)


@dataclass(frozen=True)
class LineIn:
    kind: str
    description: str | None
    quantity: Decimal
    unit_price: Decimal | None = None          # tax included; blank: the payer's rate for labour or paint
    work_type: str | None = None
    part_class: str | None = None
    product_id: UUID | None = None
    line_id: UUID | None = None                # a line already on this draft (a revision keeps its history)


def _price(payer: Payer, line: LineIn, description: str, apply_terms: bool) -> Decimal:
    price = line.unit_price
    if price is None and line.kind == "labour":
        price = rates.labour_rate(payer.labour_rates, line.work_type)
    elif price is None and line.kind == "paint":
        price = payer.paint_rate
    elif price is not None and apply_terms and line.kind == "parts":
        price = rates.parts_price(price, payer.parts_discount_pct, payer.parts_markup_pct)
    if price is None or price < 0:
        raise ValidationFailed(f"Enter a price for {description}")
    return price


def build_lines(session: Session, claim: Claim, payer: Payer, lines: list[LineIn], *,
                apply_terms: bool) -> list[EstimateLine]:
    if len(lines) > MAX_LINES:
        raise ValidationFailed(f"An estimate has at most {MAX_LINES} lines")
    tenant_id = current_context().tenant_id
    rows: list[EstimateLine] = []
    for line in lines:
        if line.kind not in rules.KINDS:
            raise ValidationFailed(f"A line is one of: {', '.join(rules.KINDS)}")
        if line.quantity <= 0:
            raise ValidationFailed("Quantities must be more than zero")
        if line.part_class is not None and line.part_class not in rules.PART_CLASSES:
            raise ValidationFailed("A part is genuine, aftermarket or used")
        description = clean(line.description, 300)
        if description is None:
            raise ValidationFailed("Every line needs a description")
        price = _price(payer, line, description, apply_terms)
        rows.append(EstimateLine(
            tenant_id=tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=UUID(int=0), position=0,
            kind=line.kind, work_type=clean(line.work_type, 40), part_class=line.part_class if line.kind == "parts"
            else None, description=description, quantity=line.quantity, unit_price=price,
            asked_total=line_total(line.quantity, price), product_id=line.product_id))
    return rows


def _store(session: Session, estimate: Estimate, kept: list[EstimateLine], fresh: list[EstimateLine]) -> None:
    """Number the lines (kept ones first, in their order, then the new ones) and add up the estimate."""
    for row in fresh:
        row.estimate_id = estimate.id
        session.add(row)
    session.flush()
    ordered = kept + fresh
    for position, row in enumerate(ordered, start=1):
        row.position = position
    estimate.total = sum((r.asked_total for r in ordered), ZERO)
    session.flush()


def _latest_sent(session: Session, claim_id: UUID, lineage_id: UUID) -> Estimate | None:
    found = [e for e in repo.estimates(session, claim_id) if e.lineage_id == lineage_id]
    return found[-1] if found else None


def create_estimate(session: Session, claim_id: UUID, *, kind: str = "original", lines: list[LineIn] | None = None,
                    from_estimate_id: UUID | None = None, notes: str | None = None, valid_until: date | None = None,
                    title: str | None = None, revision_note: str | None = None,
                    apply_terms: bool = False) -> Estimate:
    """Start the next estimate as a draft. `kind` is `original` (the first one), `supplementary` (extra damage found
    after teardown, a chain of its own) or `revision` (the next version after the payer's answer; name the estimate
    it follows in `from_estimate_id`). Needs 'claims.estimate'."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status in ("closed", "settled"):
        raise Conflict("This claim is closed: no more estimates")
    existing = repo.estimates(session, claim.id)
    if any(e.status == "draft" for e in existing):
        raise Conflict("There is already a draft estimate on this claim. Change it or send it first")
    payer = claim_settings.load_payer(session, claim.payer_id)
    seq = max((e.seq for e in existing), default=0) + 1
    lineage, lineage_kind, lineage_no, version, previous = uuid4(), "original", 0, 1, None
    carried: list[EstimateLine] = []
    if kind == "original":
        if any(e.lineage_kind == "original" for e in existing):
            raise Conflict("This claim already has its first estimate: make a revision or a supplementary one")
    elif kind == "supplementary":
        if not any(e.lineage_kind == "original" and e.status in ("submitted", "answered") for e in existing):
            raise ValidationFailed("Send the first estimate before adding a supplementary one")
        lineage_kind, lineage_no = "supplementary", max((e.lineage_no for e in existing), default=0) + 1
    elif kind == "revision":
        if from_estimate_id is None:
            raise ValidationFailed("Say which estimate the new version follows")
        previous = next((e for e in existing if e.id == from_estimate_id), None)
        if previous is None:
            raise ValidationFailed("That estimate does not belong to this claim")
        if _latest_sent(session, claim.id, previous.lineage_id) is not previous or previous.status not in (
                "submitted", "answered"):
            raise Conflict("Only the latest sent version can be followed by a new one")
        lineage, lineage_kind, lineage_no = previous.lineage_id, previous.lineage_kind, previous.lineage_no
        version = previous.version + 1
        carried = [row for row in repo.estimate_lines(session, previous.id)]
    else:
        raise ValidationFailed("An estimate is original, supplementary or a revision")
    estimate = Estimate(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=claim.company_id, claim_id=claim.id, seq=seq,
        lineage_id=lineage, lineage_kind=lineage_kind, lineage_no=lineage_no, version=version,
        previous_id=previous.id if previous else None,
        title=clean(title, 120) or (None if kind != "supplementary" else f"Supplementary {lineage_no}"),
        notes=clean(notes, 2000), revision_note=clean(revision_note, 1000), valid_until=valid_until)
    repo.add(session, estimate)
    carried_over = [_carry(session, claim, estimate, row) for row in carried]
    kept = [row for row in carried_over if row is not None]
    fresh = build_lines(session, claim, payer, lines or [], apply_terms=apply_terms) if lines else []
    _store(session, estimate, kept, fresh)
    add_event(session, claim, "estimate", f"{label(estimate)} drafted", estimate_id=estimate.id)
    audit_record(session, "create", "claims.estimate", estimate.id, {"claim": claim.number, "kind": lineage_kind,
                                                                      "version": version})
    return estimate


def _carry(session: Session, claim: Claim, estimate: Estimate, old: EstimateLine) -> EstimateLine | None:
    """The line of the next version that follows `old`: settled lines stay as they were (locked), the rest are asked
    again, and a rejected line the customer declined is left off."""
    if old.payer_state == "rejected" and old.customer_decision == "declined":
        return None
    settled = old.payer_state == "approved" or (old.payer_state == "countered" and old.our_decision == "accepted") \
        or (old.payer_state == "rejected" and old.customer_decision == "pays")
    row = EstimateLine(
        tenant_id=old.tenant_id, company_id=old.company_id, claim_id=old.claim_id, estimate_id=estimate.id,
        position=0, kind=old.kind, work_type=old.work_type, part_class=old.part_class, description=old.description,
        quantity=old.quantity, unit_price=old.unit_price, asked_total=old.asked_total, product_id=old.product_id,
        carried_from_id=old.id, locked=settled)
    if settled:
        row.payer_state, row.payer_amount, row.payer_reason = old.payer_state, old.payer_amount, old.payer_reason
        row.responded_at, row.our_decision = old.responded_at, old.our_decision
        row.customer_decision, row.shortfall_to = old.customer_decision, old.shortfall_to
        row.customer_decision_by, row.customer_decision_at = old.customer_decision_by, old.customer_decision_at
        row.invoiced_run_id = old.invoiced_run_id
    session.add(row)
    session.flush()
    if settled and old.invoiced_run_id is not None:
        for invoice_line in repo.claim_invoice_lines(session, claim.id):
            if invoice_line.estimate_line_id == old.id:
                invoice_line.estimate_line_id = row.id
    return row


def label(estimate: Estimate) -> str:
    """How people name an estimate: 'Estimate version 2' or 'Supplementary 1, version 1'."""
    if estimate.lineage_kind == "original":
        return f"Estimate version {estimate.version}"
    return f"Supplementary {estimate.lineage_no}, version {estimate.version}"


def update_estimate(session: Session, estimate_id: UUID, *, lines: list[LineIn] | None = None,
                    notes: str | None = None, change_notes: bool = False, valid_until: date | None = None,
                    change_valid_until: bool = False, revision_note: str | None = None,
                    change_revision_note: bool = False, title: str | None = None, change_title: bool = False,
                    apply_terms: bool = False) -> Estimate:
    """Change a draft. Lines the payer already settled (kept from the version before) cannot be changed or removed; send
    the other lines in full. Needs 'claims.estimate'."""
    estimate, claim = load_estimate(session, estimate_id, lock=True)
    current_context().require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if estimate.status != "draft":
        raise Conflict("Only a draft can be changed. Make a new version instead")
    if lines is not None:
        payer = claim_settings.load_payer(session, claim.payer_id)
        existing = repo.estimate_lines(session, estimate.id)
        kept = [row for row in existing if row.locked]
        by_id = {row.id: row for row in existing}
        for entry in lines:
            if entry.line_id is not None and entry.line_id not in by_id:
                raise ValidationFailed("A line named in the change is not on this estimate")
        visible = [e for e in lines if e.line_id is None or not by_id[e.line_id].locked]
        built = build_lines(session, claim, payer, visible, apply_terms=apply_terms)
        fresh: list[EstimateLine] = []
        keep_unlocked: list[EstimateLine] = []
        for entry, row in zip(visible, built, strict=True):
            if entry.line_id is None:
                fresh.append(row)
                continue
            old = by_id[entry.line_id]                   # the same line: change it in place so its history stays
            for field in ("kind", "work_type", "part_class", "description", "quantity", "unit_price", "asked_total",
                          "product_id"):
                setattr(old, field, getattr(row, field))
            keep_unlocked.append(old)
        for row in existing:
            if not row.locked and row not in keep_unlocked:
                session.delete(row)
        session.flush()
        _store(session, estimate, kept + keep_unlocked, fresh)
    if change_notes:
        estimate.notes = clean(notes, 2000)
    if change_valid_until:
        estimate.valid_until = valid_until
    if change_revision_note:
        estimate.revision_note = clean(revision_note, 1000)
    if change_title:
        estimate.title = clean(title, 120)
    estimate.updated_by = current_context().user_id
    session.flush()
    return estimate


def submit_estimate(session: Session, estimate_id: UUID, *, channel: str | None = None, recipient: str | None = None,
                    make_link: bool = True, link_days: int | None = None) -> tuple[Estimate, str | None, bool]:
    """Send the draft to the payer. It becomes the live version of its chain (the version before is superseded and its
    links stop working). Choose how it goes:

    * `channel` (email, SMS or another channel the business has): the secure response link is queued as a message to
      `recipient` (or the payer's estimate address or first contact);
    * `make_link` with no channel: the link is made and returned once for the staff to pass on;
    * neither: the estimate is printed or sent by hand; answers are recorded by staff.

    Returns (estimate, link secret shown only now, whether a message was queued). Needs 'claims.estimate'."""
    estimate, claim = load_estimate(session, estimate_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if estimate.status != "draft":
        raise Conflict(f"This estimate is {estimate.status}")
    rows = repo.estimate_lines(session, estimate.id)
    if not rows or estimate.total <= 0:
        raise ValidationFailed("An estimate needs at least one line and must be worth more than nothing")
    if not any(not r.locked for r in rows) and estimate.previous_id is not None:
        raise ValidationFailed("Every line is already settled: there is nothing left to ask the payer")
    settings = claim_settings.get_settings(session, claim.company_id)
    day = company_today(session, claim.company_id)
    if estimate.previous_id is not None:
        before = repo.get(session, Estimate, estimate.previous_id, lock=True)
        if before is not None:
            before.status = "superseded"
            links.revoke_all(session, before.id, "a newer version was sent")
    estimate.status, estimate.submitted_at, estimate.submitted_by = "submitted", now(), ctx.user_id
    estimate.submitted_via = channel or ("link" if make_link else "hand")
    if estimate.valid_until is None:
        estimate.valid_until = day + timedelta(days=settings.estimate_valid_days)
    session.flush()
    if claim.status == "draft":
        claim.status = "open"
    secret: str | None = None
    queued = False
    if channel is not None or make_link:
        link, secret = links.create_link(session, claim, estimate, valid_days=link_days or settings.link_valid_days,
                                         sent_via=channel or "link", sent_to=None)
        if channel is not None:
            from ziira.modules.claims.services import send

            queued = send.deliver(session, claim, estimate, link, secret, channel=channel, recipient=recipient)
    add_event(session, claim, "submitted", f"{label(estimate)} sent ({estimate.submitted_via})"
              + (f". {estimate.revision_note}" if estimate.revision_note else ""), estimate_id=estimate.id)
    audit_record(session, "submit", "claims.estimate", estimate.id,
                 {"claim": claim.number, "via": estimate.submitted_via, "total": str(estimate.total)})
    status.refresh(session, claim)
    publish(session, Event("claim.estimate_submitted", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
        "estimate_id": estimate.id, "version": estimate.version, "kind": estimate.lineage_kind,
        "total": estimate.total, "source_type": claim.source_type, "source_id": claim.source_id}))
    return estimate, secret, queued


def withdraw_estimate(session: Session, estimate_id: UUID, *, note: str | None = None) -> Estimate:
    """Take back an estimate that has not been fully answered (or throw away a draft). Needs 'claims.estimate'."""
    estimate, claim = load_estimate(session, estimate_id, lock=True)
    current_context().require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if estimate.status not in ("draft", "submitted"):
        raise Conflict(f"This estimate is {estimate.status}: it cannot be withdrawn")
    if any(r.invoiced_run_id is not None for r in repo.estimate_lines(session, estimate.id)):
        raise Conflict("Part of this estimate has been invoiced")
    was_sent = estimate.status == "submitted"
    estimate.status = "withdrawn"
    session.flush()
    links.revoke_all(session, estimate.id, "the estimate was withdrawn")
    if was_sent:
        from ziira.modules.claims.services import responses

        responses.record_withdrawal(session, estimate, claim, note)
    add_event(session, claim, "estimate", f"{label(estimate)} withdrawn" + (f": {note.strip()}" if note else ""),
              estimate_id=estimate.id)
    status.refresh(session, claim)
    return estimate


def is_over_limit(payer: Payer, estimate: Estimate) -> bool:
    return payer.approval_limit is not None and estimate.total > payer.approval_limit


def expired(estimate: Estimate, today: date) -> bool:
    return estimate.valid_until is not None and estimate.valid_until < today

