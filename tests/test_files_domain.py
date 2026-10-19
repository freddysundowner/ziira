"""Files: reading what an upload really is, cleaning pictures, signed links and the byte store (no database)."""

import io
import time
from uuid import uuid4

import pytest
from PIL import Image

from tests import files_helpers as fx
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.files import media, tokens
from ziira.kernel.files.store import LocalFileStore


# --------------------------------------------------------------------------- what an upload is
@pytest.mark.parametrize(("raw", "kind", "content_type", "ext"), [
    (fx.jpeg(), "image", "image/jpeg", "jpg"), (fx.png(), "image", "image/png", "png"),
    (fx.webp(), "image", "image/webp", "webp"), (fx.pdf(), "pdf", "application/pdf", "pdf"),
])
def test_accepted_types_are_read_from_the_bytes(raw: bytes, kind: str, content_type: str, ext: str) -> None:
    found = media.inspect(raw)
    assert (found.kind, found.content_type, found.extension) == (kind, content_type, ext)
    assert (found.pages == 1) if kind == "pdf" else (found.width and found.height)


@pytest.mark.parametrize("raw", [
    b"", b"MZ\x90\x00" + b"\x00" * 200, b"<html><script>alert(1)</script></html>", b"GIF89a" + b"\x00" * 50,
    fx.jpeg()[:200], b"%PDF-1.4\nnot really a pdf", fx.pdf()[:-30], b"PK\x03\x04" + b"\x00" * 100,
    fx.gif_animated(), b"\x00" * 1000,
])
def test_anything_else_is_refused_with_a_plain_message(raw: bytes) -> None:
    with pytest.raises(ValidationFailed):
        media.inspect(raw)


def test_a_program_or_page_renamed_to_a_photo_is_refused_whatever_it_is_called() -> None:
    with pytest.raises(ValidationFailed, match="not a photo"):
        media.inspect(b"#!/bin/sh\nrm -rf /\n" + b"\x00" * 200)          # name is irrelevant: only bytes are read


def test_a_pdf_is_never_taken_for_a_picture_and_a_picture_never_for_a_pdf() -> None:
    assert media.inspect(fx.pdf()).kind == "pdf"
    assert media.inspect(fx.jpeg()).kind == "image"


def test_too_many_pixels_are_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "MAX_PIXELS", 1000)
    with pytest.raises(ValidationFailed, match="million pixels|not a photo"):
        media.inspect(fx.jpeg((100, 100)))


def test_a_locked_pdf_is_refused() -> None:
    from reportlab.lib import pdfencrypt
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    page = canvas.Canvas(out, encrypt=pdfencrypt.StandardEncryption("secret", canPrint=0))
    page.drawString(10, 10, "x")
    page.save()
    with pytest.raises(ValidationFailed, match="password"):
        media.inspect(out.getvalue())


def test_names_are_made_safe_and_match_the_real_type() -> None:
    assert media.clean_name("../../etc/passwd", "jpg") == "passwd.jpg"
    assert media.clean_name("C:\\Users\\me\\front left.JPEG", "jpg") == "front left.jpg"
    assert media.clean_name("estimate.jpg", "pdf") == "estimate.pdf"                # a PDF called .jpg
    assert media.clean_name("", "png", "photo") == "photo.png"
    assert media.clean_name("a" * 400 + ".png", "png").endswith(".png")
    assert len(media.clean_name("a" * 400, "png")) <= media.NAME_LIMIT
    assert media.clean_name("bad\x00name\n.jpg", "jpg") == "badname.jpg"


# --------------------------------------------------------------------------- cleaning pictures
def test_location_and_camera_information_is_removed_when_asked() -> None:
    raw = fx.jpeg(gps=True)
    assert fx.exif_of(raw)["gps"]                                             # the test picture does carry a position
    done = media.prepare(raw, strip_location=True)
    assert done.location_stripped is True
    assert not fx.exif_of(done.original)["gps"] and 0x010F not in fx.exif_of(done.original)
    assert not fx.exif_of(done.web or b"")["gps"] and not fx.exif_of(done.thumb or b"")["gps"]


def test_the_original_is_kept_as_it_came_when_the_business_wants_that() -> None:
    raw = fx.jpeg(gps=True)
    done = media.prepare(raw, strip_location=False)
    assert done.original == raw and done.location_stripped is False
    assert not fx.exif_of(done.web or b"")["gps"]                              # copies never carry it


def test_the_cameras_orientation_is_applied() -> None:
    done = media.prepare(fx.jpeg((400, 200), orientation=6), strip_location=True)    # rotated a quarter turn
    assert (done.info.width, done.info.height) == (200, 400)
    with Image.open(io.BytesIO(done.original)) as image:
        assert image.size == (200, 400)


