"""Working out a file's layout without asking: where the table starts, which column is which, how dates and numbers
are written, and how sure we are.

Everything is judged by header words (alias tables supplied by the connectors, as data) and by the shape of the
cells beneath them (dates, amounts, codes, text). No country is assumed: a date written 03/04/2026 is ambiguous and
reported as such. Wrapped description lines, repeated headers, titles, totals and page footers are recognised here.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import get_close_matches

from ziira.modules.connect.domain import csvfile, reconcile, shapes
from ziira.modules.connect.domain.tabular import RawRow, RawTable

HEADER_SEARCH = 60
PROFILE_ROWS = 80
FUZZY = 0.85
# the kind of content a field holds, by field name (data, so a connector's own names can be added here)
FIELD_SHAPES = {"date": "date", "issue_date": "date", "reference": "code", "description": "text",
                "money_in": "amount", "money_out": "amount", "amount": "amount", "balance": "amount",
                "direction": "direction"}
TEXT_FIELDS = ("description", "reference", "counterparty")
_FOOTER = re.compile(r"\bpage\s+\d+(\s+(of|/)\s+\d+)?\b|^\d+\s*/\s*\d+$", re.IGNORECASE)


@dataclass
class Shaped:
    """The table once its header is found: headers, and every line below with its kind (data / text / junk)."""

    headers: list[str]
    rows: list[RawRow]
    kinds: list[str]
    header_found: bool
    warnings: list[str] = field(default_factory=list)
    source: str = "csv"
    ocr: bool = False


@dataclass
class Guess:
    mapping: dict[str, str | None]
    how: dict[str, float]                 # field -> how sure (1 header name, 0.85 similar name, 0.7 by content)


@dataclass
class Formats:
    date_format: str = "iso"
    ambiguous: bool = False
    decimal_separator: str = "."


# --------------------------------------------------------------------------- finding the header
def _hits(cells: list[str], vocabulary: set[str], fuzzy: bool) -> int:
    found = set()
    for cell in cells:
        key = csvfile.normalise(cell)
        if not key or len(key) > 40:
            continue
        if key in vocabulary or (fuzzy and len(key) > 3 and get_close_matches(key, vocabulary, 1, FUZZY)):
            found.add(key)
    return len(found)


def _is_data(cells: list[str]) -> bool:
    return any(shapes.is_date(c) for c in cells) and any(shapes.is_amount(c) and not shapes.is_date(c) for c in cells)


def find_header(rows: list[RawRow], vocabulary: set[str]) -> int | None:
    """Index of the header line: the line with the most known column names (at least two), earliest on a tie."""
    for fuzzy in (False, True):
        best, best_score = None, 1
        for index, row in enumerate(rows[:HEADER_SEARCH]):
            score = _hits(row.cells, vocabulary, fuzzy)
            if score > best_score:
                best, best_score = index, score
        if best is not None:
            return best
    return None


def _classify(cells: list[str]) -> str:
    """data: a dated line with an amount; text: words only (a title, a footer, or the wrapped end of a detail);
    junk: something else (an undated line with numbers: totals, page numbers)."""
    filled = [c for c in cells if c.strip()]
    if not filled:
        return "junk"
    dated = any(shapes.is_date(c) for c in filled)
    numeric = any(shapes.is_money(c) or re.fullmatch(r"\(?-?\d[\d,]*\)?", c.strip()) for c in filled)
    if dated and (numeric or len(filled) >= 3):
        return "data"
    if not dated and not numeric:
        return "text"
    return "junk"


def shape(table: RawTable, vocabulary: set[str], *, lenient: bool, skip_phrases: tuple[str, ...] = ()) -> Shaped:
    """Find the header and sort the lines below it. `lenient` (statements, and any file that is not plain CSV) drops
    titles, totals, page footers and repeated headers and keeps wrapped detail lines for merging."""
    rows = table.rows
    start = find_header(rows, vocabulary)
    found = start is not None
    warnings = list(table.warnings)
    header_keys: set[str] = set()
    if start is None:
        start = next((i for i in range(len(rows)) if _is_data(rows[i].cells) and
                      sum(_is_data(r.cells) for r in rows[i:i + 3]) >= min(2, len(rows) - i)), None)
        if start is None:
            headers = csvfile.clean_headers(rows[0].cells)
            body = rows[1:]
        else:
            width = max(len(r.cells) for r in rows[start:start + 20])
            headers = csvfile.clean_headers([""] * width)
            body = rows[start:]
            warnings.append("The columns have no names in this file; they were recognised by what they contain.")
    else:
        headers = csvfile.clean_headers(rows[start].cells)
        header_keys = {csvfile.normalise(h) for h in rows[start].cells if csvfile.normalise(h)}
        body = rows[start + 1:]
        if start:
            warnings.append(f"{start} line(s) above the column names were ignored.")
    width = len(headers)
    out: list[RawRow] = []
    kinds: list[str] = []
    for row in body:
        cells = (row.cells + [""] * width)[:width]
        if not any(c.strip() for c in cells):
            continue
        shaped_row = RawRow(row.number, cells, row.page, row.low_confidence)
        if not lenient:
            out.append(shaped_row)
            kinds.append("data")
            continue
        keys = {csvfile.normalise(c) for c in cells if csvfile.normalise(c)}
        if header_keys and len(keys & header_keys) >= max(2, len(header_keys) * 0.7):
            continue                                              # the header repeated on a new page
        text = " ".join(c for c in cells if c.strip())
        low = text.lower()
        kind = _classify(cells)
        if _FOOTER.search(low) or _starts_with_any(cells, skip_phrases):
            kind = "junk"
        out.append(shaped_row)
        kinds.append(kind)
    return Shaped(headers, out, kinds, found, warnings, table.source, table.ocr)


def _starts_with_any(cells: list[str], phrases: tuple[str, ...]) -> bool:
    """True when some cell begins with one of the phrases (an 'opening balance' line)."""
    return any(c.strip().lower().startswith(p) for c in cells for p in phrases)


# --------------------------------------------------------------------------- reading the columns' contents
def _values(shaped: Shaped, header: str) -> list[str]:
    index = shaped.headers.index(header)
    return [r.cells[index] for r, k in zip(shaped.rows, shaped.kinds, strict=True) if k == "data"][:PROFILE_ROWS * 4]


@dataclass
class Profile:
    fill: float = 0.0
    date: float = 0.0
    amount: float = 0.0
    code: float = 0.0
    direction: float = 0.0
    unique: float = 0.0
    length: float = 0.0


def profile(shaped: Shaped, header: str) -> Profile:
    values = _values(shaped, header)[:PROFILE_ROWS]
    filled = [v.strip() for v in values if v.strip()]
    if not values or not filled:
        return Profile()
    n = len(filled)
    return Profile(
        fill=n / len(values), date=sum(shapes.is_date(v) for v in filled) / n,
        amount=sum(shapes.is_amount(v) and not shapes.is_code(v) or shapes.is_money(v) for v in filled) / n,
        code=sum(shapes.is_code(v) for v in filled) / n, direction=sum(shapes.is_direction(v) for v in filled) / n,
        unique=len(set(filled)) / n, length=sum(len(v) for v in filled) / n)


def detect_decimal(shaped: Shaped, headers: list[str]) -> str:
    """'.' or ',': which one the amounts use before the cents, voted by cells that cannot be read the other way."""
    votes: Counter[str] = Counter()
    for header in headers:
        for value in _values(shaped, header)[:PROFILE_ROWS * 2]:
            v = re.sub(r"\s*(CR|DR)\.?$", "", value.strip(), flags=re.IGNORECASE).strip("()- ")
            if re.search(r"\d\.\d{3},\d", v) or re.search(r",\d{1,2}$", v) and not re.search(r"\.\d{1,2}$", v):
                votes[","] += 1
            elif re.search(r"\d,\d{3}\.\d", v) or re.search(r"\.\d{1,2}$", v):
                votes["."] += 1
    return "," if votes[","] > votes["."] else "."


def detect_dates(values: list[str]) -> tuple[str, bool]:
    """(date format, ambiguous): iso when written year-first, else the day/month order the numbers allow."""
    dmy = mdy = True
    numeric = 0
    for value in values:
        match = re.match(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", value)
        if not match:
            continue
        numeric += 1
        a, b = int(match[1]), int(match[2])
        dmy = dmy and a <= 31 and b <= 12
        mdy = mdy and a <= 12 and b <= 31
    if numeric == 0:
        return "iso", False
    if dmy and mdy:
        return "dmy", True
    if mdy and not dmy:
        return "mdy", False
    return "dmy", False


def formats_for(shaped: Shaped, mapping: dict[str, str | None]) -> Formats:
    amount_fields = ("money_in", "money_out", "amount", "balance", "total", "paid")
    amount_headers = [h for f in amount_fields if (h := mapping.get(f))]
    date_headers = [h for f in ("date", "issue_date") if (h := mapping.get(f))]
    values = [v for h in date_headers for v in _values(shaped, h)]
    date_format, ambiguous = detect_dates(values)
    return Formats(date_format, ambiguous, detect_decimal(shaped, amount_headers))


# --------------------------------------------------------------------------- which column is which
def _numbers(shaped: Shaped, header: str, separator: str) -> list[Decimal | None]:
    return [shapes.number(v, separator) if v.strip() else None for v in _values(shaped, header)]


def _balance_fit(shaped: Shaped, balance: str, in_col: str | None, out_col: str | None, signed: str | None,
                 separator: str) -> float:
    bal = _numbers(shaped, balance, separator)
    parts = []
    for i, b in enumerate(bal):
        if b is None:
            continue
        move = Decimal(0)
        if signed:
            move = _numbers(shaped, signed, separator)[i] or Decimal(0)
        else:
            move = ((_numbers(shaped, in_col, separator)[i] if in_col else None) or Decimal(0)) - \
                   ((_numbers(shaped, out_col, separator)[i] if out_col else None) or Decimal(0))
        parts.append((i, move, b))
    if len(parts) < 2:
        return 0.0
    exact = [(i, m, b) for i, m, b in parts]
    best = 0.0
    for entries in (exact, exact[::-1]):
        ok = sum(entries[j][2] - entries[j - 1][2] == entries[j][1] for j in range(1, len(entries)))
        loose = sum(abs(entries[j][2] - entries[j - 1][2]) == abs(entries[j][1]) for j in range(1, len(entries)))
        steps = len(entries) - 1
        best = max(best, ok / steps, 0.9 * loose / steps if signed or not (in_col and out_col) else 0)
    return best


def guess_mapping(shaped: Shaped, fields: list[tuple[str, tuple[str, ...]]], separator: str = ".") -> Guess:
    """Header words first (exact, then similar), then what the columns contain for the fields still unplaced."""
    names = dict(fields)
    base = csvfile.suggest_mapping(shaped.headers, fields) if shaped.header_found else dict.fromkeys(names)
    mapping: dict[str, str | None] = dict(base)
    how: dict[str, float] = {}
    for name, header in base.items():
        if header:
            wanted = {csvfile.normalise(name), *(csvfile.normalise(a) for a in names[name])}
            how[name] = 1.0 if csvfile.normalise(header) in wanted else 0.85
    used = {h for h in mapping.values() if h}
    profiles = {h: profile(shaped, h) for h in shaped.headers}

    def place(name: str, header: str | None, sure: float = 0.7) -> None:
        if header and name in names and mapping.get(name) is None and header not in used:
            mapping[name] = header
            used.add(header)
            how[name] = sure

    def free(test: Callable[[Profile], bool]) -> list[str]:
        return [h for h in shaped.headers if h not in used and test(profiles[h])]

    for name in ("date", "issue_date"):
        if name in names and mapping.get(name) is None:
            place(name, max(free(lambda p: p.date >= 0.6), key=lambda h: profiles[h].date, default=None))
    if "direction" in names:
        place("direction", next(iter(free(lambda p: p.direction >= 0.8 and p.fill >= 0.5)), None))
    if "reference" in names:
        place("reference", next(iter(free(lambda p: p.code >= 0.7 and p.unique >= 0.8)), None))
    if "money_in" in names:
        _place_amounts(shaped, names, mapping, used, profiles, separator, place)
    if "description" in names:
        text_cols = free(lambda p: p.amount < 0.3 and p.date < 0.3 and p.code < 0.5 and p.length >= 6)
        place("description", max(text_cols, key=lambda h: profiles[h].length, default=None))
    return Guess(mapping, how)


def _place_amounts(shaped: Shaped, names: dict[str, tuple[str, ...]], mapping: dict[str, str | None], used: set[str],
                   profiles: dict[str, Profile], separator: str, place: Callable[..., None]) -> None:
    mapped_amounts = [mapping.get(f) for f in ("money_in", "money_out", "amount")]
    spare = [h for h in shaped.headers if h not in used and profiles[h].amount >= 0.6]
    if not spare:
        return
    if any(mapped_amounts):
        # amounts known by name; a spare column that keeps the running balance is the balance
        if mapping.get("balance") is None:
            for h in spare:
                fit = _balance_fit(shaped, h, mapping.get("money_in"), mapping.get("money_out"), mapping.get("amount"),
                                   separator)
                if profiles[h].fill >= 0.8 and fit >= 0.6:
                    place("balance", h)
                    return
        return
    if mapping.get("balance") is None:
        scored: list[tuple[float, str, dict[str, str]]] = []
        for h in spare:
            found = _best_assignment(shaped, h, [s for s in spare if s != h], separator) if profiles[h].fill >= 0.8 \
                else None
            if found is not None and found[0] >= 0.6:
                scored.append((found[0], h, found[1]))
        if scored:
            _, balance, assignment = max(scored, key=lambda item: item[0])
            place("balance", balance)
            for field_name, header in assignment.items():
                place(field_name, header, 0.7)
            return
    rest = [s for s in spare if s != mapping.get("balance")]
    if len(rest) >= 2 and not (set(_filled(shaped, rest[0])) & set(_filled(shaped, rest[1]))):
        place("money_in", rest[0])
        place("money_out", rest[1])
    elif rest:
        place("amount", rest[0])


def _filled(shaped: Shaped, header: str) -> list[int]:
    return [i for i, v in enumerate(_values(shaped, header)) if v.strip()]


def _best_assignment(shaped: Shaped, balance: str, others: list[str], separator: str) \
        -> tuple[float, dict[str, str]] | None:
    """How well the other numeric columns explain the balance's changes, and which of them is in / out / signed."""
    if len(others) == 1:
        score = _balance_fit(shaped, balance, None, None, others[0], separator)
        return score, {"amount": others[0]}
    if len(others) == 2:
        first = _balance_fit(shaped, balance, others[0], others[1], None, separator)
        second = _balance_fit(shaped, balance, others[1], others[0], None, separator)
        return (first, {"money_in": others[0], "money_out": others[1]}) if first >= second else \
               (second, {"money_in": others[1], "money_out": others[0]})
    return None


