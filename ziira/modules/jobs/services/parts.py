"""Use cases: parts and labour on a job.

A part is a stock item (issued from a location through Inventory at the ledger's average cost, so stock and the books
follow), something bought in and priced by hand, something *ordered for this job* (it arrives later; arrival moves the
job on), or a part the customer brought (labour only: it is listed on the job, never invoiced). A part may carry a class
(genuine, aftermarket, used: insurers care) and a category whose markup on cost prices it when no price is given.
Labour is hours times a rate, priced by work type (mechanical, body, paint, electrical), or a task from the flat-rate
library (a standard time, optionally a fixed price). Prices include tax. Lines are never edited: a wrong line is removed
(a stock part goes back on the shelf at the cost it left at) and added again.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.domain import pricing
from ziira.modules.jobs.permissions import JOBS_MANAGE, JOBS_PARTS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobLabour, JobPart
from ziira.modules.jobs.services import approval, catalog, claims_link, totals
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, check_person, clean, load_job, unit_enabled
from ziira.modules.jobs.services.jobs import require_editable
from ziira.modules.products.public import ProductView, find_product, selling_prices
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
)

MAX_LINES = 200
SOURCES = ("stock", "bought_in", "special_order", "customer_supplied")


def _product(session: Session, job: Job, product_id: UUID) -> ProductView:
    product = find_product(session, product_id)
    if product is None or product.company_id != job.company_id or not product.is_active:
        raise ValidationFailed("Product not found in this company")
    return product


def part_tax_code(session: Session, job: Job, product: ProductView | None) -> UUID | None:
    """The tax code a part is charged at: the Parts item's when it will be invoiced under it (stock and hand-priced
    parts), else the product's own."""
    settings = job_settings.get_settings(session, job.company_id)
    if product is not None and product.product_type != "stock":
        return product.tax_code_id
    if settings.parts_product_id is not None:
        stand_in = find_product(session, settings.parts_product_id)
        if stand_in is not None:
            return stand_in.tax_code_id
    return product.tax_code_id if product is not None else None


def default_location(session: Session, job: Job) -> UUID:
    if not unit_enabled(session, "inventory"):
        raise ValidationFailed("Stock is not switched on for this business, so parts cannot be taken from it")
    from ziira.modules.inventory.public import locations_for_branch

    places = locations_for_branch(session, job.company_id, job.branch_id)
    if not places:
        raise ValidationFailed("This branch has no store to take parts from. Add one in Stock first")
    return places[0].id


def marked_up(session: Session, cost: Decimal, markup_percent: Decimal, tax_code_id: UUID | None) -> Decimal:
    """The tax-inclusive selling price for a cost (without tax): cost plus the markup, plus the tax of the code."""
    rate = totals.Rates(session).of(tax_code_id)
    return pricing.cents(cost * (1 + markup_percent / 100) * (1 + rate / 100))


