"""From a scanned PDF or a photo to rows: render each page, tidy the picture, read the words, rebuild the table.

The engine is whatever is plugged into `connect.ocr_engine`; this code only needs positioned words, so a test can
supply made-up words and the real engine can be swapped. Pillow does the tidying (grey, contrast, size, straighten).
"""

import io
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageOps

from ziira.modules.connect.domain.csvfile import FileProblem
from ziira.modules.connect.domain.tabular import PNG, RawRow, RawTable
from ziira.modules.connect.domain.words import TableBuilder, Word
from ziira.modules.connect.public import OcrEngine

RENDER_DPI = 200
TARGET_WIDTH = 2000
LOW_CONFIDENCE = 60.0
Progress = Callable[[int, int], None]


def deskew(image: Image.Image) -> Image.Image:
    """Straighten a slightly tilted page: the angle (within 5 degrees) at which the rows of text are most distinct."""
    small = image.copy()
    small.thumbnail((700, 700))
    ink = small.point(lambda p: 255 if p < 160 else 0)
    best_angle, best_score = 0.0, -1.0
    for step in range(-10, 11):
        angle = step / 2
        rows = list(ink.rotate(angle, resample=Image.Resampling.BILINEAR)
                    .resize((1, ink.height), Image.Resampling.BOX).tobytes())
        mean = sum(rows) / len(rows)
        score = sum((r - mean) ** 2 for r in rows)
        if score > best_score + 1e-9:
            best_angle, best_score = angle, score
    if abs(best_angle) < 0.3:
        return image
    return image.rotate(best_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)


def prepare(image: Image.Image) -> bytes:
    """A page picture ready for reading: upright, grey, contrasty, big enough, straight. PNG bytes."""
    page = ImageOps.exif_transpose(image).convert("L")
    if page.width < TARGET_WIDTH:
        factor = min(TARGET_WIDTH / page.width, 3.0)
        page = page.resize((int(page.width * factor), int(page.height * factor)), Image.Resampling.LANCZOS)
    page = deskew(ImageOps.autocontrast(page, cutoff=1))
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()


def page_images(data: bytes, kind: str, password: str | None, max_pages: int) -> tuple[int, Callable[[], Any]]:
    """(page count, a generator function of PIL images) for a scanned PDF or a picture file."""
    if kind == "image":
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception:                                                          # noqa: BLE001 - any broken picture
            raise FileProblem("This picture could not be opened. Use a PNG or JPG photo.") from None
        return 1, lambda: iter([image])
    from ziira.modules.connect.domain import pdfreader
    total = pdfreader.page_count(data, password)
    if total > max_pages:
        raise FileProblem(f"This file has {total} pages; at most {max_pages} pages are read from a picture. "
                          "Upload it in parts, or download a text version from your bank.")

    def render() -> Any:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data), password=password or None) as pdf:
            for page in pdf.pages:
                yield page.to_image(resolution=RENDER_DPI).original

    return total, render


def read_pictures(data: bytes, kind: str, engine: OcrEngine, vocabulary: set[str], *, max_pages: int,
                  password: str | None = None, progress: Progress | None = None) -> RawTable:
    """Rows from a scanned PDF or a photo, read with the engine. Raises FileProblem in plain words."""
    total, pages = page_images(data, kind, password, max_pages)
    builder = TableBuilder(vocabulary, low_confidence=LOW_CONFIDENCE)
    before = 0
    ordered: list[RawRow] = []
    for number, image in enumerate(pages(), 1):
        png = prepare(image)
        found = engine.read(png)
        builder.feed([Word(w.text, w.x0, w.x1, w.y0, w.y1, w.confidence) for w in found], number)
        ordered.extend(builder.rows[before:] if builder.header_seen else [])
        before = len(builder.rows)
        if progress is not None:
            progress(number, total)
    rows = ordered if builder.header_seen else builder.result()
    if not rows:
        raise FileProblem("No transactions could be read from the picture. Use a sharper, straight, well-lit photo, "
                          "or download the statement as PDF, Excel or CSV.")
    return RawTable([RawRow(i, r.cells, r.page, r.low_confidence) for i, r in enumerate(rows, 1)], "scan", [
        "This was read from a picture. Check every line against your statement before you confirm."], None, True)


__all__ = ["PNG", "prepare", "read_pictures"]
