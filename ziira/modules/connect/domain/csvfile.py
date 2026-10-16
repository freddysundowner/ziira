"""Reading an uploaded CSV file into headers and rows, whatever a spreadsheet or another system did to it.

Tolerated: a byte-order mark, UTF-16 or Windows-1252 text (with a warning), `,` `;` tab or `|` as the delimiter,
quoted cells with commas and line breaks, title lines above the header (the header is the first row that looks like
one), summary lines below the data, blank lines. Refused with a plain message: an Excel workbook, binary data, an empty
file, a file over the limits. Only raises `FileProblem`.
"""

import codecs
import csv
import io
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100
MAX_CELL = 2_000
DELIMITERS = (",", ";", "\t", "|")
MIN_SIMILARITY = 0.8


class FileProblem(ValueError):
    """The file cannot be used; the message says why in plain words."""


@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[tuple[int, list[str]]]           # (line number in the file, cells aligned with headers)
    delimiter: str
    warnings: list[str] = field(default_factory=list)


def decode(data: bytes, warnings: list[str]) -> str:
    if data[:4] == b"PK\x03\x04":
        raise FileProblem("This is an Excel workbook, not a CSV file. In Excel use Save As > CSV (UTF-8).")
    if data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as error:
            raise FileProblem("The file could not be read as text.") from error
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        warnings.append("The file is not UTF-8; it was read as Windows-1252. Check names with accents.")
    if "\x00" in text:
        raise FileProblem("This does not look like a CSV text file.")
    return text


def sniff_delimiter(text: str) -> str:
    """The delimiter most used outside quotes on the first few non-empty lines (comma when unsure)."""
    lines = [ln for ln in text.splitlines() if ln.strip()][:5]
    counts = dict.fromkeys(DELIMITERS, 0)
    for line in lines:
        quoted = False
        for ch in line:
            if ch == '"':
                quoted = not quoted
            elif not quoted and ch in counts:
                counts[ch] += 1
    best = max(DELIMITERS, key=lambda d: (counts[d], d == ","))
    return best if counts[best] > 0 else ","


def clean_headers(cells: list[str]) -> list[str]:
    """Trimmed names; blanks named 'column N'; repeats numbered."""
    seen: dict[str, int] = {}
    headers = []
    for index, cell in enumerate(cells, 1):
        name = " ".join(cell.split()) or f"column {index}"
        seen[name.lower()] = seen.get(name.lower(), 0) + 1
        headers.append(name if seen[name.lower()] == 1 else f"{name} ({seen[name.lower()]})")
    return headers


def _plain(cell: str) -> str:
    """Trimmed, without the apostrophe our own downloads put before a value that starts like a formula."""
    cell = cell.strip()
    return cell[1:] if cell[:1] == "'" and cell[1:2] in ("=", "+", "-", "@") else cell


def raw_rows(data: bytes, *, delimiter: str | None = None) -> tuple[list[tuple[int, list[str]]], str, list[str]]:
    """Every non-blank line of a CSV file as cells: (line number, cells), the delimiter used, and warnings."""
    if len(data) > MAX_BYTES:
        raise FileProblem(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. Split it into smaller files.")
    if not data.strip():
        raise FileProblem("The file is empty.")
    warnings: list[str] = []
    text = decode(data, warnings)
    chosen = delimiter or sniff_delimiter(text)
    if chosen not in DELIMITERS:
        raise FileProblem("The delimiter must be a comma, semicolon, tab or bar.")
    all_rows: list[tuple[int, list[str]]] = []
    try:
        for number, cells in enumerate(csv.reader(io.StringIO(text, newline=""), delimiter=chosen), 1):
            if any(c.strip() for c in cells):
                all_rows.append((number, cells))
    except csv.Error as error:
        raise FileProblem(f"The file could not be read as CSV ({error}).") from error
    if not all_rows:
        raise FileProblem("The file is empty.")
    return all_rows, chosen, warnings


def parse_file(data: bytes, *, delimiter: str | None = None, header_hint: set[str] | None = None) -> ParsedFile:
    """Headers and data rows. With `header_hint` (normalised names the connector knows), title lines above the header
    are skipped: the header is the first row sharing at least two names with the hint (else the first non-blank row)."""
    all_rows, chosen, warnings = raw_rows(data, delimiter=delimiter)
    start = 0
    if header_hint:
        for index, (_, cells) in enumerate(all_rows[:30]):
            if len({normalise(c) for c in cells} & header_hint) >= 2:
                start = index
                break
    header_number, header_cells = all_rows[start]
    if len(header_cells) > MAX_COLUMNS:
        raise FileProblem(f"The file has more than {MAX_COLUMNS} columns.")
    if start:
        warnings.append(f"{start} line(s) above the column names were ignored.")
    headers = clean_headers(header_cells)
    rows: list[tuple[int, list[str]]] = []
    for number, cells in all_rows[start + 1:]:
        if len(rows) >= MAX_ROWS:
            raise FileProblem(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
        if any(len(c) > MAX_CELL for c in cells):
            raise FileProblem(f"Row {number} has a value longer than {MAX_CELL} characters.")
        cells = cells[:len(headers)]
        rows.append((number, [_plain(c) for c in cells] + [""] * (len(headers) - len(cells))))
    if not rows:
        raise FileProblem("The file has column names but no data rows.")
    del header_number
    return ParsedFile(headers, rows, chosen, warnings)


# --------------------------------------------------------------------------- guessing which column is which
def normalise(name: str) -> str:
    """A header reduced to lower-case letters and digits ('Unit Price (USD)' and 'unit_price' compare alike)."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", name.lower()))


def suggest_mapping(headers: list[str], fields: list[tuple[str, tuple[str, ...]]]) -> dict[str, str | None]:
    """For each field (name, aliases) the header that best matches it, or None. A header serves one field only; exact
    matches of the name or an alias win over similar ones."""
    heads = {h: normalise(h) for h in headers}
    result: dict[str, str | None] = {name: None for name, _ in fields}
    taken: set[str] = set()
    for name, aliases in fields:
        wanted = {normalise(name), *(normalise(a) for a in aliases)}
        for header, key in heads.items():
            if header not in taken and key in wanted:
                result[name] = header
                taken.add(header)
                break
    for name, aliases in fields:
        if result[name] is not None:
            continue
        best, best_score = None, MIN_SIMILARITY
        for header, key in heads.items():
            if header in taken or not key:
                continue
            score = max(SequenceMatcher(None, key, normalise(w)).ratio() for w in (name, *aliases) if normalise(w))
            if score >= best_score:
                best, best_score = header, score
        if best is not None:
            result[name] = best
            taken.add(best)
    return result
