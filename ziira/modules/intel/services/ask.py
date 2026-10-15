"""Ask Ziira: a person asks a question in plain words and the model answers by calling the **tools** units offer.

How the answer stays trustworthy:
- The model never sees tables, only tools (`intel.ask_tool`). Each tool filters by the asking person's own permissions
  and branches, returns a bounded result, and takes no free text into a query. A tool the person may not use is not
  offered, and if the model calls one anyway it is refused.
- At most `MAX_TOOL_ROUNDS` rounds of tool calls, a token cap and a time cap; then the model must answer with what
  it has.
- Names of customers, suppliers and employees reach the provider as labels ("Customer A") and are put back in the
  answer.
- Every number in the answer must be in the tool results (or be a total, difference or share of them): otherwise the
  answer is kept but marked "some figures could not be verified" and flagged.
- The conversation is stored with the tools called and the rows used (`intel.ask_session` / `ask_message`).
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.domain.llm import AskTool, LlmMessage, LlmReply, ToolCall, ToolResult, ToolSpec
from ziira.modules.intel.domain.scope import branch_scope
from ziira.modules.intel.domain.tool_params import BadParams, check_params
from ziira.modules.intel.permissions import AI_ASK, AI_MANAGE
from ziira.modules.intel.repository import ai_repo as repo
from ziira.modules.intel.services import ai
from ziira.modules.intel.services.explain import _known_names
from ziira.sdk import (
    Forbidden,
    NotFound,
    RequestContext,
    Session,
    ValidationFailed,
    ZiiraError,
    check_company,
    company_setting,
    company_today,
    implementations,
    tenant_transaction,
)

log = logging.getLogger("ziira.intel.ask")
INTEL_ASK_TOOL = "intel.ask_tool"
MAX_TOOL_ROUNDS = 6
MAX_CALLS_PER_ROUND = 4
TOKEN_CAP = 40_000               # for one question, input and output together
SECONDS_CAP = 75.0               # for one question, between model calls
ANSWER_TOKENS = 1200
MAX_ROWS = 40
MAX_RESULT_CHARS = 14_000
LANGUAGE_NAMES = {"en": "English", "sw": "Swahili"}
NOTE = {"en": "Some figures could not be verified against your data.",
        "sw": "Baadhi ya namba hazikuweza kuthibitishwa dhidi ya data yako."}
GAVE_UP = {"en": "I could not finish answering that with the information available. Try asking in a narrower way.",
           "sw": "Sikuweza kukamilisha jibu kwa taarifa zilizopo. Jaribu kuuliza kwa upana mdogo zaidi."}
PERSON_FIELD_KINDS = (("customer", "Customer"), ("supplier", "Supplier"), ("employee", "Employee"))

SYSTEM = (
    "You are Ziira's assistant for the business '{company}'. Today is {today} (time zone {zone}); amounts are in "
    "{currency}. Answer the question using ONLY the tools provided: never use your own knowledge for any figure. Write "
    "every number exactly as it appears in a tool result: do not round, abbreviate or estimate; you may add or "
    "subtract "
    "figures or give a percentage when it helps, naming the figures you used. If the tools cannot answer, or return "
    "nothing, say so plainly and do not guess. If a result says it is truncated, say the list is partial. The person "
    "asking can see only these branches (use these ids for branch_id): {branches}. Names such as 'Customer A' stand "
    "for "
    "real people: write them exactly as given. Reply in {language}, in a few short sentences or a short list. If the "
    "question is ambiguous, ask one short question back.")


@dataclass
class Answer:
    session_id: UUID
    message_id: UUID
    answer: str
    sources: list[dict[str, Any]]
    flagged: bool = False
    flag_reason: str | None = None
    capped: str | None = None
    ai_generated: bool = True


@dataclass
class _Run:
    """Everything gathered while the model works: what the tools returned (to check the answer against) and used."""

    names: ai_rules.Pseudonyms
    facts: list[Decimal] = field(default_factory=list)
    groups: list[list[Decimal]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    capped: str | None = None


# --------------------------------------------------------------------------- tools
def available_tools(session: Session, context: RequestContext) -> dict[str, AskTool]:
    """The tools of enabled units that this person may use somewhere."""
    return {t.name: t for t in implementations(session, INTEL_ASK_TOOL)
            if any(context.has_anywhere(p) for p in t.permissions)}


def _strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items() if not (k == "id" or k.endswith("_id"))}
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def _decimal(value: Any) -> Decimal | None:
    """A cell as a number if it is one (a number, or a string of digits such as "1250.00"), else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return abs(Decimal(str(value)))
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value):
        return abs(Decimal(value))
    return None


