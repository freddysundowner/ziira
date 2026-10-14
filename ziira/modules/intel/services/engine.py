"""The checks engine: run the checks units supply, turn what they find into findings, keep them in step with reality.

A problem seen again is the same finding (its fingerprint). A finding a check no longer reports is closed by itself
when the check says it can be (a stockout fixed), and kept for a person otherwise (a void on Tuesday). A failing check
never stops the others: it is reported in the exceptions inbox.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ziira.modules.intel.domain.model import SEVERITIES, Candidate
from ziira.modules.intel.domain.rules import severity_rank
from ziira.modules.intel.public import INTEL_CHECK, CheckContext, IntelCheck
from ziira.modules.intel.repository import findings_repo as repo
from ziira.modules.intel.services import baselines as baseline_service
from ziira.sdk import Event, Session, company_setting, flag_for_review, implementations, publish

log = logging.getLogger("ziira.intel")


@dataclass
class RunResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    reopened: int = 0
    failed: list[str] = field(default_factory=list)
    checks_run: int = 0


def local_today(session: Session, company_id: UUID) -> date:
    """Today's date in the company's time zone."""
    zone = str(company_setting(session, company_id, "timezone"))
    return datetime.now(ZoneInfo(zone)).date()


def effective_params(check: IntelCheck, overrides: dict[str, Any]) -> dict[str, Any]:
    """The check's limits: its defaults, with what the business changed (only names the check knows)."""
    return {**check.params, **{k: v for k, v in overrides.items() if k in check.params}}


def _evidence(c: Candidate) -> dict[str, Any]:
    return {"records": [{"type": r.type, "id": str(r.id) if r.id else None, "label": r.label} for r in c.records],
            "figures": c.figures}


def run_company(session: Session, company_id: UUID, *, today: date | None = None,
                only: set[str] | None = None) -> RunResult:
    """Run every enabled check for one company and update its findings. The session must be scoped to the tenant."""
    result = RunResult()
    today = today or local_today(session, company_id)
    timezone = str(company_setting(session, company_id, "timezone"))
    baselines = baseline_service.load(session, company_id)
    settings = repo.check_settings(session)
    for check in implementations(session, INTEL_CHECK):
        if only is not None and check.code not in only:
            continue
        enabled, overrides = settings.get(check.code, (True, {}))
        if not enabled:
            continue
        params = effective_params(check, overrides)
        check_id = repo.upsert_definition(
            session, code=check.code, version=int(getattr(check, "version", 1)), title=check.title, area=check.area,
            description=check.description, severity=check.default_severity, params=check.params)
        ctx = CheckContext(company_id=company_id, today=today, params=params, baseline=baselines.get, timezone=timezone)
        try:
            with session.begin_nested():
                candidates = check.run(session, ctx)
        except Exception as error:  # a broken check must not stop the others, and must not pass silently
            log.exception("Check %s failed for company %s", check.code, company_id)
            result.failed.append(check.code)
            flag_for_review(session, unit="intel", kind="check_failed", severity="low", company_id=company_id,
                            message=f"The check '{check.title}' could not run: {error}"[:500],
                            dedupe_key=f"intel-check-failed:{check.code}:{company_id}:{today}")
            continue
        result.checks_run += 1
        _apply(session, check, check_id, company_id, candidates, result)
    return result


def _apply(session: Session, check: IntelCheck, check_id: UUID, company_id: UUID, candidates: list[Candidate],
           result: RunResult) -> None:
    open_before = repo.open_ids_for_check(session, check.code, company_id)
    seen: set[str] = set()
    for c in candidates:
        if c.company_id != company_id or c.severity not in SEVERITIES or c.fingerprint in seen:
            if c.fingerprint not in seen:
                log.warning("Check %s returned an unusable candidate %s; ignored", check.code, c.fingerprint)
            continue
        seen.add(c.fingerprint)
        evidence = _evidence(c)
        amount = c.amount.quantize(Decimal("0.01")) if c.amount is not None else None
        row = repo.find_by_fingerprint(session, check.code, c.fingerprint)
        if row is None:
            finding_id = repo.insert_finding(
                session, check_id=check_id, code=check.code, area=check.area, fingerprint=c.fingerprint,
                severity=c.severity, company_id=c.company_id, branch_id=c.branch_id, entity_type=c.entity_type,
                entity_id=c.entity_id, period_start=c.period_start, period_end=c.period_end, value=c.value,
                expected_value=c.expected_value, amount=amount, summary=c.summary, action=c.recommended_action,
                evidence=evidence)
            repo.add_event(session, finding_id, "detected")
            publish(session, Event("finding.created", "intel.finding", finding_id, {
                "check": check.code, "severity": c.severity, "company_id": c.company_id, "branch_id": c.branch_id,
                "summary": c.summary, "amount": amount}))
            result.created += 1
            continue
        reopen = row.status == "resolved"
        repo.refresh_finding(session, row.id, severity=c.severity, value=c.value, expected_value=c.expected_value,
                             amount=amount, summary=c.summary, action=c.recommended_action, evidence=evidence,
                             reopen=reopen)
        if reopen:
            repo.add_event(session, row.id, "reopened", note="The problem is back")
            result.reopened += 1
        elif severity_rank(c.severity) != severity_rank(row.severity):
            repo.add_event(session, row.id, "severity_changed", note=f"{row.severity} -> {c.severity}")
        result.updated += 1
    if check.auto_resolves:
        for fingerprint, finding_id in open_before.items():
            if fingerprint not in seen:
                repo.set_status(session, finding_id, "resolved")
                repo.add_event(session, finding_id, "auto_resolved", note="No longer detected")
                result.resolved += 1
