"""The checks engine: run the checks units supply, turn what they find into findings, keep them in step with reality.

A problem seen again is the same finding (its fingerprint). A finding a check no longer reports is closed by itself
when the check says it can be (a stockout fixed), and kept for a person otherwise (a void on Tuesday). A failing check
never stops the others: it is reported in the exceptions inbox.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from ziira.modules.intel.domain.model import SEVERITIES, Candidate
from ziira.modules.intel.domain.rules import severity_rank
from ziira.modules.intel.public import INTEL_CHECK, CheckContext, IntelCheck
from ziira.modules.intel.repository import findings_repo as repo
from ziira.modules.intel.services import baselines as baseline_service
from ziira.sdk import Event, Session, company_setting, flag_for_review, implementations, publish_many

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
    """Turn a check's candidates into findings. Works in batches (one read of the check's findings, then a few bulk
    writes) because a check can find thousands of things; the effect is the same as handling them one at a time."""
    open_before = repo.open_ids_for_check(session, check.code, company_id)
    existing = repo.existing_by_fingerprint(session, check.code)
    seen: set[str] = set()
    created: list[dict[str, Any]] = []
    refreshed: list[dict[str, Any]] = []
    events: list[tuple[UUID, str, str | None]] = []
    announced: list[Event] = []
    for c in candidates:
        if c.company_id != company_id or c.severity not in SEVERITIES or c.fingerprint in seen:
            if c.fingerprint not in seen:
                log.warning("Check %s returned an unusable candidate %s; ignored", check.code, c.fingerprint)
            continue
        seen.add(c.fingerprint)
        evidence = json.dumps(_evidence(c), default=str)
        amount = c.amount.quantize(Decimal("0.01")) if c.amount is not None else None
        row = existing.get(c.fingerprint)
        if row is None:
            finding_id = uuid4()
            created.append({
                "id": str(finding_id), "ci": str(check_id), "cc": check.code, "ar": check.area, "fp": c.fingerprint,
                "sv": c.severity, "co": str(c.company_id), "br": str(c.branch_id) if c.branch_id else None,
                "et": c.entity_type, "ei": str(c.entity_id) if c.entity_id else None, "ps": c.period_start,
                "pe": c.period_end, "v": c.value, "ev": c.expected_value, "am": amount, "su": c.summary[:1000],
                "ra": c.recommended_action[:1000], "evd": evidence})
            events.append((finding_id, "detected", None))
            announced.append(Event("finding.created", "intel.finding", finding_id, {
                "check": check.code, "severity": c.severity, "company_id": c.company_id, "branch_id": c.branch_id,
                "summary": c.summary, "amount": amount}))
            result.created += 1
            continue
        reopen = row.status == "resolved"
        refreshed.append({"sv": c.severity, "v": c.value, "ev": c.expected_value, "am": amount,
                          "su": c.summary[:1000], "ra": c.recommended_action[:1000], "evd": evidence,
                          "reopen": reopen, "i": str(row.id)})
        if reopen:
            events.append((row.id, "reopened", "The problem is back"))
            result.reopened += 1
        elif severity_rank(c.severity) != severity_rank(row.severity):
            events.append((row.id, "severity_changed", f"{row.severity} -> {c.severity}"))
        result.updated += 1
    repo.insert_findings(session, created)
    repo.refresh_findings(session, refreshed)
    if check.auto_resolves:
        gone = [finding_id for fingerprint, finding_id in open_before.items() if fingerprint not in seen]
        repo.resolve_many(session, gone)
        events += [(finding_id, "auto_resolved", "No longer detected") for finding_id in gone]
        result.resolved += len(gone)
    repo.add_events(session, events)
    publish_many(session, announced)
