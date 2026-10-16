"""Use case: add the statutory rule tables a country pack supplies, as data the business edits and verifies.

Idempotent and non-destructive: a code the company already has any table for (its own, or an earlier seeding) is left
alone, so nothing it entered is replaced or given a newer version; nothing is removed; every seeded table is saved
*unverified* (someone other than the system must check it against the official notice before a payroll run that used it
is approved)."""

from uuid import UUID

from sqlalchemy import select

from ziira.modules.people.domain import rules as domain
from ziira.modules.people.public import STATUTORY_TABLE_SEED
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import PayComponent, RateTable
from ziira.sdk import Session, audit_record, current_context, pack_providers


def seed_statutory_tables(session: Session, company_id: UUID) -> int:
    """Add the pack's rule tables the company lacks. Returns how many."""
    ctx = current_context()
    have = set(session.scalars(select(RateTable.code).where(RateTable.company_id == company_id)))
    components = set(session.scalars(select(PayComponent.code).where(PayComponent.company_id == company_id)))
    added: list[str] = []
    for provider in pack_providers(session, STATUTORY_TABLE_SEED, company_id):
        for table in provider.tables():
            code = table.code.strip().upper()
            if code in have or code in components:
                continue
            domain.parse_rule(code, table.definition)                   # a pack's mistake fails loudly, here
            people_repo.add(session, RateTable(
                tenant_id=ctx.tenant_id, created_by=None, company_id=company_id, code=code,
                effective_from=table.effective_from, definition=table.definition,
                source_reference=table.source_reference, is_verified=False))
            added.append(code)
    if added:
        audit_record(session, "seed_statutory_rules", "people.statutory_rule", None,
                     {"company_id": str(company_id), "codes": added})
    return len(added)
