"""Pictures and PDFs made in memory for the files tests."""

import io

from PIL import Image


def jpeg(size: tuple[int, int] = (640, 480), *, gps: bool = False, orientation: int | None = None,
         colour: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    image = Image.new("RGB", size, colour)
    exif = Image.Exif()
    if gps:
        exif[0x010F] = "TestCam"                           # make
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1], gps_ifd[2], gps_ifd[3], gps_ifd[4] = "S", (1.0, 17.0, 20.0), "E", (36.0, 49.0, 10.0)
    if orientation:
        exif[0x0112] = orientation
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif.tobytes() if (gps or orientation) else b"")
    return out.getvalue()


def png(size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, (0, 128, 255, 120)).save(out, "PNG")
    return out.getvalue()


def webp(size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (10, 200, 10)).save(out, "WEBP")
    return out.getvalue()


def gif_animated() -> bytes:
    out = io.BytesIO()
    frames = [Image.new("P", (16, 16), i) for i in (1, 2)]
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:])
    return out.getvalue()


def pdf(text: str = "Estimate") -> bytes:
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    page = canvas.Canvas(out)
    page.drawString(72, 720, text)
    page.save()
    return out.getvalue()


def exif_of(raw: bytes) -> dict[int, object]:
    with Image.open(io.BytesIO(raw)) as image:
        exif = image.getexif()
        merged = dict(exif)
        merged.update({k: v for k, v in exif.get_ifd(0x8825).items()})
        return {"gps": dict(exif.get_ifd(0x8825)), **merged}  # type: ignore[dict-item]


def noise_png(side: int = 700) -> bytes:
    """A picture that does not compress: about side * side * 3 bytes."""
    import os

    out = io.BytesIO()
    Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(out, "PNG", compress_level=0)
    return out.getvalue()
