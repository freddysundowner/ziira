"""Reading an uploaded CSV file into headers and rows, whatever Excel or another system did to it.

Tolerated: a byte-order mark, UTF-16 or Windows-1252 text (with a warning), `,` `;` tab or `|` as the delimiter,
quoted cells with commas and line breaks, spaces around values, blank lines. Refused with a plain message: an Excel
workbook, binary data, an empty file, a file over the limits. Never raises anything but `ImportFileError`.
"""

import codecs
import csv
import io
from dataclasses import dataclass, field

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5_000
MAX_COLUMNS = 100
MAX_CELL = 2_000
MAX_WARNINGS = 20
DELIMITERS = (",", ";", "\t", "|")


class ImportFileError(ValueError):
    """The file cannot be used; the message says why in plain words."""


@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[tuple[int, list[str]]]          # (row number as in the spreadsheet, cells aligned with headers)
    delimiter: str
    warnings: list[str] = field(default_factory=list)


def decode(data: bytes, warnings: list[str]) -> str:
    """The file's text. UTF-8 (with or without BOM) or UTF-16 with a BOM; anything else is read as Windows-1252."""
    if data[:4] == b"PK\x03\x04":
        raise ImportFileError("This is an Excel workbook, not a CSV file. In Excel use Save As > CSV (UTF-8).")
    if data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as error:
            raise ImportFileError("The file could not be read as text.") from error
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        warnings.append("The file is not UTF-8; it was read as Windows-1252. Check names with accents.")
    if "\x00" in text:
        raise ImportFileError("This does not look like a CSV text file.")
    return text


def sniff_delimiter(text: str) -> str:
    """The delimiter most used outside quotes on the first non-empty line (comma when unsure)."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    counts = dict.fromkeys(DELIMITERS, 0)
    quoted = False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    best = max(DELIMITERS, key=lambda d: (counts[d], d == ","))
    return best if counts[best] > 0 else ","


def _plain(cell: str) -> str:
    """A cell trimmed, without the apostrophe our own downloads put before a value that starts like a formula
    (so a rejected-rows file can be fixed and uploaded again)."""
    cell = cell.strip()
    return cell[1:] if cell[:1] == "'" and cell[1:2] in ("=", "+", "-", "@") else cell


def clean_headers(cells: list[str]) -> list[str]:
    """Header names: trimmed, blanks named 'column N', repeats numbered."""
    seen: dict[str, int] = {}
    headers = []
    for index, cell in enumerate(cells, 1):
        name = " ".join(cell.split()) or f"column {index}"
        seen[name.lower()] = seen.get(name.lower(), 0) + 1
        headers.append(name if seen[name.lower()] == 1 else f"{name} ({seen[name.lower()]})")
    return headers


def parse_file(data: bytes, *, delimiter: str | None = None) -> ParsedFile:
    """Headers and data rows of a CSV file. `delimiter` forces one; by default it is detected."""
    if len(data) > MAX_BYTES:
        raise ImportFileError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. Split it into smaller files.")
    if not data.strip():
        raise ImportFileError("The file is empty.")
    warnings: list[str] = []
    text = decode(data, warnings)
    chosen = delimiter or sniff_delimiter(text)
    if chosen not in DELIMITERS:
        raise ImportFileError("The delimiter must be a comma, semicolon, tab or bar.")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=chosen)
    headers: list[str] = []
    rows: list[tuple[int, list[str]]] = []
    number = 0
    try:
        for cells in reader:
            number += 1
            blank = not any(c.strip() for c in cells)
            if not headers:
                if blank:
                    continue
                if len(cells) > MAX_COLUMNS:
                    raise ImportFileError(f"The file has more than {MAX_COLUMNS} columns.")
                headers = clean_headers(cells)
                continue
            if blank:
                continue
            if len(rows) >= MAX_ROWS:
                raise ImportFileError(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
            if any(len(c) > MAX_CELL for c in cells):
                raise ImportFileError(f"Row {number} has a value longer than {MAX_CELL} characters.")
            if len(cells) > len(headers):
                if any(c.strip() for c in cells[len(headers):]) and len(warnings) < MAX_WARNINGS:
                    warnings.append(f"Row {number} has more values than the header; the extra values were ignored.")
                cells = cells[:len(headers)]
            rows.append((number, [_plain(c) for c in cells] + [""] * (len(headers) - len(cells))))
    except csv.Error as error:
        raise ImportFileError(f"The file could not be read as CSV ({error}).") from error
    if not headers:
        raise ImportFileError("The file has no header row.")
    if not rows:
        raise ImportFileError("The file has a header but no data rows.")
    return ParsedFile(headers, rows, chosen, warnings)