def add_part(session: Session, job_id: UUID, *, quantity: Decimal, product_id: UUID | None = None,
             description: str | None = None, unit_price: Decimal | None = None, tax_code_id: UUID | None = None,
             location_id: UUID | None = None, part_class: str | None = None, category_code: str | None = None,
             customer_supplied: bool = False, order_for_job: bool = False, cost_price: Decimal | None = None,
             supplier_name: str | None = None, supplier_id: UUID | None = None, expected_on: date | None = None,
             purchase_order_number: str | None = None, keep_old_part: bool = False,
             old_part_note: str | None = None) -> JobPart:
    """Use a part on the job.

    A stock product is issued from a location (the branch's first store unless named). A part with no product (or a
    service item) needs a description and a price, or a cost and a category to mark it up. `customer_supplied`: the
    customer brought it (never invoiced, no stock). `order_for_job`: it is being ordered for this job (stock is taken
    when it arrives). Needs 'jobs.parts'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_PARTS, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    if quantity <= 0:
        raise ValidationFailed("Quantity must be more than zero")
    if customer_supplied and order_for_job:
        raise ValidationFailed("A part cannot be both brought by the customer and ordered for the job")
    if len([p for p in repo.parts(session, job.id) if p.voided_at is None]) >= MAX_LINES:
        raise ValidationFailed(f"At most {MAX_LINES} parts on a job")
    product = _product(session, job, product_id) if product_id is not None else None
    name = clean(description, 300) or (product.name if product else None)
    if name is None:
        raise ValidationFailed("Say what the part is")
    if part_class not in (None, "genuine", "aftermarket", "used"):
        raise ValidationFailed("A part is genuine, aftermarket or used")
    category = None
    if category_code:
        category = repo.part_category_by_code(session, job.company_id, category_code.strip().lower())
        if category is None:
            raise ValidationFailed("That part category does not exist")
        part_class = part_class or category.default_class
    if cost_price is not None and cost_price < 0:
        raise ValidationFailed("The cost cannot be negative")
    is_stock = product is not None and product.product_type == "stock" and not customer_supplied \
        and not order_for_job
    source = "customer_supplied" if customer_supplied else "special_order" if order_for_job \
        else "stock" if is_stock else "bought_in"
    tax_code = tax_code_id or (None if customer_supplied else part_tax_code(session, job, product))

    price = unit_price
    if customer_supplied:
        price = price if price is not None else Decimal(0)
    elif price is None and category is not None and category.markup_percent > 0:
        base = cost_price
        if base is None and is_stock and product is not None:
            from ziira.modules.inventory.public import average_cost

            base = average_cost(session, job.company_id, product.id)
        if base is not None and base > 0:
            price = marked_up(session, base, category.markup_percent, tax_code)
    if price is None and product is not None:
        price = selling_prices(session, job.company_id, job.branch_id, {product.id}).get(product.id)
        payer = claims_link.terms(session, job)
        if price is not None and payer is not None:             # the insurer's parts rule: markup then discount
            price = payer.parts_price(price)
    if price is None or price < 0:
        raise ValidationFailed("Enter a price for this part (it has no selling price yet)")
    if not customer_supplied:
        approval.guard(session, job, pricing.line_total(quantity, price), name)

    part = JobPart(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, product_id=product.id if product else None,
        description=name, quantity=quantity, unit_price=price, tax_code_id=tax_code, is_stock=is_stock,
        source=source, part_class=part_class, category_code=category.code if category else None,
        cost_price=cost_price, keep_old_part=keep_old_part, old_part_note=clean(old_part_note, 300),
        order_status="to_order" if order_for_job else None, supplier_name=clean(supplier_name, 160),
        supplier_id=supplier_id, expected_on=expected_on)
    repo.add(session, part)
    if order_for_job and (purchase_order_number or "").strip():
        _link_order(session, job, part, purchase_order_number)
    if is_stock and product is not None:
        _issue(session, job, part, product, location_id)
    session.flush()
    add_event(session, job, "parts", f"{quantity.normalize():f} x {name}"
              + (" (brought by the customer)" if customer_supplied else " (ordered for the job)" if order_for_job
                 else ""))
    audit_record(session, "add_part", "jobs.job", job.id, {"part": str(part.id), "stock": is_stock})
    return part


def _issue(session: Session, job: Job, part: JobPart, product: ProductView, location_id: UUID | None) -> None:
    from ziira.modules.inventory.public import issue_stock_to_job

    part.location_id = location_id or default_location(session, job)
    used = issue_stock_to_job(session, company_id=job.company_id, location_id=part.location_id,
                              product_id=product.id, quantity=part.quantity, job_id=job.id, line_id=part.id)
    part.unit_cost, part.cost_value = used.unit_cost, used.value


def _link_order(session: Session, job: Job, part: JobPart, number: str | None) -> None:
    """Tie the part to a purchase order of Purchasing, found by its number (the supplier and expected date follow)."""
    part.purchase_order_number = clean(number, 40)
    if number and unit_enabled(session, "purchasing"):
        from ziira.modules.purchasing.public import find_order_by_number

        found = find_order_by_number(session, job.company_id, number)
        if found is None:
            raise ValidationFailed(f"There is no purchase order {number.strip()}")
        part.purchase_order_id, part.purchase_order_number = found.id, found.number
        part.supplier_id, part.supplier_name = found.supplier_id, found.supplier_name
        part.expected_on = part.expected_on or found.expected_date
        if part.order_status == "to_order":
            part.order_status, part.ordered_at = "ordered", datetime.now(UTC)


def _load_part(session: Session, job: Job, part_id: UUID, *, lock: bool = True) -> JobPart:
    part = repo.get(session, JobPart, part_id, lock=lock)
    if part is None or part.job_id != job.id:
        raise NotFound("Part not found")
    return part


def mark_ordered(session: Session, job_id: UUID, part_id: UUID, *, supplier_name: str | None = None,
                 supplier_id: UUID | None = None, expected_on: date | None = None,
                 purchase_order_number: str | None = None) -> JobPart:
    """A part for the job has been ordered from a supplier. Needs 'jobs.parts'."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_PARTS, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    part = _load_part(session, job, part_id)
    if part.source != "special_order" or part.voided_at is not None:
        raise ValidationFailed("Only a part ordered for this job can be marked as ordered")
    if part.order_status == "arrived":
        raise Conflict("This part has already arrived")
    part.supplier_name = clean(supplier_name, 160) or part.supplier_name
    part.supplier_id = supplier_id or part.supplier_id
    part.expected_on = expected_on or part.expected_on
    if (purchase_order_number or "").strip():
        _link_order(session, job, part, purchase_order_number)
    part.order_status, part.ordered_at = "ordered", part.ordered_at or datetime.now(UTC)
    session.flush()
    add_event(session, job, "parts", f"Ordered {part.description}"
              + (f" from {part.supplier_name}" if part.supplier_name else "")
              + (f", expected {part.expected_on.isoformat()}" if part.expected_on else ""))
    return part


