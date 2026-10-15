"""Rebuilding a table from words that have positions on a page (text PDFs and OCR share this).

A page of words becomes lines (words at about the same height), lines become cells: the header line is the one whose
phrases are known column names, and every later line is split into cells by where its phrases sit under those
headers. Pages without their own header line reuse the previous page's. When no header line exists anywhere, lines
that start with a date and end with amounts are read by shape (`rows_from_text`).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from ziira.modules.connect.domain import shapes
from ziira.modules.connect.domain.csvfile import normalise
from ziira.modules.connect.domain.tabular import RawRow

GAP_FACTOR = 0.6          # words closer than this many text heights are one phrase
LINE_FACTOR = 0.5         # words whose tops differ by less than this many heights are on one line
MIN_HEADER_HITS = 2


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    confidence: float = 100.0


@dataclass
class Phrase:
    text: str
    x0: float
    x1: float
    confidence: float


def group_lines(words: list[Word]) -> list[list[Word]]:
    """Words sorted into lines top to bottom, each line left to right."""
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    height = median(max(w.bottom - w.top, 1.0) for w in words)
    lines: list[list[Word]] = []
    centre: list[float] = []
    for word in sorted(words, key=lambda w: (w.top + w.bottom) / 2):
        middle = (word.top + word.bottom) / 2
        if lines and abs(middle - centre[-1]) <= height * LINE_FACTOR:
            lines[-1].append(word)
            centre[-1] = (centre[-1] * (len(lines[-1]) - 1) + middle) / len(lines[-1])
        else:
            lines.append([word])
            centre.append(middle)
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def phrases_of(line: list[Word]) -> list[Phrase]:
    """Neighbouring words merged into phrases; a wide gap starts a new one (a new column)."""
    if not line:
        return []
    height = median(max(w.bottom - w.top, 1.0) for w in line)
    out = [Phrase(line[0].text, line[0].x0, line[0].x1, line[0].confidence)]
    for word in line[1:]:
        last = out[-1]
        if word.x0 - last.x1 <= height * GAP_FACTOR:
            last.text += " " + word.text
            last.x1 = max(last.x1, word.x1)
            last.confidence = min(last.confidence, word.confidence)
        else:
            out.append(Phrase(word.text, word.x0, word.x1, word.confidence))
    return out


def header_hits(phrases: list[Phrase], vocabulary: set[str]) -> int:
    return len({normalise(p.text) for p in phrases if normalise(p.text) in vocabulary})


def _zones(anchors: list[Phrase]) -> list[tuple[float, float]]:
    """Where each header's column lies: from the middle of the gap before it to the middle of the gap after it."""
    cuts = [(anchors[i].x1 + anchors[i + 1].x0) / 2 for i in range(len(anchors) - 1)]
    edges = [float("-inf"), *cuts, float("inf")]
    return [(edges[i], edges[i + 1]) for i in range(len(anchors))]


def _assign(phrases: list[Phrase], anchors: list[Phrase], low: float) -> tuple[list[str], bool]:
    zones = _zones(anchors)
    cells = [""] * len(anchors)
    doubtful = False
    for phrase in phrases:
        overlaps = [max(0.0, min(phrase.x1, hi) - max(phrase.x0, lo)) for lo, hi in zones]
        index = max(range(len(zones)), key=lambda i: overlaps[i])
        cells[index] = f"{cells[index]} {phrase.text}".strip()
        doubtful = doubtful or phrase.confidence < low
    return cells, doubtful


class TableBuilder:
    """Feeds pages of words in, collects rows out. Keeps the last header so later pages need not repeat it."""

    def __init__(self, vocabulary: set[str], *, low_confidence: float = 60.0) -> None:
        self.vocabulary = vocabulary
        self.low = low_confidence
        self.rows: list[RawRow] = []
        self.loose: list[tuple[int, str, float]] = []        # (page, text, lowest confidence) before any header
        self.anchors: list[Phrase] | None = None
        self.header_seen = False

    def feed(self, words: list[Word], page: int) -> None:
        for line in group_lines(words):
            phrases = phrases_of(line)
            if header_hits(phrases, self.vocabulary) >= MIN_HEADER_HITS:
                self.anchors = phrases
                self.header_seen = True
                self.rows.append(RawRow(len(self.rows) + 1, [p.text for p in phrases], page))
            elif self.anchors:
                cells, doubtful = _assign(phrases, self.anchors, self.low)
                self.rows.append(RawRow(len(self.rows) + 1, cells, page, doubtful))
            else:
                self.loose.append((page, " ".join(w.text for w in line), min(w.confidence for w in line)))

    def result(self) -> list[RawRow]:
        """The rows found under a header; else lines read by shape; else nothing."""
        if self.header_seen:
            return self.rows
        return rows_from_text(self.loose, self.low)


