"""Use case: the first-run checklist of Time and Billing, worked out from what the business has actually done (so it
is true whatever order things were done in, and ticks itself)."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.timebilling.services import access, common, sample_data
from ziira.sdk import NotFound, Session, check_company

STEPS = ("service_item", "rates", "team", "client_project", "time", "invoice")


def checklist(session: Session, company_id: UUID) -> dict[str, Any]:
    """Six steps with whether each is done, how many example rates still wait to be confirmed, and whether sample
    data is available or loaded."""
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    setting = common.settings(session, company_id)
    c = {"c": str(company_id)}

    def count(sql: str) -> int:
        return int(session.execute(text(sql), c).scalar_one())

    real = count("select count(*) from timebilling.rate where company_id = :c and kind = 'bill' and not example")
    examples = count("select count(*) from timebilling.rate where company_id = :c and kind = 'bill' and example")
    done = {
        "service_item": setting.service_product_id is not None,
        "rates": real > 0,
        "team": count("select count(*) from timebilling.staff where company_id = :c and title is not null") > 0,
        "client_project": count("select count(*) from timebilling.project where company_id = :c "
                               "and code not like 'SMP-%'") > 0,
        "time": count("select count(*) from timebilling.entry where company_id = :c") > 0,
        "invoice": count("select count(*) from timebilling.invoice_batch where company_id = :c "
                         "and status in ('issued', 'cancelled')") > 0,
    }
    return {"steps": [{"key": k, "done": done[k]} for k in STEPS], "example_rates": examples,
            "sample": sample_data.status(session, company_id)}
