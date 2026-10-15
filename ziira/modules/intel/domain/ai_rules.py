"""Rules of the AI layer that need no database: keeping personal data out of what is sent, checking that every figure
in a reply came from the facts, validating a ranking, and the consent text.

The model writes sentences; it never supplies figures. Whatever it says is accepted only if its numbers can be found
in the facts it was given (`FigureChecker`).
"""

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# --------------------------------------------------------------------------- keeping personal data out
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PLUS_PHONE = re.compile(r"(?<![\w.,])\+\d[\d ()-]{6,}\d")
_SEPARATED = re.compile(r"(?<![\w.,-])\d{2,4}(?:[ .-]\d{2,4}){2,}(?![\w.,]\d)")
_DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LONG_DIGITS = re.compile(r"(?<![\w.,])\d{9,}(?!\.\d)(?![\w,])")
_MIXED_ID = re.compile(r"(?<![\w-])(?=(?:[A-Za-z]*\d){6})(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{9,}(?![\w-])")
_AMOUNT = re.compile(r"^-?\d+(\.\d+)?$")


def _separated_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group())
    return match.group() if len(digits) < 9 or _DATE_LIKE.search(match.group()) else "[phone]"


def scrub_personal(text: str) -> str:
    """`text` with email addresses, phone numbers, long numbers (accounts, national ids) and mixed letter-and-digit
    identifiers (tax ids, bank accounts) replaced by labels. A best-effort net applied to everything sent; the data
    that goes in is chosen to need little of it. Money written with separators ("1,250.00") and dates are left alone."""
    text = _EMAIL.sub("[email]", text)
    text = _PLUS_PHONE.sub("[phone]", text)
    text = _SEPARATED.sub(_separated_phone, text)
    text = _LONG_DIGITS.sub("[number]", text)
    return _MIXED_ID.sub("[id]", text)


