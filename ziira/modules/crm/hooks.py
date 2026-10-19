"""Sockets the CRM module plugs into (declared under [extends] in manifest.toml): Intelligence checks, the figures
it adds to the Command Center, and the importer for customers."""

from uuid import UUID

from ziira.modules.crm import intel_checks, privacy, pulse  # noqa: F401 - importing registers the implementations
from ziira.modules.crm.importers import CustomerImporter
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.sdk import CUSTOM_FIELD_ENTITY, CustomFieldEntity, Session, provides

provides(IMPORTS_IMPORTER)(CustomerImporter)


@provides(CUSTOM_FIELD_ENTITY)
class CustomerFields(CustomFieldEntity):
    """Custom fields on a customer (a tailor's measurements, a garage's preferred contact ...). Added for the service
    industry packs; a business may add its own."""

    entity_type = "crm.customer"
    label = "Customer"
    view_permission = "customers.view"
    edit_permission = "customers.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        from sqlalchemy import text

        row = session.execute(text("select company_id from crm.customer where id = :i"),
                              {"i": str(entity_id)}).first()
        return (row.company_id, None) if row else None

from ziira.modules.crm import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools
