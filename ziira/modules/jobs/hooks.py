"""Sockets the Jobs module plugs into (declared under [extends] in manifest.toml)."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_CHECK
from ziira.modules.jobs import privacy as _privacy  # noqa: F401 - registers the personal-data provider
from ziira.modules.jobs.intel_checks import CHECKS
from ziira.modules.jobs.pulse import JobsPulse
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
provides(COMMAND_PULSE_SOURCE)(JobsPulse)


@provides(CUSTOM_FIELD_ENTITY)
class WorkOrderFields(CustomFieldEntity):
    """Custom fields on a work order (a business or an industry pack adds its own)."""

    entity_type = "jobs.work_order"
    label = "Work order"
    view_permission = "jobs.view"
    edit_permission = "jobs.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from jobs.job where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None


@provides(CUSTOM_FIELD_ENTITY)
class AssetFields(CustomFieldEntity):
    """Custom fields on an item customers bring (vehicle, device, garment)."""

    entity_type = "jobs.asset"
    label = "Item customers bring"
    view_permission = "jobs.view"
    edit_permission = "jobs.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id from jobs.asset where id = :i"), {"i": str(entity_id)}).first()
        return (row.company_id, None) if row else None


@provides(ATTACHABLE_ENTITY)
class JobFiles(AttachableEntity):
    """Photos and documents on a job: intake, damage, odometer, progress, the old part (kinds are data)."""

    entity_type = "jobs.job"
    label = "Job"
    view_permission = "jobs.view"
    edit_permission = "jobs.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from jobs.job where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None

    def categories(self, session: Session) -> list[Category]:
        from ziira.modules.jobs.services import photos

        return photos.all_categories(session)


@provides(ATTACHABLE_ENTITY)
class AssetFiles(AttachableEntity):
    """Photos of an item a customer brings (a vehicle, a garment): the same kinds as a job."""

    entity_type = "jobs.asset"
    label = "Item customers bring"
    view_permission = "jobs.view"
    edit_permission = "jobs.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id from jobs.asset where id = :i"), {"i": str(entity_id)}).first()
        return (row.company_id, None) if row else None

    def categories(self, session: Session) -> list[Category]:
        from ziira.modules.jobs.services import photos

        return photos.all_categories(session)


@provides(INDUSTRY_SEEDER)
class JobsSeeder(IndustrySeeder):
    """Copies what an industry pack ships in `data/jobs.toml`: job stages and moves, intake checklists, suggested
    settings, work types, the task library, part categories, kinds of photo, job types, bays, the first-run steps,
    Intelligence limits and the sample week (see services/seed_industry.py for the shape)."""

    name = "jobs"
    unit = "jobs"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        from ziira.modules.jobs.services import seed_industry

        return seed_industry.seed(session, pack, company_id)

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        from ziira.modules.jobs.services import seed_industry

        return seed_industry.untouched(session, item_type, item_id)

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        from ziira.modules.jobs.services import seed_industry

        seed_industry.remove(session, item_type, item_id)


@provides("kernel.integrity_check")
class InvoiceLinkCheck(IntegrityCheck):
    """Every job that says it was invoiced must have its invoice in Point of Sale, and no job is invoiced twice."""

    name = "job invoices"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).first()
        if enabled is None:
            return []
        from ziira.modules.pos.public import invoice_for_source

        problems: list[str] = []
        for row in session.execute(text("select id, number, invoice_id from jobs.job where invoice_id is not null")):
            found = invoice_for_source(session, "job", row.id)
            if found is None:
                problems.append(f"Job {row.number} says it was invoiced but has no invoice in Point of Sale")
            elif found.id != row.invoice_id:
                problems.append(f"Job {row.number} points at a different invoice than the one made for it")
        return problems
