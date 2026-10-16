"""Images for the website: checked, re-encoded and stored in the master database.

An upload is never kept as it came. It must decode as PNG, JPEG or WebP (no SVG, GIF, ICO or PDF: they can carry
scripts or animation), be at most `MAX_BYTES` and `MAX_SIDE` pixels on a side and `MAX_PIXELS` in total (checked from
the header, before the picture is decoded, so a small file that expands to gigabytes is refused). It is then re-encoded
from the decoded pixels, which drops EXIF (camera, place, time), comments and every other embedded block, after the
camera's orientation has been applied. The first 16 hex digits of the stored file's SHA-256 name it.
"""

import hashlib
import io
from typing import Any
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text

from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed

MAX_BYTES = 1_500_000
MAX_SIDE = 4096
MAX_PIXELS = 12_000_000
MAX_ASSETS = 300
FORMATS = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def re_encode(raw: bytes) -> tuple[bytes, str, int, int]:
    """The cleaned file, its content type and its width and height; raises ValidationFailed for anything else."""
    if not raw:
        raise ValidationFailed("The file is empty")
    if len(raw) > MAX_BYTES:
        raise ValidationFailed(f"The image is larger than {MAX_BYTES // 1000} KB; make it smaller and try again")
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS                     # only while this upload is read; restored below
    try:
        with Image.open(io.BytesIO(raw), formats=list(FORMATS)) as image:
            kind = image.format or ""
            width, height = image.size
            if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                raise ValidationFailed(f"The image is {width} x {height} pixels; the limit is {MAX_SIDE} on a side "
                                       f"and {MAX_PIXELS // 1_000_000} million pixels in all")
            if getattr(image, "is_animated", False):
                raise ValidationFailed("Animated images are not accepted; use a still picture")
            image.load()
            picture = ImageOps.exif_transpose(image)                    # the camera's orientation, applied
    except ValidationFailed:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError,
            ValueError, SyntaxError) as error:
        raise ValidationFailed("This is not a PNG, JPEG or WebP image") from error
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
    content_type = FORMATS[kind][0]
    picture.info.clear()                                                # EXIF, comments, colour profile, text blocks
    if kind == "JPEG":
        picture = picture.convert("RGB")
    elif picture.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        picture = picture.convert("RGBA" if "A" in picture.getbands() else "RGB")
    out = io.BytesIO()
    if kind == "JPEG":
        picture.save(out, "JPEG", quality=88, optimize=True)
    elif kind == "PNG":
        picture.save(out, "PNG", optimize=True)
    else:
        picture.save(out, "WEBP", quality=88)
    data = out.getvalue()
    return data, content_type, picture.size[0], picture.size[1]


def asset_id(content_hash: str) -> str:
    """The short name used in Markdown (`asset:<id>`) and in file names."""
    return content_hash[:16]


def file_name(row: Any) -> str:
    return f"{asset_id(row.content_hash)}.{EXTENSIONS[row.content_type]}"


def save(raw: bytes, *, name: str, alt: str, by: str) -> dict[str, Any]:
    """Check, clean and store an upload. The same picture twice gives the existing record (409 with its id)."""
    data, content_type, width, height = re_encode(raw)
    digest = hashlib.sha256(data).hexdigest()
    clean_name = (name or "image").strip()[:120] or "image"
    with master_session() as m:
        found = m.execute(text("select id from master.site_asset where content_hash = :h"), {"h": digest}).first()
        if found is not None:
            raise Conflict("This picture is already in the library", {"asset_id": str(found.id)})
        if m.execute(text("select count(*) from master.site_asset")).scalar_one() >= MAX_ASSETS:
            raise ValidationFailed(f"The library holds {MAX_ASSETS} pictures already; remove some first")
        new_id: UUID = m.execute(text(
            "insert into master.site_asset (name, alt, content_type, width, height, size_bytes, content_hash, data, "
            "created_by) values (:n, :a, :c, :w, :h, :s, :x, :d, :by) returning id"),
            {"n": clean_name, "a": alt.strip()[:300], "c": content_type, "w": width, "h": height, "s": len(data),
             "x": digest, "d": data, "by": by}).scalar_one()
    return get(new_id)


def _public(row: Any) -> dict[str, Any]:
    return {"id": row.id, "asset_id": asset_id(row.content_hash), "name": row.name, "alt": row.alt,
            "content_type": row.content_type, "width": row.width, "height": row.height, "size_bytes": row.size_bytes,
            "hash": row.content_hash, "file": file_name(row), "created_at": row.created_at}


_COLUMNS = "id, name, alt, content_type, width, height, size_bytes, content_hash, created_at"


def get(asset: UUID) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text(f"select {_COLUMNS} from master.site_asset where id = :i"), {"i": str(asset)}).first()
    if row is None:
        raise NotFound("No such picture")
    return _public(row)


def listing() -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(text(f"select {_COLUMNS} from master.site_asset order by created_at desc"))
        return [_public(r) for r in rows]


def set_alt(asset: UUID, alt: str) -> dict[str, Any]:
    with master_session() as m:
        if not m.execute(text("update master.site_asset set alt = :a where id = :i returning id"),
                         {"a": alt.strip()[:300], "i": str(asset)}).first():
            raise NotFound("No such picture")
    return get(asset)


def remove(asset: UUID) -> None:
    with master_session() as m:
        if not m.execute(text("delete from master.site_asset where id = :i returning id"), {"i": str(asset)}).first():
            raise NotFound("No such picture")


def content(asset: UUID) -> tuple[bytes, str]:
    """The stored file and its content type (for the operator's own preview)."""
    with master_session() as m:
        row = m.execute(text("select data, content_type from master.site_asset where id = :i"),
                        {"i": str(asset)}).first()
    if row is None:
        raise NotFound("No such picture")
    return bytes(row.data), row.content_type


def content_by_hash_prefix(short_id: str) -> tuple[bytes, str] | None:
    with master_session() as m:
        row = m.execute(text("select data, content_type from master.site_asset where left(content_hash, 16) = :h"),
                        {"h": short_id}).first()
    return (bytes(row.data), row.content_type) if row else None