# --------------------------------------------------------------------------- no header: lines read by their shape
_TRAILING_CR_DR = re.compile(r"^(?:cr|dr)$", re.IGNORECASE)


def _split_amounts(tokens: list[str]) -> tuple[list[str], list[str]]:
    """(the rest, the trailing amount tokens): 'DR'/'CR' stays glued to the amount before it."""
    amounts: list[str] = []
    rest = list(tokens)
    while rest:
        token = rest[-1]
        if _TRAILING_CR_DR.match(token) and len(rest) > 1 and shapes.is_money(rest[-2]):
            amounts.insert(0, f"{rest[-2]} {token}")
            rest = rest[:-2]
        elif shapes.is_money(token):
            amounts.insert(0, token)
            rest = rest[:-1]
        else:
            break
    return rest, amounts


def _signed_by_balance(amount: str, balance_text: str, previous: Decimal | None) -> tuple[str, Decimal | None]:
    """The amount with a minus sign when the balance fell by it (an unsigned amount says nothing about direction)."""
    move, balance = shapes.number(amount), shapes.number(balance_text)
    if balance is None:
        return amount, previous
    marked = amount.strip().upper().endswith(("CR", "DR")) or amount.strip().startswith(("-", "("))
    if move is not None and previous is not None and not marked and balance - previous == -abs(move) != abs(move):
        return f"-{amount}", balance
    return amount, balance


def rows_from_text(lines: list[tuple[int, str, float]], low: float = 60.0) -> list[RawRow]:
    """Lines like `14/10/2026 QWE123 Payment to shop 2,000.00 8,300.00`: date first, amounts last, in between a code
    (when the first token looks like one) and the details. With two amounts the second is the balance and the
    first moves the balance (its direction is worked out from the change in balance)."""
    parsed: list[tuple[int, list[str] | None, str, bool]] = []
    for page, text, confidence in lines:
        match = re.match(rf"^({shapes.DATE_RE})(?:\s+({shapes.TIME_RE}))?\s+(.*)$", text)
        if not match:
            parsed.append((page, None, text, confidence < low))
            continue
        date_text = f"{match[1]} {match[2]}".strip() if match[2] else match[1]
        rest, amounts = _split_amounts(match[3].split())
        code = ""
        if rest and shapes.is_code(rest[0]) and len(rest) > 1:
            code, rest = rest[0], rest[1:]
        parsed.append((page, [date_text, code, " ".join(rest), *amounts], text, confidence < low))
    dated = [c for _, c, _, _ in parsed if c is not None and len(c) > 3]
    if not dated:
        return []
    width = max({len(c) for c in dated}, key=[len(c) for c in dated].count)
    header = ["Date", "Reference", "Details"]
    named = {1: ["Amount"], 2: ["Amount", "Balance"], 3: ["Paid in", "Withdrawn", "Balance"]}
    header += named.get(width - 3, ["Amount"])
    rows: list[RawRow] = []
    previous: Decimal | None = None
    for page, cells, text, doubtful in parsed:
        if cells is None:                                        # a title, a footer, or the wrapped end of a detail
            rows.append(RawRow(len(rows) + 2, ["", "", text, *[""] * (len(header) - 3)], page, doubtful))
            continue
        cells = cells[:len(header)] + [""] * (len(header) - len(cells))
        if header[-1] == "Balance" and len(header) == 5:
            cells[3], previous = _signed_by_balance(cells[3], cells[4], previous)
        rows.append(RawRow(len(rows) + 2, cells, page, doubtful))
    return [RawRow(1, header, 0), *rows]
