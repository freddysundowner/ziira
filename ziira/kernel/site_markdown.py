"""Markdown for the website's pages: rendered to HTML that is safe to put on a public page.

Safety comes from three rules, not from cleaning up afterwards:

- Raw HTML in the Markdown is never passed through (`html=False`): `<script>`, `<iframe>`, `onerror=` and the like come
  out as visible, escaped text.
- A link or image address must be `http`, `https`, `mailto`, `tel`, a site path (`/x`, not `//host`), a fragment, or
  the editor's own image reference `asset:<id>`. Anything else (`javascript:`, `data:`, `vbscript:` ...) is not
  rendered as a link at all, whatever tricks (entities, spaces, control characters, mixed case) hide the scheme.
- The output contains only what the renderer itself writes: tags and attributes are not copied from the input.

`asset:<id>` images are rewritten to the path the site stores the file under (`/media/<id>.<ext>`) by the caller-given
resolver; an unknown id renders no image and is reported by `problems()`.
"""

import re
from collections.abc import Callable
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

ALLOWED_SCHEMES = ("http", "https", "mailto", "tel")
ASSET_SCHEME = "asset:"
_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f​-‏  ﻿]")
_ASSET_ID = re.compile(r"^asset:([0-9a-f]{16})$")

# Words and addresses that mean "someone still has to fill this in".
PLACEHOLDER = re.compile(
    r"\bTODO\b|\bTBD\b|\bFIXME\b|lorem ipsum|\bCHANGE ?ME\b|REPLACE[ _-]?ME|\bXXX+\b|\[\[|\]\]|<<|>>|"
    r"review with your lawyer|example\.invalid|@example\.(?:com|org|net)\b|\bexample\.(?:com|org|net)\b|"
    r"your[- ]company[- ]name",
    re.IGNORECASE)


def is_safe_address(url: str) -> bool:
    """True when `url` may be a link or image address (see the module note)."""
    flat = _CONTROL.sub("", url)
    if not flat:
        return False
    if flat.startswith(("#", "?")):
        return True
    if flat.startswith("/"):
        return not flat.startswith("//") and "\\" not in flat
    if _ASSET_ID.match(flat):
        return True
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", flat)
    if scheme is None:
        return not flat.startswith("\\") and ":" not in flat.split("/")[0]       # a relative path such as "about"
    name = scheme.group(1).lower()
    return name in ALLOWED_SCHEMES and (name in ("mailto", "tel") or "//" in flat[:9])


def _engine() -> MarkdownIt:
    options = {"html": False, "linkify": False, "typographer": False}
    md = MarkdownIt("commonmark", options).enable(["table", "strikethrough"])
    md.validateLink = is_safe_address                                   # type: ignore[method-assign]
    return md


_MD = _engine()


def _walk(tokens: list[Token]) -> list[Token]:
    out: list[Token] = []
    for t in tokens:
        out.append(t)
        if t.children:
            out.extend(_walk(t.children))
    return out


def references(markdown: str) -> dict[str, list[str]]:
    """Every link address and image address in the text (as written, including ones that will not be rendered)."""
    links: list[str] = []
    images: list[str] = []
    for t in _walk(_MD.parse(markdown or "")):
        if t.type == "link_open":
            links.append(str(t.attrGet("href") or ""))
        elif t.type == "image":
            images.append(str(t.attrGet("src") or ""))
    return {"links": links, "images": images}


def raw_references(markdown: str) -> list[str]:
    """Addresses written as Markdown links or images, found by pattern, so ones the parser refused are still seen."""
    return [m.group(1).strip().strip("<>") for m in re.finditer(r"\]\(\s*([^)\s]*)", markdown or "")]


def problems(markdown: str, known_assets: set[str]) -> list[str]:
    """Why a text should not be published: addresses that would be dropped, images that do not exist."""
    found: list[str] = []
    for address in raw_references(markdown):
        if not address:
            found.append("an empty link or image address")
        elif not is_safe_address(address):
            found.append(f"a link that is not allowed: {address[:60]}")
        else:
            match = _ASSET_ID.match(address)
            if match and match.group(1) not in known_assets:
                found.append(f"an image that is not in the media library: {address}")
            elif address.startswith(("http://", "https://")):
                host = urlsplit(address).hostname or ""
                if not host or PLACEHOLDER.search(host):
                    found.append(f"a placeholder address: {address[:60]}")
    return found


def render(markdown: str, resolve_asset: Callable[[str], str | None] | None = None) -> str:
    """HTML for the text. `resolve_asset(id)` gives the path for an `asset:<id>` image, or None when there is none (the
    image is then left out)."""
    tokens = _MD.parse(markdown or "")
    for t in _walk(tokens):
        if t.type == "link_open":
            href = str(t.attrGet("href") or "")
            if href.startswith(("http://", "https://")):
                t.attrSet("rel", "noopener noreferrer")
        elif t.type == "image":
            src = str(t.attrGet("src") or "")
            match = _ASSET_ID.match(src)
            if match:
                path = resolve_asset(match.group(1)) if resolve_asset else None
                if path is None:
                    if resolve_asset is not None:
                        t.attrSet("src", "")
                else:
                    t.attrSet("src", path)
            t.attrSet("loading", "lazy")
    html = _MD.renderer.render(tokens, _MD.options, {})
    return _drop_empty_images(html)


def _drop_empty_images(html: str) -> str:
    return re.sub(r'<img src="" [^>]*>', "", html)


def plain_text(markdown: str) -> str:
    """The words of the text without markup (to check for placeholders and to measure)."""
    parts: list[str] = []
    for t in _walk(_MD.parse(markdown or "")):
        if t.type in ("text", "code_inline", "code_block", "fence"):
            parts.append(t.content)
    return " ".join(parts)


def has_placeholder(text: str) -> str | None:
    """The first placeholder-looking fragment in `text`, or None."""
    match = PLACEHOLDER.search(text or "")
    return match.group(0) if match else None
