"""What the chat bot says. The same checked answers as the website assistant (`kernel/site_assistant.py`: the site's
knowledge file and the live public plans, figures checked, one provider, the same spend ceiling), made fit for a phone
screen: short paragraphs, no markup, plain addresses, the person's language, a welcome with up to three reply buttons.

Pure in the sense that matters here: `compose` reads nothing about a person from the database and writes nothing; the
caller (`chat_inbound.py`) passes in what it knows (history, language, whether a welcome is due) and stores the result.
That is what lets a slow model call be abandoned and redone later without a second hand-off or a second history line.

The bot never says it is a person, never asks for passwords, card numbers or ID numbers, and says so when a sender
shares personal data. It sends nothing on its own: it only ever answers a message that was just sent to it.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ziira.kernel import site_assistant
from ziira.kernel.platform import behaviour
from ziira.kernel.platform.chat_channel import BUTTON_BODY_MAX, BUTTON_TITLE_MAX, TEXT_MAX, ChatButton

MAX_QUESTION = 500
STOP_WORDS = frozenset(["STOP", "UNSUBSCRIBE", "ACHA", "SIMAMISHA"])
START_WORDS = frozenset(["START", "UNSTOP", "ANZA", "JIUNGE"])
GREETINGS = frozenset(
    [
        "hi",
        "hello",
        "hey",
        "hallo",
        "hola",
        "habari",
        "jambo",
        "mambo",
        "sasa",
        "niaje",
        "vipi",
        "salaam",
        "salama",
        "start",
        "menu",
        "help",
        "msaada",
        "good",
        "morning",
        "afternoon",
        "evening",
        "asubuhi",
        "mchana",
        "jioni",
        "karibu",
    ]
)
HUMAN_WORDS = frozenset(["human", "agent", "representative", "person", "mtu", "binadamu", "mfanyakazi"])
SW_MARKERS = frozenset(
    [
        "habari",
        "jambo",
        "bei",
        "gharama",
        "ninataka",
        "nataka",
        "naomba",
        "jinsi",
        "kujisajili",
        "kujiandikisha",
        "biashara",
        "duka",
        "msaada",
        "asante",
        "tafadhali",
        "kiasi",
        "gani",
        "unaweza",
        "mimi",
        "yako",
        "wenu",
        "huduma",
        "malipo",
        "mfumo",
        "hisa",
        "mauzo",
        "ripoti",
        "wapi",
        "lini",
        "nini",
        "nani",
        "sawa",
        "ndiyo",
        "hapana",
        "karibu",
        "bure",
        "ni",
        "na",
        "kwa",
    ]
)
EN_MARKERS = frozenset(
    [
        "the",
        "is",
        "are",
        "what",
        "how",
        "much",
        "price",
        "prices",
        "cost",
        "do",
        "does",
        "can",
        "you",
        "your",
        "want",
        "need",
        "sign",
        "plan",
        "plans",
        "free",
        "trial",
        "please",
        "thanks",
        "which",
        "who",
        "where",
        "when",
        "why",
    ]
)

BUTTON_IDS = ("see_prices", "how_signup", "talk_person")
TITLES = {
    "en": {"see_prices": "See prices", "how_signup": "How to sign up", "talk_person": "Talk to a person"},
    "sw": {"see_prices": "Angalia bei", "how_signup": "Jinsi ya kujisajili", "talk_person": "Ongea na mtu"},
}
CANNED_QUESTIONS = {
    "en": {
        "see_prices": "How much does it cost? What are the plans and prices?",
        "how_signup": "How do I get started and sign up?",
    },
    "sw": {"see_prices": "Bei ni kiasi gani? Mipango na bei ni zipi?", "how_signup": "Ninaanzaje na kujisajili?"},
}
SAY: dict[str, dict[str, str]] = {
    "welcome": {
        "en": "Hi, I am Ziira's automated assistant, not a person. Ask me what Ziira does, what it costs or how to "
        "sign up. I will never ask for passwords, card numbers or ID numbers. Reply STOP to stop messages.",
        "sw": "Habari, mimi ni msaidizi wa kiotomatiki wa Ziira, si mtu. Niulize Ziira inafanya nini, bei yake au "
        "jinsi ya kujisajili. Sitaomba kamwe nywila, namba za kadi wala za kitambulisho. Jibu STOP kusimamisha "
        "ujumbe.",
    },
    "handoff": {
        "en": "I have passed your request to the Ziira team. A person will write back to you here.",
        "sw": "Nimewasilisha ombi lako kwa timu ya Ziira. Mtu atakujibu hapa hapa.",
    },
    "handoff_again": {
        "en": "Your request is already with the Ziira team. A person will write back to you here.",
        "sw": "Ombi lako tayari liko kwa timu ya Ziira. Mtu atakujibu hapa hapa.",
    },
    "off_hours": {
        "en": "The Ziira team is away right now. I have passed your request on and a person will write back when the "
        "team is back.",
        "sw": "Timu ya Ziira haipo kwa sasa. Nimewasilisha ombi lako na mtu atakujibu timu itakaporudi.",
    },
    "unsupported": {
        "en": "I can only read text messages. Please type your question.",
        "sw": "Ninaweza kusoma ujumbe wa maandishi tu. Tafadhali andika swali lako.",
    },
    "opt_out": {
        "en": "Done. We will not message you unless you write to us first. Reply START to chat again.",
        "sw": "Sawa. Hatutakutumia ujumbe isipokuwa uandike wewe kwanza. Jibu START kuanza tena.",
    },
    "opt_in": {
        "en": "Welcome back. Ask me anything about Ziira.",
        "sw": "Karibu tena. Niulize chochote kuhusu Ziira.",
    },
    "slow": {
        "en": "You are writing very quickly. Please wait a little before sending more.",
        "sw": "Unaandika haraka sana. Tafadhali subiri kidogo kabla ya kutuma zaidi.",
    },
    "more": {"en": "More", "sw": "Zaidi"},
}


@dataclass(frozen=True)
class BotReply:
    text: str
    buttons: tuple[ChatButton, ...] = ()
    outcome: str = "answered"
    action: str | None = None  # opt_out | opt_in | handoff: the caller stores it
    lang: str = "en"
    silent: bool = False


@dataclass(frozen=True)
class BotTexts:
    """What the owner may change (all optional: empty means the built-in text in the person's language)."""

    welcome: str = ""
    handoff: str = ""
    off_hours: str = ""
    language: str = "auto"  # auto | en | sw
    hours_start: str = ""  # HH:MM, empty = always open
    hours_end: str = ""
    hours_timezone: str = "UTC"


def say(key: str, lang: str) -> str:
    return SAY[key].get(lang, SAY[key]["en"])


def mask_number(digits: str) -> str:
    """+123…789: enough to recognise a conversation, not enough to ring anyone."""
    if len(digits) < 7:
        return "…" + digits[-2:]
    return f"+{digits[:3]}…{digits[-3:]}"


def detect_language(message: str, fallback: str | None = None) -> str:
    """English or Swahili by the words used; the last language the person used (or English) when it cannot tell."""
    found = _tokens(message)
    sw = sum(1 for w in found if w in SW_MARKERS)
    en = sum(1 for w in found if w in EN_MARKERS)
    if sw and sw >= en:
        return "sw"
    if en:
        return "en"
    return fallback if fallback in ("en", "sw") else "en"


def _tokens(message: str) -> list[str]:
    return re.findall(r"[a-z']+", message.lower())


def _buttons(lang: str, *ids: str) -> tuple[ChatButton, ...]:
    return tuple(ChatButton(i, TITLES.get(lang, TITLES["en"])[i][:BUTTON_TITLE_MAX]) for i in ids)


def _with_buttons(body: str, buttons: tuple[ChatButton, ...]) -> tuple[str, tuple[ChatButton, ...]]:
    """Buttons ride along only when the body fits what a button message may carry."""
    return body, (buttons if len(body) <= BUTTON_BODY_MAX else ())


def is_off_hours(texts: BotTexts, now: datetime | None = None) -> bool:
    """True when opening hours are set and it is outside them (Monday to Friday, in the owner's time zone)."""
    if not (texts.hours_start and texts.hours_end):
        return False
    try:
        zone = ZoneInfo(texts.hours_timezone or "UTC")
    except ZoneInfoNotFoundError:
        return False
    moment = (now or datetime.now(zone)).astimezone(zone)
    if moment.weekday() >= 5:
        return True
    clock = moment.strftime("%H:%M")
    return not (texts.hours_start <= clock < texts.hours_end)


def _clean_word(value: str) -> str:
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE).upper()


