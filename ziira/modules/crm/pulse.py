"""CRM's figures for the Command Center: new customers, overdue follow-ups, open leads, credit raises waiting."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, PulseSource
from ziira.sdk import Session, company_setting, provides


@provides(COMMAND_PULSE_SOURCE)
class CrmPulse(PulseSource):
    """Customer and lead numbers for a company and a day (customers and leads belong to the company, not a branch)."""

    code = "crm"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        params = {"c": str(company_id), "d": day, "tz": str(company_setting(session, company_id, "timezone"))}

        def count(sql: str) -> Decimal:
            return Decimal(session.execute(text(sql), params).scalar_one())

        new_customers = count("select count(*) from crm.customer where company_id = :c "
                              "and (created_at at time zone :tz)::date = :d")
        overdue = count("select count(*) from crm.activity a left join crm.lead l on a.related_type = 'lead' "
                        "and l.id = a.related_id left join crm.customer cu on a.related_type = 'customer' "
                        "and cu.id = a.related_id where coalesce(l.company_id, cu.company_id) = :c "
                        "and a.done_at is null and a.due_at is not null and (a.due_at at time zone :tz)::date < :d "
                        "and (a.related_type = 'customer' or l.status in ('new', 'contacted', 'qualified'))")
        leads = count("select count(*) from crm.lead where company_id = :c "
                      "and status in ('new', 'contacted', 'qualified')")
        raises = count("select count(*) from crm.customer_credit_version v join crm.customer c on c.id = v.customer_id "
                       "where c.company_id = :c and v.status = 'pending_approval' "
                       "and v.credit_limit > coalesce(v.previous_limit, c.credit_limit)")
        return [Figure("crm.new_customers", "New customers", "count", new_customers, None, True),
                Figure("crm.followups_overdue", "Overdue follow-ups", "count", overdue, None, False),
                Figure("crm.leads_open", "Open leads", "count", leads, None, None),
                Figure("crm.credit_increases_waiting", "Credit limit increases awaiting approval", "count",
                       raises, None, False)]
