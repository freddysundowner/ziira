"""The default OCR engine: a self-hosted Tesseract program run on the server (nothing is sent anywhere).

Install on the server: `apt install tesseract-ocr` plus a language pack per language (`tesseract-ocr-swa` ...), then
set `ZIIRA_OCR_LANGUAGES` (for example `eng+swa`). `ziira ocr-check` says whether it works.
"""

import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from ziira.modules.connect.public import ConnectorError, OcrEngine, OcrWord
from ziira.sdk import platform_settings

TIMEOUT_SECONDS = 180


class TesseractEngine(OcrEngine):
    name = "tesseract (on this server)"

    def __init__(self) -> None:
        settings = platform_settings()
        self.command = settings.ocr_command.strip() or "tesseract"
        self.languages = settings.ocr_languages.strip() or "eng"

    def unavailable(self) -> str | None:
        program = shutil.which(self.command)
        if program is None:
            return (f"Reading pictures is not switched on on this server yet: the text-reading program "
                    f"'{self.command}' is not installed. Install tesseract-ocr (see docs/operations.md).")
        try:
            listed = subprocess.run([program, "--list-langs"], capture_output=True, text=True, timeout=30,
                                    check=False)
        except (OSError, subprocess.SubprocessError):
            return f"The text-reading program '{self.command}' did not start."
        have = set(listed.stdout.split()[4:]) if listed.returncode == 0 else set()
        missing = [lang for lang in self.languages.split("+") if lang not in have]
        if missing:
            return f"The text-reading program lacks the language pack(s): {', '.join(missing)}."
        return None

    def read(self, image_png: bytes) -> list[OcrWord]:
        program = shutil.which(self.command)
        if program is None:
            raise ConnectorError("Reading pictures is not switched on on this server yet", retryable=False)
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "page.png"
            image.write_bytes(image_png)
            try:
                done = subprocess.run([program, str(image), "stdout", "-l", self.languages, "--psm", "6", "tsv"],
                                      capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired:
                raise ConnectorError("Reading the picture took too long", retryable=False) from None
            except OSError:
                raise ConnectorError("The text-reading program did not start", retryable=False) from None
        if done.returncode != 0:
            raise ConnectorError("The text-reading program failed on this picture", retryable=False)
        return parse_tsv(done.stdout)


def parse_tsv(output: str) -> list[OcrWord]:
    """Words (level 5) from Tesseract's TSV output."""
    words: list[OcrWord] = []
    for row in csv.DictReader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            if row["level"] != "5" or not (row["text"] or "").strip():
                continue
            left, top, width, height = (float(row[k]) for k in ("left", "top", "width", "height"))
            words.append(OcrWord(row["text"].strip(), left, top, left + width, top + height, float(row["conf"])))
        except (KeyError, ValueError, TypeError):
            continue
    return words