def site_base() -> str:
    return str(behaviour.get("public.site_url") or "").rstrip("/")


def address_of(url: str) -> str | None:
    """A page of the knowledge as an address a phone can open (None when there is no site address to put in front)."""
    if url.startswith(("http://", "https://")):
        return url
    base = site_base()
    return f"{base}/{url.lstrip('/')}" if base and url.startswith("/") else None


def render(lines: list[str], links: list[dict[str, str]], lang: str) -> str:
    """Checked lines as short paragraphs (sentences joined, list lines kept apart), then up to two pages as plain
    addresses."""
    blocks: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    for line in lines:
        if line.startswith("- "):
            if paragraph:
                blocks.append(" ".join(paragraph))
                paragraph = []
            bullets.append(line)
        else:
            if bullets:
                blocks.append("\n".join(bullets))
                bullets = []
            paragraph.append(line)
            if len(" ".join(paragraph)) > 220:
                blocks.append(" ".join(paragraph))
                paragraph = []
    if paragraph:
        blocks.append(" ".join(paragraph))
    if bullets:
        blocks.append("\n".join(bullets))
    pages = [f"{link['title']}: {a}" for link in links if (a := address_of(link["href"]))][:2]
    if pages:
        blocks.append(say("more", lang) + ":\n" + "\n".join(pages))
    return "\n\n".join(blocks)[:TEXT_MAX].strip()