def mark_arrived(session: Session, job_id: UUID, part_id: UUID, *, location_id: UUID | None = None) -> JobPart:
    """The ordered part has arrived. A stock product is taken from the store now (receive it in Purchasing first); the
    job moves out of 'waiting' only through its own stages. Needs 'jobs.parts'."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_PARTS, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    part = _load_part(session, job, part_id)
    if part.source != "special_order" or part.voided_at is not None:
        raise ValidationFailed("Only a part ordered for this job can be marked as arrived")
    if part.order_status == "arrived":
        return part
    product = find_product(session, part.product_id) if part.product_id else None
    if product is not None and product.product_type == "stock":
        part.is_stock = True
        _issue(session, job, part, product, location_id)
    part.order_status, part.arrived_at = "arrived", datetime.now(UTC)
    session.flush()
    add_event(session, job, "parts", f"{part.description} has arrived")
    audit_record(session, "part_arrived", "jobs.job", job.id, {"part": str(part.id)})
    return part


def note_goods_received(session: Session, order_id: UUID) -> int:
    """Purchasing received goods for an order: mark the job parts waiting on that order as arrived (parts that take
    stock stay 'ordered' until staff take them, so the stock movement is a person's decision). Returns how many."""
    from sqlalchemy import select

    n = 0
    for part in session.scalars(select(JobPart).where(JobPart.purchase_order_id == order_id,
                                                      JobPart.order_status == "ordered",
                                                      JobPart.voided_at.is_(None))):
        job = repo.get(session, Job, part.job_id)
        if job is None:
            continue
        product = find_product(session, part.product_id) if part.product_id else None
        if product is not None and product.product_type == "stock":
            add_event(session, job, "parts", f"Stock for {part.description} has been received: mark it as arrived")
            continue
        part.order_status, part.arrived_at = "arrived", datetime.now(UTC)
        add_event(session, job, "parts", f"{part.description} has arrived (order {part.purchase_order_number})")
        n += 1
    session.flush()
    return n


def remove_part(session: Session, job_id: UUID, part_id: UUID, reason: str | None = None) -> JobPart:
    """Take a part off the job; a stock part goes back into stock at its cost. Needs 'jobs.parts'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_PARTS, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    part = repo.get(session, JobPart, part_id, lock=True)
    if part is None or part.job_id != job.id:
        raise NotFound("Part not found")
    if part.voided_at is not None:
        return part
    if part.is_stock:
        from ziira.modules.inventory.public import return_stock_from_job

        return_stock_from_job(session, job_id=job.id, line_id=part.id)
    part.voided_at, part.voided_by = datetime.now(UTC), ctx.user_id
    part.void_reason = clean(reason, 300)
    session.flush()
    why = f": {part.void_reason}" if part.void_reason else ""
    add_event(session, job, "parts", f"Removed {part.description}{why}")
    audit_record(session, "remove_part", "jobs.job", job.id, {"part": str(part.id)})
    return part


def return_unused(session: Session, job_id: UUID, part_id: UUID, *, quantity: Decimal,
                  reason: str | None = None) -> JobPart | None:
    """Part of a part was not used: put `quantity` back (stock goes back on the shelf at the cost it left at). The line
    keeps what was used. Returns the new line for what remains, or None when everything went back. Needs
    'jobs.parts'."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_PARTS, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    part = _load_part(session, job, part_id)
    if part.voided_at is not None:
        raise Conflict("This part is already off the job")
    if quantity <= 0 or quantity > part.quantity:
        raise ValidationFailed(f"Return more than zero and at most {part.quantity.normalize():f}")
    why = clean(reason, 300) or "Not used"
    left = part.quantity - quantity
    if left <= 0:
        remove_part(session, job_id, part_id, why)
        return None
    remaining = JobPart(
        tenant_id=part.tenant_id, created_by=part.created_by, job_id=job.id, product_id=part.product_id,
        description=part.description, quantity=left, unit_price=part.unit_price, tax_code_id=part.tax_code_id,
        is_stock=part.is_stock, source=part.source, part_class=part.part_class, category_code=part.category_code,
        order_status=part.order_status, supplier_id=part.supplier_id, supplier_name=part.supplier_name,
        purchase_order_id=part.purchase_order_id, purchase_order_number=part.purchase_order_number,
        expected_on=part.expected_on, ordered_at=part.ordered_at, arrived_at=part.arrived_at,
        cost_price=part.cost_price, keep_old_part=part.keep_old_part, old_part_note=part.old_part_note,
        location_id=part.location_id)
    repo.add(session, remaining)
    was_stock, location, product_id = part.is_stock, part.location_id, part.product_id
    remove_part(session, job_id, part_id, f"Returned {quantity.normalize():f} of {part.quantity.normalize():f}: {why}")
    if was_stock and product_id is not None:
        product = find_product(session, product_id)
        if product is not None:
            remaining.location_id = location
            _issue(session, job, remaining, product, location)
    session.flush()
    return remaining


# --------------------------------------------------------------------------- labour
def labour_rate(session: Session, company_id: UUID) -> Decimal:
    return job_settings.get_settings(session, company_id).default_labour_rate


def add_labour(session: Session, job_id: UUID, *, hours: Decimal | None = None, description: str | None = None,
               rate: Decimal | None = None, assignee_id: UUID | None = None, work_date: date | None = None,
               source: str = "manual", source_id: UUID | None = None, work_type_code: str | None = None,
               task_code: str | None = None, booked_hours: Decimal | None = None) -> JobLabour:
    """Record labour: hours times a rate. The rate is the given one, else that of the work type, else the company's.
    A `task_code` takes the standard time, name, work type and (when it has one) fixed price from the flat-rate library.
    `hours` are the hours billed; `booked_hours` is what the technician actually worked (timers fill it in). The person
    defaults to whoever is signed in. Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    flat: Decimal | None = None
    wt = work_type_code.strip().lower() if work_type_code else None
    if task_code:
        task = repo.labour_task_by_code(session, job.company_id, task_code.strip().lower())
        if task is None or not task.is_active:
            raise ValidationFailed("That task is not in the library")
        hours = hours if hours is not None else task.standard_hours
        description = description or task.name
        wt = wt or task.work_type_code
        flat = task.flat_price if (hours == task.standard_hours) else None
    if hours is None or hours <= 0 or hours > 1000:
        raise ValidationFailed("Hours are more than zero and at most 1000")
    if rate is not None and rate < 0:
        raise ValidationFailed("The rate cannot be negative")
    if booked_hours is not None and (booked_hours < 0 or booked_hours > 1000):
        raise ValidationFailed("Booked hours are between 0 and 1000")
    if wt and repo.work_type_by_code(session, job.company_id, wt) is None:
        raise ValidationFailed("That work type does not exist. Add it in the job settings first")
    person = assignee_id or ctx.user_id
    check_person(session, person)
    if source_id is not None:
        for existing in repo.labour(session, job.id, include_voided=False):
            if existing.source == source and existing.source_id == source_id:
                return existing
    if len([x for x in repo.labour(session, job.id) if x.voided_at is None]) >= MAX_LINES:
        raise ValidationFailed(f"At most {MAX_LINES} labour lines on a job")
    default = labour_rate(session, job.company_id)
    used_rate = rate if rate is not None else catalog.rate_for_work_type(session, job.company_id, wt, default)
    payer = claims_link.terms(session, job) if rate is None and flat is None else None
    payer_rate = payer.labour_rate(wt) if payer is not None else None
    if payer_rate is not None:                                 # the insurer's rate for this kind of work
        used_rate = payer_rate
    if flat is not None and rate is None:
        used_rate = pricing.cents(flat / hours)           # what the fixed price comes to per billed hour
    elif flat is not None:
        flat = None                                       # a rate typed by hand overrides the library's fixed price
    if booked_hours is None and source == "timer":
        booked_hours = hours
    amount = flat if flat is not None else pricing.line_total(hours, used_rate)
    approval.guard(session, job, amount, description or "Labour")
    line = JobLabour(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id,
                     description=clean(description, 300) or "Labour", hours=hours, rate=used_rate,
                     assignee_id=person, work_date=work_date or company_today(session, job.company_id),
                     source=source[:30], source_id=source_id, work_type_code=wt,
                     task_code=task_code.strip().lower() if task_code else None, booked_hours=booked_hours,
                     flat_price=flat)
    repo.add(session, line)
    add_event(session, job, "labour", f"{hours.normalize():f} h {line.description}")
    audit_record(session, "add_labour", "jobs.job", job.id, {"line": str(line.id)})
    return line


def book_hours(session: Session, job_id: UUID, line_id: UUID, booked_hours: Decimal) -> JobLabour:
    """Say how long the technician really worked on a labour line (billed hours stay as quoted). Needs 'jobs.manage'.
    Allowed on an invoiced job too: it changes no money."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    line = repo.get(session, JobLabour, line_id)
    if line is None or line.job_id != job.id:
        raise NotFound("Labour line not found")
    if booked_hours < 0 or booked_hours > 1000:
        raise ValidationFailed("Booked hours are between 0 and 1000")
    line.booked_hours = booked_hours
    session.flush()
    return line


def remove_labour(session: Session, job_id: UUID, line_id: UUID) -> JobLabour:
    """Take a labour line off the job. Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    line = repo.get(session, JobLabour, line_id, lock=True)
    if line is None or line.job_id != job.id:
        raise NotFound("Labour line not found")
    if line.voided_at is None:
        line.voided_at, line.voided_by = datetime.now(UTC), ctx.user_id
        session.flush()
        add_event(session, job, "labour", f"Removed {line.description}")
    return line


def labour_total(line: JobLabour) -> Decimal:
    return line.flat_price if line.flat_price is not None else pricing.line_total(line.hours, line.rate)
