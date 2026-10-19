"""Ask Ziira as a chat: the same work as `ask.ask`, told as events while it happens (Server-Sent Events).

Events, in this order: `status` (plain words about what is being done, as often as it changes), then the answer as
`text` events (one sentence or list line each), `sources` (the rows the answer rests on), and `done` (with the
conversation id); or `error` (a reason code and plain words) at any point, and nothing after it.

Nothing is released before it has been checked: the model's whole reply is verified against the tool results first
(`ask_steps(strict=True)`: a sentence holding a figure that is not in the data is left out), and only then released
sentence by sentence with short pauses. The provider is called, as always, with no database transaction open.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from ziira.modules.intel.domain.chat_text import split_chunks
from ziira.modules.intel.services import ai, ask
from ziira.sdk import RequestContext, ZiiraError

log = logging.getLogger("ziira.intel.ask")
PAUSE_SECONDS = 0.05                     # between released sentences (the screen types each one out over a moment)

PLAIN_ERRORS: dict[str, dict[str, str]] = {
    "not_enabled": {"en": "The assistant is switched off for this business. An Owner can switch it on in Settings.",
                    "sw": "Msaidizi amezimwa kwa biashara hii. Mmiliki anaweza kumwasha kwenye Mipangilio."},
    "no_consent": {"en": "The assistant needs an Owner's consent first. An Owner can give it in Settings.",
                   "sw": "Msaidizi anahitaji ridhaa ya Mmiliki kwanza. Mmiliki anaweza kuitoa kwenye Mipangilio."},
    "purpose_off": {"en": "Questions to the assistant are switched off in Settings.",
                    "sw": "Maswali kwa msaidizi yamezimwa kwenye Mipangilio."},
    "budget": {"en": "This month's allowance for the assistant has been used up.",
               "sw": "Kikomo cha msaidizi cha mwezi huu kimekwisha."},
    "spend_cap": {"en": "The assistant is paused for now. Please try again later.",
                  "sw": "Msaidizi amesimamishwa kwa sasa. Tafadhali jaribu tena baadaye."},
    "not_configured": {"en": "The assistant is not set up yet.", "sw": "Msaidizi hajawekwa bado."},
    "terms_unconfirmed": {"en": "The assistant is not set up yet.", "sw": "Msaidizi hajawekwa bado."},
    "provider_failed": {"en": "I could not reach the assistant just now. Nothing was changed. Please try again.",
                        "sw": "Sikuweza kumfikia msaidizi sasa hivi. Hakuna kilichobadilishwa. Tafadhali jaribu tena."},
    "failed": {"en": "Something went wrong. Please try again.", "sw": "Kuna tatizo. Tafadhali jaribu tena."},
}


def _error(reason: str, lang: str, message: str | None = None) -> dict[str, Any]:
    texts = PLAIN_ERRORS.get(reason, PLAIN_ERRORS["failed"])
    return {"event": "error", "data": {"reason": reason, "message": message or texts.get(lang, texts["en"])}}


def stream(context: RequestContext, question: str, *, company_id: UUID | None, session_id: UUID | None,
           language: str, pause: float | None = None) -> Iterator[dict[str, Any]]:
    """The events of one question: dicts `{"event": name, "data": {...}}`. Never raises (a failure is an `error` event).
    Closing the generator stops the work at the next step."""
    lang = language if language in ask.LANGUAGE_NAMES else "en"
    steps = ask.ask_steps(context, question, company_id=company_id, session_id=session_id, language=lang, strict=True)
    answer: ask.Answer
    try:
        while True:
            kind, words = next(steps)
            yield {"event": kind, "data": {"text": words}}
    except StopIteration as done:
        answer = done.value
    except ai.AiUnavailable as error:
        yield _error(error.reason, lang)
        return
    except ai.AiFailed:
        yield _error("provider_failed", lang)
        return
    except ZiiraError as error:
        yield _error(error.code, lang, error.message)
        return
    except Exception:  # noqa: BLE001 - the person gets plain words, the log gets the trace
        log.exception("Ask Ziira stream failed")
        yield _error("failed", lang)
        return
    wait = PAUSE_SECONDS if pause is None else pause
    for chunk in split_chunks(answer.answer):
        yield {"event": "text", "data": {"text": chunk}}
        if wait:
            time.sleep(wait)
    yield {"event": "sources", "data": {"sources": answer.sources}}      # the API layer decides how they are shown
    yield {"event": "done", "data": {"session_id": str(answer.session_id), "message_id": str(answer.message_id),
                                     "flagged": answer.flagged, "withheld": answer.withheld,
                                     "capped": answer.capped}}