def _greeting_only(message: str) -> bool:
    found = _tokens(message)
    return not found or all(w in GREETINGS for w in found)


def compose(
    kind: str,
    text: str,
    button_id: str | None,
    *,
    texts: BotTexts,
    history: list[tuple[str, str]],
    last_lang: str | None,
    first_contact: bool,
) -> BotReply:
    """The bot's reply to one message. Never raises: a provider failure is a short apology, never silence."""
    forced = texts.language if texts.language in ("en", "sw") else None
    lang = forced or detect_language(text, last_lang)
    if button_id in BUTTON_IDS:
        lang = forced or last_lang or lang
    if kind not in ("text", "button"):
        return BotReply(say("unsupported", lang), outcome="unsupported", lang=lang)
    cleaned = site_assistant.clean_input(text)[:MAX_QUESTION]
    word = _clean_word(cleaned)
    if word in STOP_WORDS and " " not in cleaned.strip():
        return BotReply(say("opt_out", lang), outcome="opted_out", action="opt_out", lang=lang)
    if word in START_WORDS and " " not in cleaned.strip():
        return BotReply(say("opt_in", lang), outcome="answered", action="opt_in", lang=lang)
    if button_id == "talk_person" or _asks_for_a_person(cleaned):
        return _handoff(texts, lang)
    if button_id in CANNED_QUESTIONS.get(lang, {}):
        cleaned = CANNED_QUESTIONS[lang][button_id]
    elif not cleaned or _greeting_only(cleaned):
        body, buttons = _with_buttons(texts.welcome.strip() or say("welcome", lang), _buttons(lang, *BUTTON_IDS))
        return BotReply(body, buttons, outcome="welcome", lang=lang)
    try:
        answer = site_assistant.answer(cleaned, history, lang)
    except Exception:  # noqa: BLE001 - whatever happens inside, the sender gets words, never silence
        site_assistant.log.exception("Chat bot could not answer")
        return BotReply(site_assistant.PLAIN["provider_failed"][lang], outcome="failed", lang=lang)
    if answer.error:
        outcome = "failed" if answer.error == "provider_failed" else answer.error
        return BotReply(
            answer.lines[0] if answer.lines else site_assistant.PLAIN["provider_failed"][lang],
            _buttons(lang, "talk_person"),
            outcome=outcome,
            lang=lang,
        )
    body = render(answer.lines, answer.links, lang)
    wanted: tuple[ChatButton, ...] = ()
    if answer.outcome == "unknown":
        wanted = _buttons(lang, "see_prices", "how_signup", "talk_person")
    elif first_contact:
        wanted = _buttons(lang, *BUTTON_IDS)
    body, shown = _with_buttons(body, wanted)
    return BotReply(body, shown, outcome=answer.outcome, lang=lang)


def _asks_for_a_person(message: str) -> bool:
    found = _tokens(message)
    return 0 < len(found) <= 8 and any(w in HUMAN_WORDS for w in found)


def _handoff(texts: BotTexts, lang: str) -> BotReply:
    if is_off_hours(texts):
        body = texts.off_hours.strip() or say("off_hours", lang)
    else:
        body = texts.handoff.strip() or say("handoff", lang)
    return BotReply(body, outcome="handoff", action="handoff", lang=lang)
