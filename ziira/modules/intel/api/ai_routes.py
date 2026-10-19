"""HTTP endpoints of the AI layer: whether the assistant is on, its settings and consent, its usage and call log, and
Ask Ziira with the person's own conversations."""

import asyncio
import contextvars
import json
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ziira.modules.intel.api.schemas import (
    AiCallOut,
    AiConsentOut,
    AiSettingsIn,
    AiSettingsOut,
    AiStatusOut,
    AiUsageOut,
    AskAnswerOut,
    AskConversationOut,
    AskMessageOut,
    AskQuestionIn,
    AskSessionOut,
    AskSourceOut,
)
from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.permissions import AI_ASK, AI_MANAGE, FINDINGS_VIEW
from ziira.modules.intel.repository import ai_repo
from ziira.modules.intel.services import ai, ai_admin, ask, ask_stream
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    RequestContext,
    Session,
    check_company,
    page_limit,
    page_offset,
    request_context,
    require_permission,
)

router = APIRouter()
MANAGE = [Depends(require_permission(AI_MANAGE))]


def _anyone_who_uses_ai(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    if not any(ctx.has_anywhere(p) for p in (AI_ASK, AI_MANAGE, FINDINGS_VIEW)):
        raise Forbidden("You do not have permission to use the AI assistant")
    return ctx


def source_out(source: dict[str, Any]) -> AskSourceOut:
    """A stored source ({tool, params, result}) as the API shows it: the rows used, and the other figures."""
    result = dict(source.get("result") or {})
    key = next((k for k, v in result.items() if isinstance(v, list)), None)
    rows = [r for r in result.pop(key) if isinstance(r, dict)] if key else []
    return AskSourceOut(tool=source["tool"], params=source.get("params") or {}, rows=rows, summary=result)


def _settings_out(state: ai.AiState, consents: list[Any], usage: list[Any]) -> AiSettingsOut:
    return AiSettingsOut(
        company_id=state.company_id, enabled=state.enabled and state.consent_valid, consent_valid=state.consent_valid,
        explanations=state.explanations, auto_explain=state.auto_explain, ask=state.ask,
        monthly_token_limit=state.token_limit, tokens_used=state.tokens_used, calls=state.calls,
        provider=state.provider, model=state.model, configured=state.configured, terms_confirmed=state.terms_ok,
        consent_version=ai_rules.CONSENT_VERSION, consent_text=ai_admin.consent_texts(state),
        provider_label=state.provider_label,
        consents=[AiConsentOut.model_validate(c, from_attributes=True) for c in consents],
        usage=[AiUsageOut.model_validate(u, from_attributes=True) for u in usage],
        unavailable_reason=state.blocked("ask") if state.enabled else "not_enabled")


@router.get("/ai/status", response_model=AiStatusOut)
def get_ai_status(company_id: UUID, ctx: RequestContext = Depends(_anyone_who_uses_ai),
                  session: Session = DB_SESSION) -> object:
    """Whether the assistant can be used for the company now (for screens deciding what to show)."""
    check_company(session, company_id)
    state = ai.get_state(session, company_id)
    return AiStatusOut(company_id=company_id, ask_available=state.blocked("ask") is None and ctx.has_anywhere(AI_ASK),
                       explanations_available=state.blocked("explain") is None,
                       reason=state.blocked("ask") or state.blocked("explain"))


@router.get("/ai/settings", response_model=AiSettingsOut, dependencies=MANAGE)
def get_ai_settings(company_id: UUID, session: Session = DB_SESSION) -> object:
    """The assistant's settings, consent history and usage for the company (Owners)."""
    return _settings_out(*ai_admin.settings_view(session, company_id))


@router.put("/ai/settings", response_model=AiSettingsOut, dependencies=MANAGE)
def put_ai_settings(body: AiSettingsIn, session: Session = DB_SESSION) -> object:
    """Switch the assistant on (with the consent text accepted) or off; set what it may do and its monthly budget."""
    ai_admin.update(session, body.company_id, enabled=body.enabled, accept_version=body.accept_version,
                    language=body.language, explanations=body.explanations, auto_explain=body.auto_explain,
                    ask=body.ask, monthly_token_limit=body.monthly_token_limit)
    return _settings_out(*ai_admin.settings_view(session, body.company_id))


@router.get("/ai/calls", response_model=list[AiCallOut], dependencies=MANAGE)
def get_ai_calls(company_id: UUID, limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    """The log of every call to the AI provider for the company: who, why, tools, tokens, outcome (Owners)."""
    ai_admin.settings_view(session, company_id)                 # checks the company and the permission
    rows = ai_repo.list_calls(session, company_id, limit, offset)
    return [AiCallOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/ask", response_model=AskAnswerOut, dependencies=[Depends(require_permission(AI_ASK))])
def post_ask(body: AskQuestionIn, ctx: RequestContext = Depends(request_context)) -> object:
    """Ask a question about the business in plain words (English or Swahili). The answer is written by an AI from the
    results of defined queries over what you may see; `sources` lists what it is based on."""
    answer = ask.ask(ctx, body.question, company_id=body.company_id, session_id=body.session_id,
                     language=body.language)
    return AskAnswerOut(session_id=answer.session_id, message_id=answer.message_id, answer=answer.answer,
                        sources=[source_out(s) for s in answer.sources], flagged=answer.flagged,
                        flag_reason=answer.flag_reason, capped=answer.capped)


def _pump(events: Iterator[dict[str, Any]], loop: asyncio.AbstractEventLoop,
          queue: "asyncio.Queue[dict[str, Any] | None]", stop: threading.Event) -> None:
    """Runs in a worker thread: moves the events of a question to the response, and stops when the reader has gone."""
    try:
        for event in events:
            if stop.is_set():
                break
            loop.call_soon_threadsafe(queue.put_nowait, event)
    finally:
        close = getattr(events, "close", None)
        if close:
            close()
        loop.call_soon_threadsafe(queue.put_nowait, None)


def _sse(event: dict[str, Any]) -> bytes:
    data = event["data"]
    if event["event"] == "sources":
        data = {"sources": [source_out(s).model_dump(mode="json") for s in data["sources"]]}
    return f"event: {event['event']}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n".encode()


@router.post("/ask/stream", dependencies=[Depends(require_permission(AI_ASK))],
             responses={200: {"content": {"text/event-stream": {}}, "description": (
                 "Server-Sent Events: `status` {text} while it works, `text` {text} for each sentence of the answer, "
                 "`sources` {sources}, then `done` {session_id, message_id, flagged, withheld, capped}; or `error` "
                 "{reason, message}.")}})
async def post_ask_stream(body: AskQuestionIn, ctx: RequestContext = Depends(request_context)) -> StreamingResponse:
    """Ask a question as a chat: the same checks and the same answer as `/ask`, told as events while the work happens.
    Closing the connection stops the question at its next step."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    stop = threading.Event()
    events = ask_stream.stream(ctx, body.question, company_id=body.company_id, session_id=body.session_id,
                               language=body.language)
    loop.run_in_executor(None, contextvars.copy_context().run, _pump, events, loop, queue, stop)

    async def body_iter() -> AsyncIterator[bytes]:
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            stop.set()

    return StreamingResponse(body_iter(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/ask/sessions", response_model=list[AskSessionOut], dependencies=[Depends(require_permission(AI_ASK))])
def get_ask_sessions(company_id: UUID | None = None, everyone: bool = False, limit: int = page_limit(30),
                     offset: int = page_offset(), ctx: RequestContext = Depends(request_context)) -> object:
    """Your own conversations with Ask Ziira; with `everyone`, everyone's in the company (Owners, for audit)."""
    return [AskSessionOut.model_validate(r, from_attributes=True)
            for r in ask.list_conversations(ctx, everyone=everyone, company_id=company_id, limit=limit, offset=offset)]


@router.get("/ask/sessions/{session_id}", response_model=AskConversationOut)
def get_ask_session(session_id: UUID, ctx: RequestContext = Depends(_anyone_who_uses_ai),
                    session: Session = DB_SESSION) -> object:
    """One conversation with its questions, answers and the sources used. Yours, or any in the company for Owners."""
    found, messages = ask.get_conversation(session, ctx, session_id)
    return AskConversationOut(
        **AskSessionOut.model_validate(found, from_attributes=True).model_dump(),
        messages=[AskMessageOut(id=m.id, created_at=m.created_at, role=m.role, content=m.content,
                                sources=[source_out(s) for s in m.sources], tools_used=m.tools_used, flagged=m.flagged,
                                flag_reason=m.flag_reason, ai_generated=m.role == "assistant") for m in messages])
