"""What a job is worth so far: its parts and labour, with the tax inside them."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.domain import pricing
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobCharge, JobLabour, JobPart
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.products.public import find_product, tax_code_rate
from ziira.sdk import Session


@dataclass(frozen=True)
class JobTotals:
    parts: pricing.Totals
    labour: pricing.Totals
    cost: Decimal                       # what the stock parts cost (from the ledger)
    charges: pricing.Totals = pricing.Totals(Decimal(0), Decimal(0))    # towing, storage, fees

    @property
    def grand(self) -> pricing.Totals:
        return pricing.Totals(self.parts.total + self.labour.total + self.charges.total,
                              self.parts.tax + self.labour.tax + self.charges.tax)


class Rates:
    """Tax rates looked up once per tax code."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.found: dict[UUID, Decimal] = {}

    def of(self, tax_code_id: UUID | None) -> Decimal:
        if tax_code_id is None:
            return Decimal(0)
        if tax_code_id not in self.found:
            self.found[tax_code_id] = tax_code_rate(self.session, tax_code_id) or Decimal(0)
        return self.found[tax_code_id]


def labour_tax_code(session: Session, company_id: UUID) -> UUID | None:
    """The tax code labour is charged at: that of the Labour item in the settings."""
    product_id = job_settings.get_settings(session, company_id).labour_product_id
    product = find_product(session, product_id) if product_id else None
    return product.tax_code_id if product is not None else None


def part_amount(part: JobPart, rates: Rates) -> tuple[Decimal, Decimal]:
    """(line total, tax inside) of a part."""
    total = pricing.line_total(part.quantity, part.unit_price)
    return total, pricing.tax_inside(total, rates.of(part.tax_code_id))


def labour_amount(line: JobLabour, rate: Decimal) -> tuple[Decimal, Decimal]:
    total = line.flat_price if line.flat_price is not None else pricing.line_total(line.hours, line.rate)
    return total, pricing.tax_inside(total, rate)


def charge_amount(charge: JobCharge, rates: Rates) -> tuple[Decimal, Decimal]:
    total = pricing.line_total(charge.quantity, charge.unit_price)
    return total, pricing.tax_inside(total, rates.of(charge.tax_code_id))


def job_totals(session: Session, job: Job) -> JobTotals:
    rates = Rates(session)
    parts = [p for p in repo.parts(session, job.id) if p.voided_at is None]
    labour = [x for x in repo.labour(session, job.id) if x.voided_at is None]
    labour_rate = rates.of(labour_tax_code(session, job.company_id))
    return JobTotals(
        pricing.add_up([part_amount(p, rates) for p in parts]),
        pricing.add_up([labour_amount(x, labour_rate) for x in labour]),
        sum((p.cost_value or Decimal(0) for p in parts), Decimal(0)),
        pricing.add_up([charge_amount(c, rates) for c in repo.charges(session, job.id, include_voided=False)]))
