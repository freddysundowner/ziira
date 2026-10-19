"""Sockets the Claims module plugs into (declared under [extends] in manifest.toml)."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.claims import privacy as _privacy  # noqa: F401 - registers the personal-data provider
from ziira.modules.claims.intel_checks import CHECKS
from ziira.modules.claims.pulse import ClaimsPulse
from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_CHECK
from ziira.sdk import ATTACHABLE_ENTITY, AttachableEntity, Category, IntegrityCheck, Session, provides

for _check in CHECKS:
    provides(INTEL_CHECK)(_check)
provides(COMMAND_PULSE_SOURCE)(ClaimsPulse)


@provides(ATTACHABLE_ENTITY)
class ClaimFiles(AttachableEntity):
    """Photos and documents on a claim: damage photos, the assessor's report, the payer's papers. A file marked
    shareable
    appears on the payer's response page."""

    entity_type = "claims.claim"
    label = "Claim"
    view_permission = "claims.view"
    edit_permission = "claims.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from claims.claim where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None

    def categories(self, session: Session) -> list[Category]:
        return [Category("damage", "Damage"), Category("assessor", "Assessor"), Category("documents", "Documents"),
                Category("repair", "Repair"), Category("other", "Other")]


@provides("kernel.integrity_check")
class RunInvoiceCheck(IntegrityCheck):
    """Every invoice a billing run says it made must exist in Point of Sale, and a billed line must belong to a run."""

    name = "claim invoices"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        problems: list[str] = []
        orphans = session.execute(text(
            "select c.number, count(*) as n from claims.estimate_line x join claims.claim c on c.id = x.claim_id "
            "where x.invoiced_run_id is not null and not exists (select 1 from claims.invoice_run r "
            "where r.id = x.invoiced_run_id) group by c.number")).all()
        problems += [f"Claim {r.number} has {r.n} line(s) marked invoiced with no billing run" for r in orphans]
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).first()
        if enabled is None:
            return problems
        from ziira.modules.pos.public import invoice_states

        runs = session.execute(text(
            "select r.id, r.payer_invoice_id, r.customer_invoice_id, c.number from claims.invoice_run r "
            "join claims.claim c on c.id = r.claim_id")).all()
        wanted = {i for r in runs for i in (r.payer_invoice_id, r.customer_invoice_id) if i}
        found = invoice_states(session, wanted)
        for r in runs:
            for kind, invoice_id in (("payer", r.payer_invoice_id), ("customer", r.customer_invoice_id)):
                if invoice_id is not None and invoice_id not in found:
                    problems.append(f"Claim {r.number}: the {kind} invoice of a run is missing in Point of Sale")
        return problems
