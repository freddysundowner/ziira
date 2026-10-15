"""Realistic ugly statement files, built in code: PDFs in several layouts (text, ruled, wrapped, repeated headers,
protected, picture-only), Excel workbooks, CSVs, and rendered "scans". The same six transactions are written in every
layout, so every reader must arrive at the same totals (hand-calculated in TRANSACTIONS).

Money in: 300.00 + 1,500.50 + 12,000.00 = 13,800.50. Money out: 2,000.00 + 500.00 + 3,250.25 = 5,750.25.
Balances start at 10,000.00 before the first line.
"""

import io
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

D = Decimal


@dataclass(frozen=True)
class Line:
    day: date
    clock: str
    code: str
    details: str
    amount: Decimal            # + in, - out


OPENING = D("10000.00")
TRANSACTIONS = (
    Line(date(2026, 10, 13), "09:30:12", "QWE101", "Customer Payment from JANE W", D("300.00")),
    Line(date(2026, 10, 13), "10:30:00", "QWE102", "Payment to supplier UNGA LTD", D("-2000.00")),
    Line(date(2026, 10, 14), "08:15:00", "QWE103", "Customer Payment from JOHN K", D("1500.50")),
    Line(date(2026, 10, 15), "12:00:00", "QWE104", "Withdrawal at agent", D("-500.00")),
    Line(date(2026, 10, 16), "16:45:30", "QWE105", "Customer Payment from MARY A", D("12000.00")),
    Line(date(2026, 10, 17), "07:05:00", "QWE106", "Payment to KPLC bill", D("-3250.25")),
)
MONEY_IN, MONEY_OUT = D("13800.50"), D("5750.25")
BALANCES = (D("10300.00"), D("8300.00"), D("9800.50"), D("9300.50"), D("21300.50"), D("18050.25"))


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def dmy(day: date) -> str:
    return day.strftime("%d/%m/%Y")


# --------------------------------------------------------------------------- PDF drawing
@dataclass
class Col:
    header: str
    x: float
    right: bool = False          # numbers are right-aligned at x; text starts at x


def draw_pdf(columns: list[Col], rows: list[list[str]], *, title: list[str] | None = None, per_page: int = 100,
             repeat_header: bool = True, footer: bool = True, grid: bool = False, password: str | None = None,
             wrap_after: dict[int, str] | None = None, extra_rows: dict[int, list[str]] | None = None,
             header_row: bool = True) -> bytes:
    """A statement PDF. `wrap_after[i]` is text drawn on a line below row i, in the column that holds the details (the
    column named 'Details', 'Narration' or 'Description'). `extra_rows[i]` are additional full rows after row i
    (an opening-balance line, say)."""
    out = io.BytesIO()
    kw = {}
    if password:
        from reportlab.lib.pdfencrypt import StandardEncryption
        kw["encrypt"] = StandardEncryption(password, canPrint=1, strength=128)
    pdf = canvas.Canvas(out, pagesize=A4, **kw)
    height = A4[1]
    wrap_col = next((c for c in columns if c.header in ("Details", "Narration", "Description")), columns[0])
    all_rows: list[tuple[list[str], str | None]] = []
    for i, row in enumerate(rows):
        all_rows.append((row, (wrap_after or {}).get(i)))
        for extra in (extra_rows or {}).get(i, []):
            all_rows.append((extra, None))
    pages = [all_rows[i:i + per_page] for i in range(0, len(all_rows), per_page)] or [[]]
    for number, chunk in enumerate(pages, 1):
        y = height - 60
        pdf.setFont("Helvetica", 9)
        if number == 1 and title:
            for line in title:
                pdf.drawString(50, y, line)
                y -= 16
            y -= 10
        if header_row and (number == 1 or repeat_header):
            pdf.setFont("Helvetica-Bold", 9)
            for col in columns:
                (pdf.drawRightString if col.right else pdf.drawString)(col.x, y, col.header)
            y -= 8
            if grid:
                pdf.line(40, y + 14, columns[-1].x + 10, y + 14)
            y -= 8
        pdf.setFont("Helvetica", 9)
        for cells, wrapped in chunk:
            for col, cell in zip(columns, cells, strict=True):
                if cell:
                    (pdf.drawRightString if col.right else pdf.drawString)(col.x, y, cell)
            if grid:
                pdf.line(40, y - 4, columns[-1].x + 10, y - 4)
            y -= 14
            if wrapped:
                pdf.drawString(wrap_col.x, y, wrapped)
                y -= 14
        if footer:
            pdf.setFont("Helvetica", 8)
            pdf.drawString(50, 30, f"Page {number} of {len(pages)}")
        pdf.showPage()
    pdf.save()
    return out.getvalue()


