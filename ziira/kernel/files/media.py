"""Reading what a file really is, and cleaning it. Pure functions: no database, no storage.

The type of an upload is decided from its bytes, never from its name or the content type the browser claimed:

* pictures (JPEG, PNG, WebP) must decode with Pillow, are limited in pixels (checked from the header before decoding,
  so a small file that expands to gigabytes is refused) and are never animated;
* PDF must start like a PDF, end like one, parse, and not be password protected.

Everything else (a renamed program, a web page, a Word file ...) is refused with a plain message. This is a check that a
file is what it says it is, not an antivirus (docs/files.md).

Pictures get three forms: the stored original (with the camera's location and every other embedded block removed when
the business keeps that setting on), a web-size copy and a thumbnail. Copies are always re-encoded from the pixels, so
they never carry metadata.
"""

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from ziira.kernel.errors import ValidationFailed

IMAGE_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
PDF = ("application/pdf", "pdf")
MAX_PIXELS = 50_000_000
MAX_SIDE = 16_000
WEB_SIDE = 1600
THUMB_SIDE = 320
MAX_PDF_PAGES = 500
NAME_LIMIT = 120
ACCEPTED_WORDS = "a photo (JPEG, PNG or WebP) or a PDF"


@dataclass(frozen=True)
class Inspected:
    """What an upload turned out to be."""

    kind: str                    # "image" or "pdf"
    content_type: str
    extension: str
    width: int | None = None
    height: int | None = None
    pages: int | None = None


@dataclass(frozen=True)
class Prepared:
    """An upload ready to store: the original (cleaned or not), and for pictures the web copy and the thumbnail."""

    info: Inspected
    original: bytes
    web: bytes | None
    thumb: bytes | None
    location_stripped: bool


def clean_name(name: str, extension: str, fallback: str = "file") -> str:
    """A safe display name: no path, no control characters, at most 120 characters, and an extension that matches the
    real type (a PDF called photo.jpg is shown as photo.pdf)."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = re.sub(r"\s+", " ", stem).strip(" .")[: NAME_LIMIT - 5] or fallback
    return f"{stem}.{extension}"


def _open_image(raw: bytes) -> tuple[Image.Image, str]:
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(raw), formats=list(IMAGE_FORMATS))
        kind = image.format or ""
        width, height = image.size
        if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
            raise ValidationFailed(f"The picture is {width} x {height} pixels; the limit is {MAX_PIXELS // 1_000_000} "
                                   "million pixels. Take it at a lower resolution and try again")
        if getattr(image, "is_animated", False):
            raise ValidationFailed("Animated pictures are not accepted; use a still picture")
        return image, kind
    except ValidationFailed:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError,
            SyntaxError) as error:
        raise ValidationFailed(f"This is not {ACCEPTED_WORDS}") from error
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def _pdf_pages(raw: bytes) -> int:
    from pdfminer.pdfdocument import PDFDocument, PDFPasswordIncorrect
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    if not raw.lstrip(b"\x00\r\n ")[:5] == b"%PDF-" and b"%PDF-" not in raw[:1024]:
        raise ValidationFailed(f"This is not {ACCEPTED_WORDS}")
    if b"%%EOF" not in raw[-4096:]:
        raise ValidationFailed("This PDF looks incomplete (its end is missing). Save it again and retry")
    try:
        document = PDFDocument(PDFParser(io.BytesIO(raw)))
        pages = 0
        for _ in PDFPage.create_pages(document):
            pages += 1
            if pages > MAX_PDF_PAGES:
                raise ValidationFailed(f"This PDF has more than {MAX_PDF_PAGES} pages; split it")
    except PDFPasswordIncorrect:
        raise ValidationFailed("This PDF is password protected; save it without a password") from None
    except ValidationFailed:
        raise
    except Exception as error:                       # pdfminer raises many kinds of error for a broken file
        if error.__class__.__name__ == "PDFEncryptionError":
            raise ValidationFailed("This PDF is password protected; save it without a password") from None
        raise ValidationFailed("This PDF cannot be read; save it again and retry") from error
    if pages < 1:
        raise ValidationFailed("This PDF has no pages")
    return pages


def inspect(raw: bytes) -> Inspected:
    """Decide what the bytes are: a picture or a PDF the system accepts, else ValidationFailed (a plain reason)."""
    if not raw:
        raise ValidationFailed("The file is empty")
    if raw[:5] == b"%PDF-" or b"%PDF-" in raw[:1024]:
        return Inspected("pdf", PDF[0], PDF[1], pages=_pdf_pages(raw))
    image, kind = _open_image(raw)
    try:
        width, height = image.size
    finally:
        image.close()
    content_type, extension = IMAGE_FORMATS[kind]
    return Inspected("image", content_type, extension, width, height)


def _flatten(picture: Image.Image) -> Image.Image:
    """A picture JPEG can hold: transparency shown on white."""
    if picture.mode in ("RGBA", "LA") or (picture.mode == "P" and "transparency" in picture.info):
        rgba = picture.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return picture.convert("RGB")


def _jpeg(picture: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    _flatten(picture).save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _shrink(picture: Image.Image, side: int) -> Image.Image:
    copy = picture.copy()
    copy.thumbnail((side, side), Image.Resampling.LANCZOS)
    return copy


def prepare(raw: bytes, *, strip_location: bool) -> Prepared:
    """Check an upload and make everything that is stored for it. Raises ValidationFailed for what is not accepted.

    With `strip_location` a picture is re-encoded from its pixels (the camera's orientation applied) so no location,
    camera or time information stays in the stored original; otherwise the original bytes are kept as uploaded."""
    info = inspect(raw)
    if info.kind == "pdf":
        return Prepared(info, raw, None, None, False)
    image, kind = _open_image(raw)
    try:
        image.load()
        upright = ImageOps.exif_transpose(image)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValidationFailed(f"This is not {ACCEPTED_WORDS}") from error
    finally:
        image.close()
    original = raw
    if strip_location:
        clean = upright.copy()
        clean.info.clear()
        out = io.BytesIO()
        if kind == "JPEG":
            _flatten(clean).save(out, "JPEG", quality=92, optimize=True)
        elif kind == "PNG":
            clean.save(out, "PNG", optimize=True)
        else:
            clean.save(out, "WEBP", quality=92)
        original = out.getvalue()
    width, height = upright.size
    web = _jpeg(_shrink(upright, WEB_SIDE), 84)
    thumb = _jpeg(_shrink(upright, THUMB_SIDE), 78)
    return Prepared(Inspected("image", info.content_type, info.extension, width, height), original, web, thumb,
                    strip_location)
