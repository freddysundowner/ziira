"""Reading a text PDF statement into rows.

For each page: a ruled table is read as a table when its header line has known column names; otherwise the page's
words are placed under the header by their position (`words.TableBuilder`); with no header anywhere, lines are read by
shape. Password-protected files need the password (used once to open the file, never kept). A PDF whose pages are
pictures raises `NeedsOcr` so the caller can read them with the OCR engine.
"""

import io
import logging
from typing import Any

from ziira.modules.connect.domain.csvfile import FileProblem, normalise
from ziira.modules.connect.domain.tabular import MAX_ROWS, NeedsOcr, PasswordNeeded, RawRow, RawTable
from ziira.modules.connect.domain.words import MIN_HEADER_HITS, TableBuilder, Word

MAX_PAGES = 300
MIN_TEXT_CHARS = 30
log = logging.getLogger("ziira.connect")


def _open(data: bytes, password: str | None) -> Any:
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException
    try:
        return pdfplumber.open(io.BytesIO(data), password=password or None)
    except PdfminerException as error:
        if error.args and isinstance(error.args[0], PDFPasswordIncorrect):
            raise PasswordNeeded(wrong=bool(password)) from None
        raise FileProblem("This PDF could not be read. Download the statement again, or as Excel/CSV.") from None
    except (ValueError, TypeError, OSError, KeyError, AttributeError, AssertionError, RecursionError):
        raise FileProblem("This PDF could not be read. Download the statement again, or as Excel/CSV.") from None


def page_count(data: bytes, password: str | None = None) -> int:
    with _open(data, password) as pdf:
        return len(pdf.pages)


def _table_rows(page: Any, vocabulary: set[str], page_no: int, start: int) -> list[RawRow]:
    """Rows of a ruled table on the page whose header names are known; [] when the page has no such table."""
    try:
        tables = page.extract_tables()
    except Exception:                                                              # noqa: BLE001 - odd drawings
        return []
    rows: list[RawRow] = []
    for table in tables:
        cleaned = [[" ".join((c or "").split()) for c in row] for row in table if row]
        cleaned = [r for r in cleaned if any(r)]
        if len(cleaned) < 2 or max(len(r) for r in cleaned) < 3:
            continue
        hits = max(len({normalise(c) for c in r if normalise(c) in vocabulary}) for r in cleaned[:5])
        if hits >= MIN_HEADER_HITS:
            for cells in cleaned:
                rows.append(RawRow(start + len(rows) + 1, cells, page_no))
    return rows


def _words(page: Any) -> list[Word]:
    found = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=2)
    return [Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"])) for w in found]


def read_pdf(data: bytes, *, vocabulary: set[str], password: str | None = None) -> RawTable:
    """The rows of a text PDF. Raises PasswordNeeded, NeedsOcr or FileProblem."""
    with _open(data, password) as pdf:
        total = len(pdf.pages)
        if total > MAX_PAGES:
            raise FileProblem(f"The PDF has more than {MAX_PAGES} pages. Download the statement in parts.")
        builder = TableBuilder(vocabulary)
        ordered: list[RawRow] = []
        text_pages = picture_pages = 0
        for number, page in enumerate(pdf.pages, 1):
            if len(page.chars) < MIN_TEXT_CHARS:
                picture_pages += 1 if (page.images or not page.chars) else 0
                continue
            text_pages += 1
            ruled = _table_rows(page, vocabulary, number, len(ordered))
            if ruled:
                ordered.extend(ruled)
            else:
                before = len(builder.rows)
                builder.feed(_words(page), number)
                ordered.extend(builder.rows[before:] if builder.header_seen else [])
            if len(ordered) > MAX_ROWS:
                raise FileProblem(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
    if text_pages == 0:
        raise NeedsOcr("pdf", total)
    rows = [RawRow(i, r.cells, r.page, r.low_confidence) for i, r in enumerate(
        ordered if builder.header_seen or ordered else builder.result(), 1)]
    if not rows:
        raise FileProblem("No transactions could be found in this PDF. Download the statement as Excel/CSV, or send "
                          "us a sample so we can learn the layout.")
    warnings = [f"{picture_pages} page(s) of the PDF are pictures and were left out."] if picture_pages else []
    return RawTable(rows, "pdf", warnings)
