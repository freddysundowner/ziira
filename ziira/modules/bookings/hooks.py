"""Sockets the Bookings module plugs into (declared under [extends] in manifest.toml), and the one it offers:
`bookings.checkout_tender` (ways of paying a checkout that a unit with credit implements)."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings import privacy as _privacy  # noqa: F401  (registers the personal-data provider)
from ziira.modules.bookings.intel_checks import ALL_CHECKS
from ziira.modules.bookings.pulse import BookingsPulse
from ziira.modules.bookings.tender import CHECKOUT_TENDER, CheckoutTender
from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_CHECK
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
    define_extension_point,
    provides,
)

define_extension_point(CHECKOUT_TENDER, CheckoutTender,
                       "A way of paying a checkout with credit the business holds (a gift voucher, loyalty points)")

for _check in ALL_CHECKS:
    provides(INTEL_CHECK)(_check)
provides(COMMAND_PULSE_SOURCE)(BookingsPulse)


@provides("kernel.integrity_check")
class AppointmentHoldsCheck(IntegrityCheck):
    """An appointment that is live or finished holds its resources; one that was cancelled or missed holds none (so its
    time is free); and every appointment names at least one resource. With `--fix` the holds are put right."""

    name = "appointment holds"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        problems: list[str] = []
        stale = session.execute(text(
            "select a.number, a.status from bookings.appointment_resource ar join bookings.appointment a "
            "on a.id = ar.appointment_id where ar.holds and a.status in ('cancelled', 'no_show') "
            "order by a.number")).all()
        problems += [f"Appointment {r.number} is {r.status} but still holds its resource" for r in stale]
        loose = session.execute(text(
            "select a.number from bookings.appointment_resource ar join bookings.appointment a "
            "on a.id = ar.appointment_id where not ar.holds and a.status in ('requested', 'confirmed', 'checked_in', "
            "'in_service', 'completed') order by a.number")).all()
        problems += [f"Appointment {r.number} is live but does not hold its resource" for r in loose]
        bare = session.execute(text(
            "select a.number from bookings.appointment a where not exists (select 1 from bookings.appointment_resource "
            "ar where ar.appointment_id = a.id) order by a.number")).all()
        problems += [f"Appointment {r.number} has no resource" for r in bare]
        over = session.execute(text(
            "select a.number, a.capacity, count(*) as n from bookings.appointment a "
            "join bookings.appointment_attendee t on t.appointment_id = a.id and t.status <> 'cancelled' "
            "where a.kind = 'class' group by a.id, a.number, a.capacity having count(*) > a.capacity")).all()
        problems += [f"Class {r.number} has {r.n} people for {r.capacity} places" for r in over]
        unpaid = session.execute(text(
            "select c.number from bookings.checkout c where c.status = 'done' and c.paid_total > c.total + 0.005 "
            "order by c.number")).all()
        problems += [f"Checkout {r.number} took more than it billed" for r in unpaid]
        if fix and (stale or loose):
            session.execute(text(
                "update bookings.appointment_resource ar set holds = (a.status not in ('cancelled', 'no_show')) "
                "from bookings.appointment a where a.id = ar.appointment_id "
                "and ar.holds <> (a.status not in ('cancelled', 'no_show'))"))
        return problems


def _client_scope(session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
    row = session.execute(text("select company_id from crm.customer where id = :i"), {"i": str(entity_id)}).first()
    return (row.company_id, None) if row else None


@provides(CUSTOM_FIELD_ENTITY)
class ClientCardFields(CustomFieldEntity):
    """The client card: a business's (or a pack's) own fields about a client, such as a preferred stylist, an allergy
    note, a formula, a patch-test date. Never a clinical record."""

    entity_type = "bookings.client"
    label = "Client card"
    view_permission = "bookings.view"
    edit_permission = "bookings.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        return _client_scope(session, entity_id)


@provides(CUSTOM_FIELD_ENTITY)
class AppointmentFields(CustomFieldEntity):
    """Fields on an appointment (new or follow-up visit, who is billed)."""

    entity_type = "bookings.appointment"
    label = "Appointment"
    view_permission = "bookings.view"
    edit_permission = "bookings.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from bookings.appointment where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None


@provides(ATTACHABLE_ENTITY)
class ClientFiles(AttachableEntity):
    """Photos and documents on a client: before and after pictures (with a consent note), consent forms, referral
    letters. Administrative documents only: Ziira is not a medical record system."""

    entity_type = "bookings.client"
    label = "Client"
    view_permission = "bookings.view"
    edit_permission = "bookings.manage"
    photo_consent = True

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        return _client_scope(session, entity_id)

    def categories(self, session: Session) -> list[Category]:
        return [Category("before", "Before"), Category("after", "After"), Category("consent_form", "Consent form"),
                Category("referral", "Referral letter"), Category("other", "Other")]


@provides(ATTACHABLE_ENTITY)
class AppointmentFiles(AttachableEntity):
    """Documents on one appointment (a signed consent form, a referral letter)."""

    entity_type = "bookings.appointment"
    label = "Appointment"
    view_permission = "bookings.view"
    edit_permission = "bookings.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        row = session.execute(text("select company_id, branch_id from bookings.appointment where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, row.branch_id) if row else None

    def categories(self, session: Session) -> list[Category]:
        return [Category("consent_form", "Consent form"), Category("referral", "Referral letter"),
                Category("other", "Other")]


@provides(INDUSTRY_SEEDER)
class BookingsSeeder(IndustrySeeder):
    """Copies what an industry pack ships in `data/bookings.toml`: staff and room templates, services (priced as
    examples), price variants, commission rules, a first-run checklist, suggested settings and check limits."""

    name = "bookings"
    unit = "bookings"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        from ziira.modules.bookings.services import seed_industry

        return seed_industry.seed(session, pack, company_id)

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        from ziira.modules.bookings.services import seed_industry

        return seed_industry.untouched(session, item_type, item_id)

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        from ziira.modules.bookings.services import seed_industry

        seed_industry.remove(session, item_type, item_id)