MPESA_COLS = [Col("Receipt No.", 30), Col("Completion Time", 85), Col("Details", 175), Col("Status", 330),
              Col("Paid In", 432, True), Col("Withdrawn", 490, True), Col("Balance", 565, True)]


def pdf_in_out(password: str | None = None, per_page: int = 100, title: bool = True, **kw: object) -> bytes:
    """Mobile-money style: separate Paid In / Withdrawn columns, a status, a running balance, a title block, a footer."""
    rows = [[t.code, f"{t.day.isoformat()} {t.clock}", t.details, "Completed",
             money(t.amount) if t.amount > 0 else "", money(-t.amount) if t.amount < 0 else "", money(b)]
            for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    cols = MPESA_COLS
    lines = ["MOBILE MONEY FULL STATEMENT", "Customer Name: DEMO TRADERS LTD", "Statement Period: 13/10/2026 - 17/10/2026"]
    return draw_pdf(cols, rows, title=lines if title else None, password=password, per_page=per_page,
                    **kw)  # type: ignore[arg-type]


def pdf_signed() -> bytes:
    """One signed amount column (money out is negative) and a balance; dates written day/month/year."""
    cols = [Col("Date", 50), Col("Description", 120), Col("Amount", 420, True), Col("Balance", 520, True)]
    rows = [[dmy(t.day), t.details, ("-" if t.amount < 0 else "") + money(abs(t.amount)), money(b)]
            for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    return draw_pdf(cols, rows, title=["Account 0123456789 statement", "Printed 18/10/2026"])


def pdf_dr_cr() -> bytes:
    """An unsigned amount with a DR/CR column."""
    cols = [Col("Date", 50), Col("Narration", 115), Col("Ref", 330), Col("Amount", 450, True), Col("Dr/Cr", 480)]
    rows = [[dmy(t.day), t.details, t.code, money(abs(t.amount)), "CR" if t.amount > 0 else "DR"] for t in TRANSACTIONS]
    return draw_pdf(cols, rows, title=["Current account statement"])


def pdf_wrapped() -> bytes:
    """Long details that continue on a second line, in the details column."""
    cols = [Col("Date", 40), Col("Reference", 105), Col("Details", 185), Col("Money In", 440, True),
            Col("Money Out", 500, True), Col("Balance", 570, True)]
    rows = [[dmy(t.day), t.code, t.details, money(t.amount) if t.amount > 0 else "",
             money(-t.amount) if t.amount < 0 else "", money(b)] for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    wraps = {0: "reference 7781 settled by till 3", 3: "cash taken for the driver"}
    return draw_pdf(cols, rows, wrap_after=wraps)


def pdf_three_pages() -> bytes:
    """Title block, the header repeated on 3 pages (two lines per page), 'Page n of 3' footers, an opening-balance line."""
    cols = [Col("Date", 40), Col("Details", 110), Col("Debit", 400, True), Col("Credit", 470, True),
            Col("Balance", 560, True)]
    rows = [[dmy(t.day), f"{t.code} {t.details}", money(-t.amount) if t.amount < 0 else "",
             money(t.amount) if t.amount > 0 else "", money(b)] for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    rows = [["", "Opening balance", "", "", money(OPENING)], *rows]
    return draw_pdf(cols, rows, title=["DEMO BANK", "Statement of account", "Account name: DEMO TRADERS"], per_page=3)


def pdf_ruled() -> bytes:
    """Horizontal rules between rows (a table drawn with lines)."""
    cols = [Col("Date", 50), Col("Description", 120), Col("Amount", 420, True), Col("Balance", 520, True)]
    rows = [[dmy(t.day), t.details, ("-" if t.amount < 0 else "") + money(abs(t.amount)), money(b)]
            for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    return draw_pdf(cols, rows, grid=True)


def pdf_no_header() -> bytes:
    """Lines of text only: date, code, details, amount, balance. No column names anywhere."""
    cols = [Col("", 40), Col("", 110), Col("", 170), Col("", 440, True), Col("", 520, True)]
    rows = [[dmy(t.day), t.code, t.details, ("-" if t.amount < 0 else "") + money(abs(t.amount)), money(b)]
            for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    return draw_pdf(cols, rows, header_row=False, footer=False)


# --------------------------------------------------------------------------- pictures
def render_page(rows: list[list[str]], header: list[str], xs: list[int], *, tilt: float = 0.0, noise: bool = False,
                width: int = 1240, height: int = 800, title: str = "STATEMENT") -> Image.Image:
    """A statement as a picture: text drawn on white paper, optionally tilted and with speckle noise."""
    paper = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(paper)
    font = ImageFont.load_default(size=22)
    draw.text((xs[0], 40), title, fill=0, font=font)
    y = 110
    for line in [header, *rows]:
        for x, cell in zip(xs, line, strict=True):
            if cell:
                draw.text((x, y), cell, fill=0, font=font)
        y += 44
    if noise:
        rnd = random.Random(7)
        for _ in range(900):
            draw.point((rnd.randrange(width), rnd.randrange(height)), fill=rnd.choice((120, 160, 200)))
    return paper.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=255) if tilt else paper


def scan_rows() -> tuple[list[str], list[int], list[list[str]]]:
    header = ["Date", "Details", "Paid In", "Withdrawn", "Balance"]
    xs = [30, 190, 640, 820, 1010]
    rows = [[dmy(t.day), t.details, money(t.amount) if t.amount > 0 else "", money(-t.amount) if t.amount < 0 else "",
             money(b)] for t, b in zip(TRANSACTIONS, BALANCES, strict=True)]
    return header, xs, rows


def png_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format=fmt)
    return out.getvalue()


def pdf_of_image(image: Image.Image) -> bytes:
    """A PDF whose only content is a picture (what a scanner makes)."""
    from reportlab.lib.utils import ImageReader
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=A4)
    pdf.drawImage(ImageReader(image.convert("RGB")), 20, 400, width=555, height=555 * image.height / image.width)
    pdf.showPage()
    pdf.save()
    return out.getvalue()


# --------------------------------------------------------------------------- spreadsheets
def xlsx_in_out(title_rows: int = 3) -> bytes:
    """Excel: a title block, then the table with real dates, real numbers and a totals line at the bottom."""
    from datetime import datetime

    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for i in range(title_rows):
        sheet.append([f"Statement title line {i + 1}"])
    sheet.append([])
    sheet.append(["Receipt No.", "Completion Time", "Details", "Status", "Paid In", "Withdrawn", "Balance"])
    for t, b in zip(TRANSACTIONS, BALANCES, strict=True):
        hour, minute, second = (int(x) for x in t.clock.split(":"))
        sheet.append([t.code, datetime(t.day.year, t.day.month, t.day.day, hour, minute, second), t.details, "Completed",
                      float(t.amount) if t.amount > 0 else None, float(-t.amount) if t.amount < 0 else None, float(b)])
    sheet.append(["", "", "Total", "", float(MONEY_IN), float(MONEY_OUT), None])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def csv_in_out() -> bytes:
    import csv
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Receipt No.", "Completion Time", "Details", "Status", "Paid In", "Withdrawn", "Balance"])
    for t, b in zip(TRANSACTIONS, BALANCES, strict=True):
        writer.writerow([t.code, f"{t.day.isoformat()} {t.clock}", t.details, "Completed",
                         money(t.amount) if t.amount > 0 else "", money(-t.amount) if t.amount < 0 else "", money(b)])
    return out.getvalue().encode()
