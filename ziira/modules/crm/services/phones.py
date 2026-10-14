"""Reading a customer's or lead's phone number with the company's calling code (a company setting)."""

from uuid import UUID

from ziira.sdk import Session, company_setting, normalise_phone


def clean(session: Session, company_id: UUID, phone: str | None) -> str | None:
    """The number as international digits, or None when empty. National numbers take the company's calling code."""
    return normalise_phone(phone, str(company_setting(session, company_id, "phone_country_code")))
