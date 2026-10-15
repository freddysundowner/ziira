"""AI-written explanations of findings, and an AI ordering of the most important ones.

The model is given only what the check computed (summary, action, figures, the labels of the records) and may add no
number of its own: a reply whose numbers are not all in those facts is discarded and the deterministic text stays. The
ordering must be exactly a permutation of the findings given; otherwise the deterministic `rank_score` order stays.
Names of people are replaced by labels such as "Employee A" while the provider has them.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.domain.llm import LlmMessage, LlmReply
from ziira.modules.intel.repository import ai_repo, findings_repo
from ziira.modules.intel.services import ai
from ziira.sdk import NotFound, Session, audit_record, tenant_transaction

log = logging.getLogger("ziira.intel.ai")
RANKING_FRESH_HOURS = 12
RANKED_FINDINGS = 12
EXPLANATIONS_PER_RUN = 5
RETRY_HOURS = 6
LANGUAGE_NAMES = {"en": "English", "sw": "Swahili"}

# Kinds of record that are people (or hold their details): their labels are replaced while the provider has them.
PERSON_KINDS = {
    "people.employee": "Employee", "people.employment_terms": "Employee", "people.employee_bank_account": "Employee",
    "people.payslip": "Employee", "people.leave_request": "Employee", "people.attendance": "Employee",
    "kernel.app_user": "Person", "kernel.user_role": "Person", "crm.customer": "Customer",
    "crm.customer_credit_version": "Customer", "crm.activity": "Customer", "purchasing.supplier": "Supplier",
    "purchasing.supplier_bank_account": "Supplier",
}

EXPLAIN_SYSTEM = (
    "You help the owner of a small business understand a flag raised by an automated check. Write 2 to 4 short, plain "
    "sentences in {language}: what was found, why it could matter, and one thing to look at first. Use ONLY numbers "
    "that appear in the FACTS: do not calculate, estimate, round, convert or add any number, and do not mention a "
    "number that is not written in the FACTS. The flag is a question, not an accusation: never blame a person, and say "
    "'could be' rather than stating a cause. Labels such as 'Employee A' or 'Customer B' stand for real people: write "
    "them exactly as given. Reply with the text only.")
RANK_SYSTEM = (
    "You help the owner of a small business decide what to look at first. Below are open findings, each with an id "
    "(F1, F2 ...). Order ALL of them from most to least urgent for the owner, weighing severity, the money at stake "
    "and how long each has been open. Reply with JSON only, no other text: "
    '{"order": [{"id": "F2", "reason": "one short plain sentence"}, ...]}. Use every id exactly once and no other id. '
    "A reason may use only numbers written in the FACTS; do not calculate. Labels such as 'Employee A' stand for real "
    "people: write them exactly as given.")


@dataclass
class Facts:
    """What goes to the provider about a finding, and the numbers in it."""

    text: str
    numbers: list[Decimal]
    names: ai_rules.Pseudonyms


def _evidence(row: Row[Any]) -> dict[str, Any]:
    return dict(row.evidence or {})


def _known_names(session: Session, rows: list[Row[Any]]) -> ai_rules.Pseudonyms:
    """The people a text may name: those in the findings' records, and everyone who has a login."""
    names = ai_rules.Pseudonyms()
    for row in rows:
        for record in _evidence(row).get("records", []):
            kind = PERSON_KINDS.get(str(record.get("type")))
            if kind:
                names.add(str(record.get("label", "")), kind)
    for r in session.execute(text("select full_name from kernel.app_user where full_name is not null "
                                  "order by created_at limit 500")):
        names.add(r.full_name, "Person")
    return names