def scrub_value(value: Any) -> Any:
    """`scrub_personal` over every string inside parsed JSON, leaving plain decimal strings (amounts) untouched."""
    if isinstance(value, str):
        return value if _AMOUNT.match(value) else scrub_personal(value)
    if isinstance(value, list):
        return [scrub_value(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    return value


_SECRET_SHAPES = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{10,}|bearer\s+[A-Za-z0-9._~+/=-]{10,}|"
                            r"x-api-key['\":= ]+[A-Za-z0-9._~+/=-]{8,})")


def hide_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    """`text` with each given secret (a key) and anything shaped like a key or bearer token removed."""
    for secret in secrets:
        if len(secret) >= 6:
            text = text.replace(secret, "[hidden]")
    return _SECRET_SHAPES.sub("[hidden]", text)


def prompt_hash(*parts: object) -> str:
    """A fingerprint of what was sent, kept in the log instead of the text."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _letters(n: int) -> str:
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


class Pseudonyms:
    """Stands in for the names of people while a question is with the provider ("Customer A"), and puts them back in
    the reply. The aliases hold no digits, so they never count as figures."""

    def __init__(self) -> None:
        self._alias: dict[str, str] = {}
        self._real: dict[str, str] = {}
        self._count: dict[str, int] = {}

    def add(self, name: str | None, kind: str = "Person") -> str | None:
        """The alias for a real name (made on first use). Names shorter than three characters are left out."""
        if not name or len(name.strip()) < 3:
            return None
        key = name.strip().casefold()
        if key not in self._alias:
            n = self._count.get(kind, 0)
            self._count[kind] = n + 1
            alias = f"{kind} {_letters(n)}"
            self._alias[key] = alias
            self._real[alias] = name.strip()
        return self._alias[key]

    def hide(self, text: str) -> str:
        """`text` with every known name replaced, longest name first."""
        for key in sorted(self._alias, key=len, reverse=True):
            text = re.sub(rf"(?<!\w){re.escape(key)}(?!\w)", self._alias[key], text, flags=re.IGNORECASE)
        return text

    def restore(self, text: str) -> str:
        """`text` with the aliases replaced by the real names again."""
        for alias in sorted(self._real, key=len, reverse=True):
            text = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", lambda _m, a=alias: self._real[a], text)  # type: ignore[misc]
        return text

    def hide_fields(self, value: Any, fields: dict[str, str]) -> Any:
        """Parsed JSON with the values of the named keys (key -> kind, such as {"customer": "Customer"}) replaced by
        aliases, and those names hidden wherever else they appear in a string."""

        def collect(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in fields and isinstance(v, str):
                        self.add(v, fields[k])
                    else:
                        collect(v)
            elif isinstance(node, list):
                for v in node:
                    collect(v)

        def apply(node: Any) -> Any:
            if isinstance(node, dict):
                return {k: apply(v) for k, v in node.items()}
            if isinstance(node, list):
                return [apply(v) for v in node]
            if isinstance(node, str):
                return self.hide(node)
            return node

        collect(value)
        return apply(value)


# --------------------------------------------------------------------------- every figure must come from the facts
_NUMBER = re.compile(
    r"(?<![\w.])(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?"
    r"(?:\s?(?P<pct>%)|\s(?P<word>thousand|million|billion|milioni|elfu|bilioni)\b|(?P<abbr>[kKmM])\b)?")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[-*])\s+")
_SCALE = {"thousand": 1_000, "elfu": 1_000, "k": 1_000, "million": 1_000_000, "milioni": 1_000_000, "m": 1_000_000,
          "billion": 1_000_000_000, "bilioni": 1_000_000_000}
MAX_UNVERIFIED_CHECKS = 20
POOL_LIMIT = 60


def numbers_in(text: str) -> list[Decimal]:
    """Every number written in `text`, without sign: "KES 1,250.50" gives 1250.50; "2026-10-15" gives 2026, 10, 15."""
    found: list[Decimal] = []
    for m in _NUMBER.finditer(text):
        try:
            found.append(Decimal(m.group("int").replace(",", "") + ("." + m.group("frac") if m.group("frac") else "")))
        except InvalidOperation:  # pragma: no cover - the pattern only matches digits
            continue
    return found


class FigureChecker:
    """Tells which numbers in a reply cannot be traced to the facts the model was given.

    Strict (an explanation): every number must appear in the facts exactly. Otherwise (Ask Ziira) a number may also be
    a rounding of a fact ("1.2 million", "12.3%"), a sum or difference of two facts, a share of one in another, or the
    total or average of a column of rows (`groups`): things the validator can recompute itself.
    """

    def __init__(self, facts: Iterable[Decimal], groups: Sequence[Sequence[Decimal]] = (), *,
                 strict: bool = False) -> None:
        self.facts: set[Decimal] = {abs(f) for f in facts}
        self.groups = [[abs(v) for v in g] for g in groups if g]
        self.strict = strict
        self._derived: set[Decimal] | None = None

    def unverified(self, reply: str) -> list[str]:
        """The numbers of `reply`, as written, that are not backed by the facts (empty when all are)."""
        bad: list[str] = []
        checked = 0
        for m in _NUMBER.finditer(_LIST_MARKER.sub("", reply)):
            written = m.group().strip()
            value = Decimal(m.group("int").replace(",", "") + ("." + m.group("frac") if m.group("frac") else ""))
            places = len(m.group("frac") or "")
            scale = _SCALE.get((m.group("word") or m.group("abbr") or "").lower(), 1)
            if value in self.facts or value * scale in self.facts:
                continue
            if self.strict:
                bad.append(written)
                continue
            checked += 1
            if checked > MAX_UNVERIFIED_CHECKS or not self._explained(value, places, scale, bool(m.group("pct"))):
                bad.append(written)
        return bad

    def _explained(self, value: Decimal, places: int, scale: int, percent: bool) -> bool:
        half = Decimal(5) * Decimal(10) ** (-places - 1)
        low, high = value - half, value + half
        pool = self.facts | self._derive() | (self._shares() if percent else set())
        for c in pool:
            shown = c / scale
            if low <= shown < high or (scale == 1 and shown == value):
                return True
        return False

    def _derive(self) -> set[Decimal]:
        if self._derived is not None:
            return self._derived
        out: set[Decimal] = set()
        for g in self.groups:
            out.add(sum(g, Decimal(0)))
            out.add(Decimal(len(g)))
            out.add(sum(g, Decimal(0)) / len(g))
            ordered = sorted(g, reverse=True)
            running = Decimal(0)
            for v in ordered[:10]:
                running += v
                out.add(running)
        pool = list(dict.fromkeys(self.facts))[:POOL_LIMIT]
        for i, a in enumerate(pool):
            for b in pool[i:]:
                out.add(a + b)
                out.add(abs(a - b))
        self._derived = out
        return out

    def _shares(self) -> set[Decimal]:
        """One fact as a percentage of another (only for a number written with a % sign)."""
        pool = list(dict.fromkeys(self.facts))[:POOL_LIMIT]
        return {a / b * 100 for a in pool for b in pool if b and a != b}


def round_money(value: Decimal, places: int = 2) -> Decimal:
    return value.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- a ranking from the model
def parse_ranking(reply: str, aliases: Sequence[str]) -> list[tuple[str, str]] | None:
    """The model's order as (alias, reason) pairs, or None unless it is exactly a permutation of `aliases` with a
    short one-line reason for each: nothing missing, nothing twice, nothing invented."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(reply[start:end + 1])
        items = data["order"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(items, list) or len(items) != len(aliases):
        return None
    out: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None
        reason = item.get("reason", "")
        if not isinstance(reason, str):
            return None
        out.append((item["id"].strip(), " ".join(reason.split())[:200]))
    if sorted(a for a, _ in out) != sorted(aliases):
        return None
    return out


# --------------------------------------------------------------------------- consent
CONSENT_VERSION = "2026-10-15"
LANGUAGES = ("en", "sw")


def consent_text(language: str, provider_label: str) -> str:
    """The words an Owner agrees to before the AI assistant is switched on (kept with the consent record)."""
    if language == "sw":
        return (
            "Msaidizi wa AI hutumia huduma ya nje (" f"{provider_label}" ") kuandika maelezo ya matokeo ya ukaguzi na "
            "kujibu maswali yako kupitia Ask Ziira.\n\n"
            "Kinachotumwa: muhtasari wa matokeo ya ukaguzi, namba na hesabu zilizokokotolewa na mfumo, "
            "majina ya bidhaa na matawi, na majibu ya maswali unayouliza (jumla, hesabu, salio). Majina "
            "ya wateja, wasambazaji na wafanyakazi hubadilishwa na lebo kama \"Customer A\" kabla ya "
            "kutumwa. Unachoandika kwenye swali hutumwa kama ulivyoandika (namba za simu na barua pepe "
            "huondolewa).\n\n"
            "Kisichotumwa: namba za simu, barua pepe, namba za kodi, taarifa za benki, nywila, funguo, "
            "mishahara.\n\n"
            "Namba zote unazoziona zinatoka kwenye rekodi zako, si kwa makadirio ya AI; jibu lolote lenye "
            "namba isiyo kwenye data hukataliwa. Kila maandishi ya AI yametiwa alama \"AI-written\". Ask "
            "Ziira hujibu kwa kutumia ruhusa na matawi ya anayeuliza tu.\n\n"
            "Data ya biashara yako haitumiwi kufunza miundo ya nje: Ziira inahitaji masharti ya mtoa "
            "huduma yasiyoruhusu hilo. Kila ombi hurekodiwa (nani, lini, zana zilizotumika, tokeni) bila "
            "maandishi yaliyotumwa. Kuna kikomo cha tokeni kwa mwezi; kikifikiwa huduma husimama. Unaweza "
            "kuzima wakati wowote na huduma husimama mara moja.")
    return (
        "The AI assistant uses an outside service (" f"{provider_label}" ") to write plain-language explanations "
        "of findings and to answer your questions in Ask Ziira.\n\n"
        "What is sent: the summary of a finding, the numbers the system calculated, names of products "
        "and branches, and the results of the questions you ask (totals, counts, balances). Names of "
        "customers, suppliers and employees are replaced by labels such as \"Customer A\" before "
        "anything is sent. What you type in a question is sent as you wrote it (phone numbers and "
        "email addresses are removed).\n\n"
        "What is not sent: phone numbers, email addresses, tax numbers, bank details, passwords, "
        "keys, salaries.\n\n"
        "Every figure you see comes from your own records, not from the AI's guess: a reply with a "
        "number that is not in the data is rejected. All AI text is labelled \"AI-written\". Ask Ziira "
        "answers only from what the person asking is allowed to see, in their branches.\n\n"
        "Your business data is not used to train outside models: Ziira requires terms with the "
        "provider that rule this out. Every request is logged (who, when, tools used, tokens) without "
        "the text sent. There is a monthly token limit; when it is reached the assistant stops. You "
        "can switch it off at any time and it stops at once.")


def consent_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