def _collect_figures(result: dict[str, Any], run: _Run) -> None:
    """Remember the numbers a tool returned, and each column of its rows (so a total can be recomputed)."""
    cleaned = _strip_ids(result)
    run.facts += ai_rules.numbers_in(json.dumps(cleaned, default=str))
    for value in cleaned.values():
        if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
            run.facts.append(Decimal(len(value)))
            columns: dict[str, list[Decimal]] = {}
            for row in value:
                for name, cell in row.items():
                    number = _decimal(cell)
                    if number is not None:
                        columns.setdefault(name, []).append(number)
            run.groups += [c for c in columns.values() if len(c) > 1]


def _bound(result: dict[str, Any]) -> dict[str, Any]:
    """Keep a result small: no more than MAX_ROWS rows in a list, and no more than MAX_RESULT_CHARS in all."""
    out: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, list) and len(value) > MAX_ROWS:
            out[key] = value[:MAX_ROWS]
            out["truncated"] = True
        else:
            out[key] = value
    while len(json.dumps(out, default=str)) > MAX_RESULT_CHARS:
        lists = [k for k, v in out.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            break
        biggest = max(lists, key=lambda k: len(out[k]))
        out[biggest] = out[biggest][: max(len(out[biggest]) // 2, 1)]
        out["truncated"] = True
    return out


def _person_fields(tool: AskTool) -> dict[str, str]:
    kinds = {}
    for name in tool.personal_fields:
        kinds[name] = next((kind for hint, kind in PERSON_FIELD_KINDS if hint in name), "Person")
    return kinds


def _run_tool(tenant_id: UUID, context: RequestContext, company_id: UUID, tools: dict[str, AskTool], call: ToolCall,
              run: _Run) -> ToolResult:
    """Run one tool the model asked for, as the person asking, and turn the outcome into what the model reads."""
    entry: dict[str, Any] = {"tool": call.name, "params": ai_rules.scrub_value(call.arguments)}
    run.tools_used.append(entry)
    tool = tools.get(call.name)
    if tool is None:
        entry["status"] = "refused"
        return ToolResult(call.id, "This tool does not exist or you are not allowed to use it.", True)
    try:
        params = check_params(tool.parameters, call.arguments)
        entry["params"] = dict(params)
        with tenant_transaction(tenant_id) as s:
            result = tool.run(s, context, {**params, "company_id": str(company_id)})
    except BadParams as error:
        entry["status"] = "bad_params"
        return ToolResult(call.id, f"Invalid arguments: {error}", True)
    except ZiiraError as error:
        entry["status"] = "refused"
        return ToolResult(call.id, f"Not possible: {error.message}", True)
    except Exception:  # noqa: BLE001 - a tool bug must not take the conversation down
        log.exception("Ask tool %s failed", call.name)
        entry["status"] = "failed"
        return ToolResult(call.id, "The tool failed. Do not guess; tell the person it could not be answered.", True)
    result = _bound(result)
    entry["status"] = "ok"
    _collect_figures(result, run)
    rows = next((v for v in result.values() if isinstance(v, list)), [])
    entry["rows"] = len(rows)
    run.sources.append({"tool": call.name, "params": dict(params), "result": result})
    shown = ai_rules.scrub_value(run.names.hide_fields(result, _person_fields(tool)))
    return ToolResult(call.id, json.dumps(shown, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- the question
def _pick_company(session: Session, context: RequestContext, company_id: UUID | None) -> UUID:
    allowed = context.companies_with(AI_ASK)
    if company_id is not None:
        check_company(session, company_id)
        if allowed is not None and company_id not in allowed:
            raise Forbidden(f"You do not have permission '{AI_ASK}' here")
        return company_id
    from sqlalchemy import text

    ids: list[UUID] = [r.id for r in session.execute(text("select id from kernel.company order by name, id"))]
    ids = [i for i in ids if allowed is None or i in allowed]
    if len(ids) != 1:
        raise ValidationFailed("Say which company the question is about")
    return ids[0]


def _branch_lines(session: Session, context: RequestContext, company_id: UUID) -> str:
    from sqlalchemy import text

    scope = branch_scope(context, (AI_ASK,), company_id)
    rows = session.execute(text("select id, name from kernel.branch where company_id = :c order by name"),
                           {"c": str(company_id)}).all()
    shown = [f"{r.name} = {r.id}" for r in rows if scope.allows(r.id)]
    return "; ".join(shown) or "none"


def ask(context: RequestContext, question: str, *, company_id: UUID | None = None, session_id: UUID | None = None,
        language: str = "en") -> Answer:
    """Answer a question for the person in `context`. Raises AiUnavailable when the assistant is off, over budget or
    not consented to; AiFailed when the provider cannot answer."""
    from sqlalchemy import text

    tenant_id = context.tenant_id
    lang = language if language in LANGUAGE_NAMES else "en"
    question = question.strip()
    if not question or context.user_id is None:
        raise ValidationFailed("Ask a question")
    with tenant_transaction(tenant_id) as s:
        company = _pick_company(s, context, company_id)
        _, blocked = ai.gate(s, company, "ask", context.user_id)
        tools = {} if blocked else available_tools(s, context)
        if session_id is not None:
            existing = repo.get_session(s, session_id)
            if existing is None or existing.user_id != context.user_id or existing.company_id != company:
                raise NotFound("Conversation not found")
        info = s.execute(text("select name, base_currency from kernel.company where id = :c"),
                         {"c": str(company)}).one()
        today: date = company_today(s, company)
        zone = str(company_setting(s, company, "timezone"))
        branches = _branch_lines(s, context, company)
        run = _Run(names=_known_names(s, []))
    if blocked:
        raise ai.AiUnavailable(blocked)
    system = SYSTEM.format(company=info.name, today=today.isoformat(), zone=zone, currency=info.base_currency,
                           branches=branches, language=LANGUAGE_NAMES[lang])
    specs = [ToolSpec(t.name, t.description, t.parameters) for t in tools.values()]
    messages = [LlmMessage("user", ai_rules.scrub_personal(question))]
    run.facts += [*ai_rules.numbers_in(question), Decimal(today.year), Decimal(today.month), Decimal(today.day)]
    final = _converse(tenant_id, context, company, tools, specs, system, messages, run)
    text_out = run.names.restore(final.strip()) if final.strip() else GAVE_UP[lang]
    flagged, reason = False, None
    if not final.strip():
        flagged, reason = True, run.capped or "no answer"
    else:
        bad = ai_rules.FigureChecker(run.facts, run.groups).unverified(text_out)
        if bad:
            text_out = f"{text_out}\n\n{NOTE[lang]}"
            flagged, reason = True, f"figures not found in the data: {', '.join(bad[:8])}"
    with tenant_transaction(tenant_id) as s:
        sid = session_id or repo.create_session(s, company, context.user_id, question)
        repo.add_message(s, sid, "user", question)
        mid = repo.add_message(s, sid, "assistant", text_out, sources=run.sources, tools_used=run.tools_used,
                               flagged=flagged, flag_reason=reason, input_tokens=run.tokens_in,
                               output_tokens=run.tokens_out)
        repo.touch_session(s, sid)
    return Answer(sid, mid, text_out, run.sources, flagged, reason, run.capped)


def _converse(tenant_id: UUID, context: RequestContext, company: UUID, tools: dict[str, AskTool],
              specs: list[ToolSpec], system: str, messages: list[LlmMessage], run: _Run) -> str:
    """The loop: ask the model; run the tools it names; give it the results; until it answers or a cap is reached."""
    started = time.monotonic()
    rounds = 0
    while True:
        capped = ("tool rounds" if rounds >= MAX_TOOL_ROUNDS
                  else "tokens" if run.tokens_in + run.tokens_out >= TOKEN_CAP
                  else "time" if time.monotonic() - started > SECONDS_CAP else None)
        last = capped is not None
        if capped:
            run.capped = capped
        reply: LlmReply = ai.call(
            tenant_id, company_id=company, user_id=context.user_id, purpose="ask", messages=messages,
            tools=[] if last else specs, system=system, max_tokens=ANSWER_TOKENS, ref_type="intel.ask",
            tools_called=[{"name": e["tool"], "status": e.get("status")} for e in run.tools_used])
        run.tokens_in += reply.usage.input_tokens
        run.tokens_out += reply.usage.output_tokens
        if last or not reply.tool_calls:
            return reply.text
        rounds += 1
        calls = reply.tool_calls
        results = [_run_tool(tenant_id, context, company, tools, c, run) for c in calls[:MAX_CALLS_PER_ROUND]]
        results += [ToolResult(c.id, "Too many tools at once; ask for fewer.", True)
                    for c in calls[MAX_CALLS_PER_ROUND:]]
        messages.append(LlmMessage("assistant", reply.text, tool_calls=tuple(calls)))
        messages.append(LlmMessage("user", tool_results=tuple(results)))


# --------------------------------------------------------------------------- reading conversations back
def list_conversations(context: RequestContext, *, everyone: bool, company_id: UUID | None, limit: int,
                       offset: int) -> list[Any]:
    """The person's own conversations; with `everyone`, those of all people in the company (holders of ai.manage)."""
    with tenant_transaction(context.tenant_id) as s:
        if everyone:
            if company_id is None:
                raise ValidationFailed("Say which company")
            context.require(AI_MANAGE, company_id=company_id)
            return repo.list_sessions(s, user_id=None, company_id=company_id, limit=limit, offset=offset)
        return repo.list_sessions(s, user_id=context.user_id, company_id=company_id, limit=limit, offset=offset)


def get_conversation(session: Session, context: RequestContext, session_id: UUID) -> tuple[Any, list[Any]]:
    """A conversation with its messages: its owner may read it, and so may a holder of ai.manage for the company."""
    found = repo.get_session(session, session_id)
    if found is None or not (found.user_id == context.user_id
                             or context.can(AI_MANAGE, company_id=found.company_id)):
        raise NotFound("Conversation not found")
    return found, repo.messages_of(session, session_id)