def _plain(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _money(amount: Decimal | None, currency: str) -> str:
    return f"{currency} {amount:,.2f}" if amount is not None else "none"


def _lines(row: Row[Any], names: ai_rules.Pseudonyms, currency: str, branch: str | None) -> list[str]:
    evidence = _evidence(row)
    lines = [f"Severity: {row.severity}", f"Area: {row.area or 'general'}",
             f"Branch: {branch or 'the whole company'}",
             f"Period: {row.period_start or 'not set'} to {row.period_end or row.period_start or 'not set'}",
             f"Summary: {names.hide(row.summary or '')}",
             f"Recommended action: {names.hide(row.recommended_action or '')}",
             f"Money at stake: {_money(row.amount, currency)}"]
    if row.value is not None:
        found = f"Value found: {_plain(row.value)}"
        if row.expected_value is not None:
            found += f"; expected: {_plain(row.expected_value)}"
        lines.append(found)
    for key, value in (evidence.get("figures") or {}).items():
        lines.append(f"Figure {key}: {names.hide(str(value))}")
    for record in evidence.get("records", []):
        label = names.hide(str(record.get("label", "")))
        lines.append(f"Record ({str(record.get('type', '')).split('.')[-1]}): {label}")
    return lines


def _context(session: Session, row: Row[Any]) -> tuple[str, str | None]:
    currency = str(session.execute(text("select base_currency from kernel.company where id = :c"),
                                   {"c": str(row.company_id)}).scalar() or "")
    branch = session.execute(text("select name from kernel.branch where id = :b"), {"b": str(row.branch_id)}).scalar() \
        if row.branch_id else None
    return currency, branch


def build_facts(session: Session, row: Row[Any]) -> Facts:
    """The facts about one finding, with people's names replaced and personal details scrubbed."""
    names = _known_names(session, [row])
    currency, branch = _context(session, row)
    body = ai_rules.scrub_personal("\n".join(_lines(row, names, currency, branch)))
    return Facts(f"FACTS\n{body}", ai_rules.numbers_in(body), names)


def _check_explanation(facts: Facts) -> Callable[[LlmReply], str | None]:
    checker = ai_rules.FigureChecker(facts.numbers, strict=True)

    def check(reply: LlmReply) -> str | None:
        written = reply.text.strip()
        if not written:
            return "empty reply"
        if reply.stop_reason == "max_tokens":
            return "reply cut short"
        if len(written) > 1500:
            return "reply too long"
        bad = checker.unverified(written)
        return f"figures not in the facts: {', '.join(bad[:5])}" if bad else None

    return check


def explain_finding(tenant_id: UUID, finding_id: UUID, *, user_id: UUID | None, language: str = "en") -> str:
    """Ask the model to explain a finding and keep the answer if its figures all come from the finding. Returns the
    stored text. Raises AiUnavailable, AiFailed or AiRejected (the deterministic text then stays)."""
    lang = language if language in LANGUAGE_NAMES else "en"
    with tenant_transaction(tenant_id) as s:
        row = findings_repo.get_finding(s, finding_id)
        if row is None or row.company_id is None:
            raise NotFound("Finding not found")
        company_id: UUID = row.company_id
        facts = build_facts(s, row)
    try:
        reply = ai.call(tenant_id, company_id=company_id, user_id=user_id, purpose="explain", ref_type="intel.finding",
                        ref_id=finding_id, messages=[LlmMessage("user", facts.text)], tools=[],
                        system=EXPLAIN_SYSTEM.format(language=LANGUAGE_NAMES[lang]), max_tokens=500,
                        check=_check_explanation(facts))
    except (ai.AiFailed, ai.AiRejected):
        with tenant_transaction(tenant_id) as s:
            ai_repo.mark_explanation_tried(s, finding_id)
        raise
    written = facts.names.restore(reply.text.strip())
    with tenant_transaction(tenant_id) as s:
        ai_repo.set_ai_explanation(s, finding_id, written)
        findings_repo.add_event(s, finding_id, "ai_explained", user_id=user_id, channel="ai")
        audit_record(s, "finding.ai_explained", "intel.finding", finding_id, {"language": lang})
    return written


def explain_pending(tenant_id: UUID, company_id: UUID) -> int:
    """Explain a few open findings that have no AI explanation yet (the background job). Stops quietly when the
    assistant is not available. Returns how many were explained."""
    with tenant_transaction(tenant_id) as s:
        state = ai.get_state(s, company_id)
        if state.blocked("explain") or not state.auto_explain:
            return 0
        ids = ai_repo.findings_to_explain(s, company_id, EXPLANATIONS_PER_RUN, RETRY_HOURS)
    done = 0
    for finding_id in ids:
        try:
            explain_finding(tenant_id, finding_id, user_id=None)
            done += 1
        except ai.AiUnavailable:
            break
        except (ai.AiFailed, ai.AiRejected) as error:
            log.info("No AI explanation for finding %s: %s", finding_id, error.message)
    return done


# --------------------------------------------------------------------------- ranking
def rank_company(tenant_id: UUID, company_id: UUID) -> bool:
    """Ask the model to order the company's most pressing open findings and store the order if it is valid. Returns
    True when a new order was stored."""
    with tenant_transaction(tenant_id) as s:
        state = ai.get_state(s, company_id)
        if state.blocked("rank"):
            return False
        rows = ai_repo.top_for_ranking(s, company_id, RANKED_FINDINGS)
        if len(rows) < 3:
            return False                                  # nothing worth reordering
        names = _known_names(s, rows)
        currency = str(s.execute(text("select base_currency from kernel.company where id = :c"),
                                 {"c": str(company_id)}).scalar() or "")
    now = datetime.now(UTC)
    aliases = [f"F{i + 1}" for i in range(len(rows))]
    lines = []
    for alias, r in zip(aliases, rows, strict=True):
        lines.append(f"{alias} | severity {r.severity} | area {r.area or 'general'} | "
                     f"open {(now - r.first_seen_at).days} "
                     f"days | money at stake {_money(r.amount, currency)} | {names.hide(r.summary or '')} | "
                     f"next step: {names.hide(r.recommended_action or '')}")
    body = ai_rules.scrub_personal("FACTS\n" + "\n".join(lines))
    checker = ai_rules.FigureChecker(ai_rules.numbers_in(body), strict=True)
    parsed: list[list[tuple[str, str]]] = []

    def check(reply: LlmReply) -> str | None:
        order = ai_rules.parse_ranking(reply.text, aliases)
        if order is None:
            return "not a complete ordering of the findings given"
        for _, reason in order:
            if checker.unverified(reason):
                return "a reason used figures that are not in the facts"
        parsed.append(order)
        return None

    try:
        reply = ai.call(tenant_id, company_id=company_id, user_id=None, purpose="rank",
                        messages=[LlmMessage("user", body)], tools=[], system=RANK_SYSTEM, max_tokens=900, check=check)
    except (ai.AiFailed, ai.AiRejected) as error:
        log.info("No AI ranking for company %s: %s", company_id, error.message)
        return False
    by_alias = {a: r.id for a, r in zip(aliases, rows, strict=True)}
    items = [{"finding_id": str(by_alias[alias]), "reason": names.restore(reason)} for alias, reason in parsed[-1]]
    with tenant_transaction(tenant_id) as s:
        ai_repo.save_ranking(s, company_id, reply.model, items)
    return True


def fresh_ranking(session: Session, company_id: UUID) -> list[tuple[UUID, str]]:
    """The stored order for a company as (finding id, reason), when it is recent enough, else empty."""
    row = ai_repo.get_ranking(session, company_id)
    if row is None or datetime.now(UTC) - row.computed_at > timedelta(hours=RANKING_FRESH_HOURS):
        return []
    return [(UUID(i["finding_id"]), str(i.get("reason", ""))) for i in row.items]
