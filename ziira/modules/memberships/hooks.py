"""Sockets the Memberships module plugs into (declared under [extends] in manifest.toml): Intelligence checks, the
figures it adds to the Command Center, the personal-data provider, custom fields on members and an integrity check."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.memberships import (  # noqa: F401 - importing registers the implementations
    intel_checks,
    privacy,
    pulse,
    tender,
)
from ziira.modules.memberships.services import seed_industry
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


@provides(CUSTOM_FIELD_ENTITY)
class MemberCustomFields(CustomFieldEntity):
    """A business's own fields on a membership (a locker number, a preferred coach)."""

    entity_type = "memberships.member"
    label = "Membership"
    view_permission = "memberships.view"
    edit_permission = "memberships.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from memberships.member where id = :i"),
                              {"i": str(entity_id)}).first()
        return None if row is None else (row.company_id, row.branch_id)


@provides(CUSTOM_FIELD_ENTITY)
class ProfileCustomFields(CustomFieldEntity):
    """A business's own fields on a member's profile (a training goal, a usual time of day). Not for health data."""

    entity_type = "memberships.profile"
    label = "Member profile"
    view_permission = "memberships.view"
    edit_permission = "memberships.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from memberships.profile where id = :i"),
                              {"i": str(entity_id)}).first()
        return None if row is None else (row.company_id, row.branch_id)


@provides(ATTACHABLE_ENTITY)
class ProfileFiles(AttachableEntity):
    """A member's photo (shown at check-in) and the forms the business keeps for them."""

    entity_type = "memberships.profile"
    label = "Member"
    view_permission = "memberships.view"
    edit_permission = "memberships.manage"
    photo_consent = True

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from memberships.profile where id = :i"),
                              {"i": str(entity_id)}).first()
        return None if row is None else (row.company_id, row.branch_id)

    def categories(self, session: Session) -> list[Category]:
        return [Category("photo", "Member photo"), Category("form", "Signed form")]


@provides(INDUSTRY_SEEDER)
class MembershipsIndustrySeeder(IndustrySeeder):
    """Plans, packages, policies, terms and check limits from an industry pack's `data/memberships.toml`."""

    name = "memberships.catalogue"
    unit = "memberships"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        return seed_industry.seed(session, pack, company_id)

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        return seed_industry.untouched(session, item_type, item_id)

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        seed_industry.remove(session, item_type, item_id)


@provides("kernel.integrity_check")
class CreditBalanceCheck(IntegrityCheck):
    """A balance of credits is never below zero unless the company allows overdraw."""

    name = "membership credits"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        rows = session.execute(text(
            "select e.holder_type, e.holder_id, sum(e.quantity) as balance, "
            "  coalesce(bool_or(s.allow_overdraw), false) as overdraw "
            "from memberships.credit_entry e left join memberships.setting s on s.company_id = e.company_id "
            "group by e.holder_type, e.holder_id having sum(e.quantity) < 0")).all()
        return [f"{r.holder_type} {r.holder_id} has {Decimal(r.balance)} credits (below zero)"
                for r in rows if not r.overdraw]
