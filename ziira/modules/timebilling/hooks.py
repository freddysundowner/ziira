"""Sockets the Time and Billing module plugs into (declared under [extends] in manifest.toml)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_CHECK
from ziira.modules.timebilling.intel_checks import CHECKS
from ziira.modules.timebilling.pulse import TimeBillingPulse
from ziira.sdk import (
    ATTACHABLE_ENTITY,
    CUSTOM_FIELD_ENTITY,
    INDUSTRY_SEEDER,
    AttachableEntity,
    Category,
    CustomFieldEntity,
    IndustrySeeder,
    IntegrityCheck,
    PackData,
    SeedReport,
    Session,
    provides,
)

for _check in CHECKS:
    provides(INTEL_CHECK)(_check)
provides(COMMAND_PULSE_SOURCE)(TimeBillingPulse)


@provides(CUSTOM_FIELD_ENTITY)
class ProjectFields(CustomFieldEntity):
    """Custom fields on an engagement or matter (a matter number, a court, a year-end)."""

    entity_type = "timebilling.project"
    label = "Project, engagement or matter"
    view_permission = "time.view"
    edit_permission = "projects.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from timebilling.project where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None


@provides(CUSTOM_FIELD_ENTITY)
class ClientFields(CustomFieldEntity):
    """Custom fields on a client of the practice (the kind of engagement, the financial year-end, the contact person).
    The record is the CRM customer, so the fields belong to the client wherever it is shown."""

    entity_type = "timebilling.client"
    label = "Client (billing profile)"
    view_permission = "time.view"
    edit_permission = "projects.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, entity_id)
        return (found.company_id, None) if found else None


@provides(ATTACHABLE_ENTITY)
class ExpenseFiles(AttachableEntity):
    """The receipt for a disbursement. Whoever logs time may add and see receipts of the company's expenses."""

    entity_type = "timebilling.expense"
    label = "Expense"
    view_permission = "time.log"
    edit_permission = "time.log"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from timebilling.expense where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None

    def categories(self, session: Session) -> list[Category]:
        return [Category("receipt", "Receipt"), Category("other", "Other")]


@provides(ATTACHABLE_ENTITY)
class ProjectDocuments(AttachableEntity):
    """The documents of an engagement: the engagement letter, signed scope, deliverables, correspondence."""

    entity_type = "timebilling.project"
    label = "Engagement"
    view_permission = "time.view"
    edit_permission = "projects.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from timebilling.project where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None

    def categories(self, session: Session) -> list[Category]:
        return [Category("engagement_letter", "Engagement letter"), Category("deliverable", "Deliverable"),
                Category("correspondence", "Correspondence"), Category("other", "Other")]


@provides(INDUSTRY_SEEDER)
class TimeBillingSeeder(IndustrySeeder):
    """Copies what an industry pack ships in `data/timebilling.toml`: suggested settings, engagement templates, example
    rates (they price nothing until confirmed), activity names, standard invoice wording and Intelligence limits."""

    name = "timebilling"
    unit = "timebilling"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        from ziira.modules.timebilling.services import seed_industry

        return seed_industry.seed(session, pack, company_id)

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        from ziira.modules.timebilling.services import seed_industry

        return seed_industry.untouched(session, item_type, item_id)

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        from ziira.modules.timebilling.services import seed_industry

        seed_industry.remove(session, item_type, item_id)


@provides("kernel.integrity_check")
class TimeBillingCheck(IntegrityCheck):
    """A retainer's balance must equal its history, and every approved week's minutes must equal its entries'."""

    name = "time and billing"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        problems: list[str] = []
        for r in session.execute(text(
                "select r.id, r.balance_minutes, coalesce(sum(t.minutes), 0) as history from timebilling.retainer r "
                "left join timebilling.retainer_txn t on t.retainer_id = r.id group by r.id, r.balance_minutes")):
            if Decimal(r.balance_minutes) != Decimal(r.history):
                problems.append(f"Retainer {r.id}: the balance is {r.balance_minutes} minutes but its history adds up "
                                f"to {r.history}")
        for w in session.execute(text(
                "select w.id, w.minutes, coalesce(sum(e.minutes), 0) as logged from timebilling.week w "
                "left join timebilling.entry e on e.week_id = w.id where w.status = 'approved' "
                "group by w.id, w.minutes having w.minutes <> coalesce(sum(e.minutes), 0)")):
            problems.append(f"Approved week {w.id}: {w.minutes} minutes recorded but its entries add up to {w.logged}")
        for e in session.execute(text(
                "select id from timebilling.entry where invoice_id is not null and status <> 'approved'")):
            problems.append(f"Time entry {e.id} is on an invoice but is not approved")
        return problems


from ziira.modules.timebilling import privacy as _privacy  # noqa: E402, F401, I001 - registers the personal-data provider