# --------------------------------------------------------------------------- wrapped lines
def merge_wrapped(shaped: Shaped, mapping: dict[str, str | None]) -> tuple[list[RawRow], int, int]:
    """(the transaction lines with wrapped detail lines joined to the line above, wrapped lines joined, lines
    dropped as not transactions)."""
    text_cols = [shaped.headers.index(h) for f in TEXT_FIELDS if (h := mapping.get(f)) and h in shaped.headers]
    result: list[RawRow] = []
    joined = dropped = 0
    last_data = False
    for row, kind in zip(shaped.rows, shaped.kinds, strict=True):
        if kind == "data":
            result.append(RawRow(row.number, list(row.cells), row.page, row.low_confidence))
            last_data = True
            continue
        filled = [i for i, c in enumerate(row.cells) if c.strip()]
        if kind == "text" and last_data and result and result[-1].page == row.page and text_cols and \
                all(i in text_cols for i in filled):
            target = result[-1]
            for i in filled:
                target.cells[i] = f"{target.cells[i]} {row.cells[i].strip()}".strip()
            joined += 1
        else:
            dropped += 1
            last_data = False if kind == "junk" else last_data
    return result, joined, dropped


def confidence_of(guess: Guess, essential: list[str]) -> float:
    """How sure the layout is: the average sureness of the fields that matter (0 when one is missing)."""
    scores = [guess.how.get(f, 0.0) for f in essential]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def suspect_lines(entries: list[tuple[int, Decimal, Decimal]]) -> list[int]:
    return reconcile.suspects(entries)