def test_copies_have_sensible_sizes() -> None:
    done = media.prepare(fx.jpeg((4000, 3000)), strip_location=True)
    assert done.web and done.thumb
    with Image.open(io.BytesIO(done.web)) as web, Image.open(io.BytesIO(done.thumb)) as thumb:
        assert max(web.size) == media.WEB_SIDE and max(thumb.size) == media.THUMB_SIDE
        assert web.format == "JPEG" == thumb.format
    small = media.prepare(fx.jpeg((100, 80)), strip_location=True)
    with Image.open(io.BytesIO(small.web or b"")) as web:
        assert web.size == (100, 80)                                       # never enlarged


def test_a_transparent_png_gets_jpeg_copies_on_white() -> None:
    done = media.prepare(fx.png(), strip_location=True)
    assert done.info.content_type == "image/png"
    with Image.open(io.BytesIO(done.web or b"")) as web:
        assert web.mode == "RGB"


def test_a_pdf_is_stored_as_it_is_without_copies() -> None:
    raw = fx.pdf()
    done = media.prepare(raw, strip_location=True)
    assert (done.original, done.web, done.thumb, done.location_stripped) == (raw, None, None, False)


# --------------------------------------------------------------------------- signed links
def claims(**over):  # type: ignore[no-untyped-def]
    base = {"tenant_id": uuid4(), "file_id": uuid4(), "variant": "web", "expires": int(time.time()) + 60, "epoch": 0,
            "purpose": "public", "label": "insurer response"}
    return tokens.LinkClaims(**{**base, **over})


def test_a_link_round_trips_and_carries_what_it_was_made_for() -> None:
    c = claims(user_id=uuid4())
    assert tokens.read(tokens.make(c)) == c


@pytest.mark.parametrize("damage", [
    lambda t: t[:-2] + ("aa" if not t.endswith("aa") else "bb"),            # wrong signature
    lambda t: "x" + t, lambda t: t.split(".")[0], lambda t: "", lambda t: "a.b", lambda t: t + "." + t,
])
def test_a_damaged_link_is_the_same_not_found_as_any_other(damage) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NotFound, match="not valid"):
        tokens.read(damage(tokens.make(claims())))


def test_a_link_ends_by_itself_and_cannot_be_given_other_powers() -> None:
    with pytest.raises(NotFound):
        tokens.read(tokens.make(claims(expires=int(time.time()) - 1)))
    with pytest.raises(NotFound):
        tokens.read(tokens.make(claims(variant="secret")))
    with pytest.raises(NotFound):
        tokens.read(tokens.make(claims(purpose="admin")))
    token = tokens.make(claims())
    payload, signature = token.split(".")
    other = tokens.make(claims()).split(".")[0]
    with pytest.raises(NotFound):                                          # a payload with someone else's signature
        tokens.read(f"{other}.{signature}")
    assert payload != other


# --------------------------------------------------------------------------- the byte store
def key(tenant=None, file_id=None, variant="original"):  # type: ignore[no-untyped-def]
    tenant, file_id = tenant or uuid4(), file_id or uuid4()
    return f"{tenant}/{str(file_id)[:2]}/{file_id}.{variant}"


def test_the_store_keeps_deletes_and_lists_bytes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = LocalFileStore(tmp_path)
    tenant, a, b = uuid4(), uuid4(), uuid4()
    store.put(key(tenant, a), b"one")
    store.put(key(tenant, b, "thumb"), b"two")
    assert store.get(key(tenant, a)) == b"one" and store.size(key(tenant, b, "thumb")) == 3
    assert sorted(store.keys(str(tenant))) == sorted([key(tenant, a), key(tenant, b, "thumb")])
    assert store.delete(key(tenant, a)) is True and store.delete(key(tenant, a)) is False
    assert store.size(key(tenant, a)) is None and store.modified(key(tenant, a)) is None
    with pytest.raises(FileNotFoundError):
        store.get(key(tenant, a))


def test_the_store_is_private_and_atomic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = LocalFileStore(tmp_path)
    k = key()
    store.put(k, b"x" * 1000)
    path = tmp_path / k
    assert oct(path.stat().st_mode & 0o777) == "0o600" and oct(path.parent.stat().st_mode & 0o777) == "0o700"
    store.put(k, b"y")                                                     # replaced whole, no partial leftovers
    assert store.get(k) == b"y" and not [p for p in path.parent.iterdir() if p.name.startswith(".part-")]


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "a/b/c.jpg", "x" * 36 + "/../../y",
                                 "", f"{uuid4()}/zz/../../{uuid4()}.original"])
def test_the_store_refuses_keys_that_could_leave_its_folder(tmp_path, bad: str) -> None:  # type: ignore[no-untyped-def]
    store = LocalFileStore(tmp_path / "files")
    for action in (lambda: store.put(bad, b"x"), lambda: store.get(bad), lambda: store.delete(bad)):
        with pytest.raises(ValueError):
            action()
    assert not (tmp_path / "etc").exists()


def test_the_store_says_when_its_folder_cannot_be_written(tmp_path) -> None:  # type: ignore[no-untyped-def]
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    assert LocalFileStore(blocker / "inside").problems()
    assert LocalFileStore(tmp_path / "ok").problems() == []
