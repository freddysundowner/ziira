"""Recurring work of Memberships (run by `ziira worker`): invoice the periods that are due, renew and end memberships,
expire packages, and queue reminders. Each item is done in its own savepoint, so one customer's problem never stops the
rest, and a problem is put in the exceptions inbox (never skipped silently)."""

import logging
from datetime import date
from uuid import UUID

from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import (
    common,
    dues,
    members,
    packages,
    reminders,
    retention,
    schedules,
    values,
)
from ziira.sdk import Session, flag_for_review, periodic

log = logging.getLogger("ziira.memberships")


def _guarded(session: Session, company_id: UUID, what: str, key: str, work: object) -> None:
    """Run one item's work in a savepoint; on failure undo only that item and flag it."""
    try:
        with session.begin_nested():
            work()  # type: ignore[operator]
    except Exception as error:  # noqa: BLE001 - flagged for a person, the next run tries again
        log.exception("Memberships: %s failed", what)
        flag_for_review(session, unit="memberships", kind="task_failed", severity="medium", company_id=company_id,
                        message=f"{what} could not be done: {error}"[:500], dedupe_key=f"memberships-task:{key}")


def bill_company(session: Session, company_id: UUID, today: date) -> dict[str, int]:
    """Everything due for one company on `today`. Returns counts, for tests and for `ziira run-task`."""
    done = {"schedules": 0, "members": 0, "packages": 0}
    for row in repo.many(session, "select id, name from memberships.schedule where company_id = :c and ("
                                  "(status = 'active' and next_run <= :d) or "
                                  "(status = 'paused' and resume_on is not null and resume_on <= :d)) "
                                  "order by next_run, id",
                         c=company_id, d=today):
        _guarded(session, company_id, f"Recurring invoice {row['name']}", f"schedule:{row['id']}",
                 lambda r=row: schedules.run_due(session, r["id"], today))
        done["schedules"] += 1
    for row in repo.many(session, "select id, number from memberships.member where company_id = :c and ("
                                  "(status = 'active' and (next_renewal_date <= :d or (end_date is not null "
                                  "and end_date <= :d))) or (status in ('paused', 'frozen') and resume_on is not null "
                                  "and resume_on <= :d)) order by next_renewal_date, id", c=company_id, d=today):
        _guarded(session, company_id, f"Membership {row['number']}", f"member:{row['id']}",
                 lambda r=row: members.process_member(session, r["id"], today))
        done["members"] += 1
    _guarded(session, company_id, "Expiring packages", f"packages:{company_id}",
             lambda: packages.expire_due(session, company_id, today))
    _guarded(session, company_id, "Expiring vouchers", f"vouchers:{company_id}",
             lambda: values.expire_due(session, company_id, today))
    _guarded(session, company_id, "Unpaid invoices", f"dues:{company_id}",
             lambda: dues.refresh_runs(session, company_id, today=today))
    _guarded(session, company_id, "Holds for unpaid fees", f"holds:{company_id}",
             lambda: (dues.apply_arrears_holds(session, company_id, today),
                      dues.release_arrears_holds(session, company_id)))
    return done


@periodic("memberships.run_billing", every_seconds=3600)
def run_billing(session: Session) -> None:
    """Invoice due recurring invoices and membership renewals, resume held memberships, end finished ones and expire
    packages, for each company in its own date."""
    for company in repo.many(session, "select id from kernel.company order by id"):
        bill_company(session, company["id"], common.today(session, company["id"]))


@periodic("memberships.send_reminders", every_seconds=3600)
def send_reminders(session: Session) -> None:
    """Queue renewal and package-expiry reminders, late-payment reminders and retention messages (outside quiet
    hours)."""
    for company in repo.many(session, "select id from kernel.company order by id"):
        _guarded(session, company["id"], "Membership reminders", f"reminders:{company['id']}",
                 lambda c=company: reminders.send_due(session, c["id"]))
        _guarded(session, company["id"], "Late-payment reminders", f"dunning:{company['id']}",
                 lambda c=company: dues.send_dunning(session, c["id"]))
        _guarded(session, company["id"], "Retention messages", f"retention:{company['id']}",
                 lambda c=company: retention.send_due(session, c["id"]))
