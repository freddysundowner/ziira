"""The marketing website's editable facts and pages (docs/platform-admin-content.md).

What lives here
- **Settings**: a fixed, typed list (`SETTINGS`): company names, contact details, social handles, SEO defaults, logo
  and favicon, analytics (off by default), cookie notice, links, announcement banner, languages. Values are checked
  when they are saved; nothing in the list is secret, because everything in it is meant to appear on the public site.
- **Pages**: legal and simple content pages in Markdown, per language, with an immutable version history.
- **Publishing**: the public site never reads the working copies. An explicit publish freezes the settings, the
  published pages (rendered to safe HTML, see site_markdown.py) and the pictures they use into one snapshot
  (`master.site_publish`); `GET /api/v1/public/site` serves the newest snapshot. Drafts, unsaved ideas and operator
  data cannot reach it, because it is built from the lists below and nothing else.

Nothing here assumes a country: phone numbers need an international `+` prefix; currencies and prices come from plans.
"""

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import site_assets, site_markdown, site_templates
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed

LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EMAIL = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]+\.[^@\s<>]{2,}$")
PHONE = re.compile(r"^\+[0-9][0-9 ()\-.]{5,28}$")
HANDLE = re.compile(r"^@?[A-Za-z0-9._-]{1,60}(/[A-Za-z0-9._-]{1,60})?$")
ANALYTICS_ID = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
LEGAL_SLUGS = site_templates.LEGAL_SLUGS
DEFAULT_LOCALES = ["en", "sw"]
MAX_LOCALES = 6
MAX_PAGES = 200
MAX_BODY = 120_000

SOCIAL_URLS = {
    "x": "https://x.com/{}", "linkedin": "https://www.linkedin.com/company/{}", "facebook": "https://www.facebook.com/{}",
    "instagram": "https://www.instagram.com/{}", "youtube": "https://www.youtube.com/@{}",
    "tiktok": "https://www.tiktok.com/@{}", "github": "https://github.com/{}",
}


@dataclass(frozen=True)
class Setting:
    """One editable fact: its key, where the form shows it, what kind of value it is and how it may be used."""

    key: str
    group: str
    kind: str          # text longtext email url phone phones handle asset bool datetime locales contact
    required: bool = False
    max_len: int = 200
    localised: bool = False


SETTINGS: tuple[Setting, ...] = (
    Setting("company_legal_name", "company", "text", required=True, max_len=160),
    Setting("company_trading_name", "company", "text", max_len=120),
    Setting("tagline", "company", "text", max_len=160, localised=True),
    Setting("registration_number", "company", "text", max_len=80),
    Setting("tax_id", "company", "text", max_len=80),
    Setting("postal_address", "company", "longtext", max_len=400),
    Setting("support_email", "contact", "email", required=True),
    Setting("sales_email", "contact", "email"),
    Setting("phones", "contact", "phones"),
    Setting("whatsapp_number", "contact", "phone"),
    Setting("contact_form_target", "contact", "contact"),
    *(Setting(f"social_{name}", "social", "handle") for name in SOCIAL_URLS),
    Setting("seo_title_template", "seo", "text", max_len=120, localised=True),
    Setting("seo_description", "seo", "text", max_len=300, localised=True),
    Setting("og_image", "seo", "asset"),
    Setting("logo", "branding", "asset"),
    Setting("favicon", "branding", "asset"),
    Setting("analytics_enabled", "analytics", "bool"),
    Setting("analytics_id", "analytics", "text", max_len=64),
    Setting("cookie_notice_text", "analytics", "longtext", max_len=600, localised=True),
    Setting("app_url", "links", "url"),
    Setting("status_page_url", "links", "url"),
    Setting("banner_active", "banner", "bool"),
    Setting("banner_text", "banner", "text", max_len=200, localised=True),
    Setting("banner_link", "banner", "url"),
    Setting("banner_starts_at", "banner", "datetime"),
    Setting("banner_ends_at", "banner", "datetime"),
    Setting("locales", "site", "locales"),
)
BY_KEY = {s.key: s for s in SETTINGS}


# --------------------------------------------------------------------------- checking one value
def _text(value: Any, limit: int, *, multiline: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Enter text")
    clean = value.strip() if multiline else " ".join(value.split())
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", clean):
        raise ValueError("Contains characters that are not allowed")
    if len(clean) > limit:
        raise ValueError(f"At most {limit} characters")
    return clean or None


def _url(value: str, *, allow_path: bool = False) -> str:
    if allow_path and value.startswith("/") and not value.startswith("//"):
        return value
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc or re.search(r"\s", value):
        raise ValueError("Enter a full web address starting with https://")
    if len(value) > 500:
        raise ValueError("At most 500 characters")
    return value


def _email(value: str) -> str:
    if not EMAIL.match(value) or len(value) > 250:
        raise ValueError("Enter an email address like name@company.com")
    return value.lower()


def _phone(value: str) -> str:
    if not PHONE.match(value) or not 7 <= sum(c.isdigit() for c in value) <= 15:
        raise ValueError("Enter the number in international form, starting with + and the country calling code")
    return " ".join(value.split())


def _single(setting: Setting, value: Any) -> Any:
    """Check one non-localised value; None, empty text and empty lists mean 'not set'."""
    kind = setting.kind
    if kind in ("text", "longtext"):
        clean = _text(value, setting.max_len, multiline=kind == "longtext")
        if clean and setting.key == "analytics_id" and not ANALYTICS_ID.match(clean):
            raise ValueError("Letters, digits, dots, dashes and underscores only")
        if clean and setting.key == "seo_title_template" and "{title}" not in clean:
            raise ValueError("Must contain {title}, where the page title goes")
        return clean
    if kind == "bool":
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("Must be true or false")
        return value
    if kind == "phones":
        if value in (None, []):
            return None
        if not isinstance(value, list) or len(value) > 5:
            raise ValueError("A list of at most 5 phone numbers")
        cleaned = [_phone(_text(v, 40) or "") for v in value if _text(v, 40)]
        return cleaned or None
    if kind == "locales":
        if value in (None, []):
            return None
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_LOCALES or len(set(value)) != len(value):
            raise ValueError(f"One to {MAX_LOCALES} different language codes")
        if not all(isinstance(v, str) and LOCALE.match(v) for v in value):
            raise ValueError("Language codes look like en, sw or pt-BR")
        return list(value)
    if kind == "asset":
        if value in (None, ""):
            return None
        try:
            asset = site_assets.get(UUID(str(value)))
        except (ValueError, NotFound):
            raise ValueError("Pick a picture from the media library") from None
        return str(asset["id"])
    if kind == "datetime":
        raw = _text(value, 40)
        if raw is None:
            return None
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Enter a date and time like 2026-12-01T09:00:00+00:00") from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat()
    raw = _text(value, setting.max_len)
    if raw is None:
        return None
    if kind == "email":
        return _email(raw)
    if kind == "phone":
        return _phone(raw)
    if kind == "url":
        return _url(raw, allow_path=setting.key == "banner_link")
    if kind == "handle":
        if HANDLE.match(raw):
            return raw
        return _url(raw)
    if kind == "contact":
        return _email(raw) if "@" in raw and not raw.startswith("http") else _url(raw)
    raise ValueError("Unknown kind of setting")


def clean_value(setting: Setting, value: Any) -> Any:
    """The checked, normalised value (None = not set). Raises ValueError with a message the form can show."""
    if not setting.localised:
        return _single(setting, value)
    if value in (None, {}, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("Enter the text for each language")
    out: dict[str, str] = {}
    for locale, entry in value.items():
        if not isinstance(locale, str) or not LOCALE.match(locale):
            raise ValueError(f"'{str(locale)[:12]}' is not a language code")
        clean = _single(Setting(setting.key, setting.group, setting.kind, max_len=setting.max_len), entry)
        if clean:
            out[locale] = str(clean)
    return out or None


def schema() -> list[dict[str, Any]]:
    """The settings the form shows."""
    return [{"key": s.key, "group": s.group, "kind": s.kind, "required": s.required, "max_len": s.max_len,
             "localised": s.localised} for s in SETTINGS]


# --------------------------------------------------------------------------- settings
def settings_values() -> dict[str, Any]:
    with master_session() as m:
        return {r.key: r.value for r in m.execute(text("select key, value from master.site_setting"))}


def save_settings(values: dict[str, Any], *, by: str) -> list[str]:
    """Check and save the given settings (all or nothing). A value of null or empty clears a setting. Returns the keys
    whose value changed."""
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}
    for key, raw in values.items():
        setting = BY_KEY.get(key)
        if setting is None:
            errors[key] = "This is not a website setting"
            continue
        try:
            cleaned[key] = clean_value(setting, raw)
        except ValueError as error:
            errors[key] = str(error)
    current = settings_values()
    merged = {**current, **{k: v for k, v in cleaned.items() if v is not None}}
    for key in [k for k, v in cleaned.items() if v is None]:
        merged.pop(key, None)
    start, end = merged.get("banner_starts_at"), merged.get("banner_ends_at")
    if start and end and end <= start and ("banner_ends_at" in cleaned or "banner_starts_at" in cleaned):
        errors["banner_ends_at"] = "The banner must end after it starts"
    if errors:
        raise ValidationFailed("Some settings are not valid", {"fields": errors})
    changed = [k for k, v in cleaned.items() if current.get(k) != v]
    with master_session() as m:
        for key in changed:
            if cleaned[key] is None:
                m.execute(text("delete from master.site_setting where key = :k"), {"k": key})
            else:
                m.execute(text(
                    "insert into master.site_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
                    "on conflict (key) do update set value = excluded.value, updated_at = now(), "
                    "updated_by = excluded.updated_by"), {"k": key, "v": json.dumps(cleaned[key]), "b": by})
    return changed


def locales_enabled(values: dict[str, Any] | None = None) -> list[str]:
    return list((values if values is not None else settings_values()).get("locales") or DEFAULT_LOCALES)


# --------------------------------------------------------------------------- pages
_PAGE_COLUMNS = ("id, slug, locale, kind, title, body_md, seo_title, seo_description, status, version, updated_by, "
                 "created_at, updated_at")


def _page_dict(row: Any, *, body: bool = True) -> dict[str, Any]:
    out = {"id": row.id, "slug": row.slug, "locale": row.locale, "kind": row.kind, "title": row.title,
           "seo_title": row.seo_title, "seo_description": row.seo_description, "status": row.status,
           "version": row.version, "updated_by": row.updated_by, "created_at": row.created_at,
           "updated_at": row.updated_at}
    if body:
        out["body_md"] = row.body_md
    else:
        out["body_length"] = len(row.body_md)
    return out


def _clean_page(title: str, body_md: str, seo_title: str | None, seo_description: str | None) -> tuple[str, ...]:
    t = _text(title, 160)
    if not t:
        raise ValidationFailed("A page needs a title")
    if len(body_md or "") > MAX_BODY:
        raise ValidationFailed(f"The text is longer than {MAX_BODY // 1000} thousand characters")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", body_md or ""):
        raise ValidationFailed("The text contains characters that are not allowed")
    try:
        st, sd = _text(seo_title, 120), _text(seo_description, 300)
    except ValueError as error:
        raise ValidationFailed(str(error)) from None
    return t, (body_md or "").replace("\r\n", "\n"), st or "", sd or ""


def _version_row(m: Any, page_id: Any, version: int, title: str, body: str, st: str | None, sd: str | None,
                 status: str, note: str | None, by: str) -> None:
    m.execute(text(
        "insert into master.site_page_version (page_id, version, title, body_md, seo_title, seo_description, status, "
        "note, created_by) values (:p, :v, :t, :b, :st, :sd, :s, :n, :by)"),
        {"p": str(page_id), "v": version, "t": title, "b": body, "st": st, "sd": sd, "s": status,
         "n": (note or "")[:300] or None, "by": by})


def create_page(*, slug: str, locale: str, kind: str, title: str, body_md: str, seo_title: str | None,
                seo_description: str | None, by: str) -> dict[str, Any]:
    if not SLUG.match(slug or "") or len(slug) > 60:
        raise ValidationFailed("The address part must be lowercase letters, digits and single dashes (at most 60)")
    if not LOCALE.match(locale or ""):
        raise ValidationFailed("Language codes look like en, sw or pt-BR")
    if kind not in ("legal", "content"):
        raise ValidationFailed("Kind is legal or content")
    t, body, st, sd = _clean_page(title, body_md, seo_title, seo_description)
    with master_session() as m:
        if m.execute(text("select count(*) from master.site_page")).scalar_one() >= MAX_PAGES:
            raise ValidationFailed(f"There are {MAX_PAGES} pages already")
        if m.execute(text("select 1 from master.site_page where slug = :s and locale = :l"),
                     {"s": slug, "l": locale}).first():
            raise Conflict("There is already a page with this address in this language")
        row = m.execute(text(
            "insert into master.site_page (slug, locale, kind, title, body_md, seo_title, seo_description, updated_by) "
            "values (:s, :l, :k, :t, :b, :st, :sd, :by) returning " + _PAGE_COLUMNS),
            {"s": slug, "l": locale, "k": kind, "t": t, "b": body, "st": st or None, "sd": sd or None,
             "by": by}).one()
        _version_row(m, row.id, 1, t, body, st or None, sd or None, "draft", "Created", by)
    return _page_dict(row)


def _load_page(m: Any, page_id: UUID, *, lock: bool = False) -> Any:
    sql = f"select {_PAGE_COLUMNS} from master.site_page where id = :i" + (" for update" if lock else "")
    row = m.execute(text(sql), {"i": str(page_id)}).first()
    if row is None:
        raise NotFound("No such page")
    return row


def _state_of(status: str, key: str, states: dict[str, str], live: set[str]) -> str:
    """draft | new | live | changed | unpublish_pending: how the page stands against the live site."""
    if status == "published":
        return states.get(key, "new")
    return "unpublish_pending" if key in live else "draft"


def _stated(page: dict[str, Any]) -> dict[str, Any]:
    page["state"] = _state_of(page["status"], _key(page["slug"], page["locale"]), _states(), _live_keys())
    return page


def get_page(page_id: UUID) -> dict[str, Any]:
    with master_session() as m:
        page = _page_dict(_load_page(m, page_id))
    return _stated(page)


def update_page(page_id: UUID, *, expected_version: int, title: str, body_md: str, seo_title: str | None,
                seo_description: str | None, note: str | None, by: str) -> dict[str, Any]:
    """Save new content as the next version. `expected_version` is what the editor loaded: if someone saved since,
    nothing is overwritten (409)."""
    t, body, st, sd = _clean_page(title, body_md, seo_title, seo_description)
    with master_session() as m:
        row = _load_page(m, page_id, lock=True)
        if row.version != expected_version:
            raise Conflict("Someone saved this page after you opened it. Reload it to see their changes",
                           {"current_version": row.version})
        if (t, body, st, sd) == (row.title, row.body_md, row.seo_title or "", row.seo_description or ""):
            return _stated(_page_dict(row))
        version = row.version + 1
        saved = m.execute(text(
            "update master.site_page set title = :t, body_md = :b, seo_title = :st, seo_description = :sd, "
            "version = :v, updated_by = :by, updated_at = now() where id = :i returning " + _PAGE_COLUMNS),
            {"t": t, "b": body, "st": st or None, "sd": sd or None, "v": version, "by": by, "i": str(page_id)}).one()
        _version_row(m, page_id, version, t, body, st or None, sd or None, row.status, note or "Edited", by)
    return _stated(_page_dict(saved))


def set_page_status(page_id: UUID, status: str, *, by: str) -> dict[str, Any]:
    """Mark a page published (goes live with the next site publish) or draft (leaves with the next site publish)."""
    if status not in ("draft", "published"):
        raise ValidationFailed("Status is draft or published")
    with master_session() as m:
        row = _load_page(m, page_id, lock=True)
        if row.status == status:
            return _stated(_page_dict(row))
        version = row.version + 1
        saved = m.execute(text(
            "update master.site_page set status = :s, version = :v, updated_by = :by, updated_at = now() "
            "where id = :i returning " + _PAGE_COLUMNS), {"s": status, "v": version, "by": by, "i": str(page_id)}).one()
        _version_row(m, page_id, version, row.title, row.body_md, row.seo_title, row.seo_description, status,
                     "Marked published" if status == "published" else "Marked draft", by)
    return _stated(_page_dict(saved))


def delete_page(page_id: UUID) -> dict[str, Any]:
    with master_session() as m:
        row = _load_page(m, page_id, lock=True)
        if row.status != "draft":
            raise Conflict("Mark the page as draft first")
        if _key(row.slug, row.locale) in _live_keys():
            raise Conflict("This page is on the live site. Publish the site without it first, then delete it")
        m.execute(text("delete from master.site_page where id = :i"), {"i": str(page_id)})
    return {"slug": row.slug, "locale": row.locale}


def list_pages(locale: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(text(
            f"select {_PAGE_COLUMNS} from master.site_page where (cast(:l as text) is null or locale = :l) "
            "and (cast(:k as text) is null or kind = :k) order by kind, slug, locale"), {"l": locale, "k": kind}).all()
    states, live = _states(), _live_keys()
    out = []
    for r in rows:
        page = _page_dict(r, body=False)
        key = _key(r.slug, r.locale)
        page["state"] = _state_of(r.status, key, states, live)
        out.append(page)
    return out


def list_versions(page_id: UUID) -> list[dict[str, Any]]:
    with master_session() as m:
        _load_page(m, page_id)
        rows = m.execute(text(
            "select version, title, status, note, created_at, created_by, length(body_md) as body_length "
            "from master.site_page_version where page_id = :p order by version desc"), {"p": str(page_id)})
        return [dict(r._mapping) for r in rows]


def _version(m: Any, page_id: UUID, version: int) -> Any:
    row = m.execute(text("select version, title, body_md, seo_title, seo_description, status, note, created_at, "
                         "created_by from master.site_page_version where page_id = :p and version = :v"),
                    {"p": str(page_id), "v": version}).first()
    if row is None:
        raise NotFound("No such version")
    return row


def get_version(page_id: UUID, version: int) -> dict[str, Any]:
    with master_session() as m:
        return dict(_version(m, page_id, version)._mapping)


def diff_versions(page_id: UUID, older: int, newer: int) -> dict[str, Any]:
    """A unified text diff of two versions (title, address texts, body)."""
    with master_session() as m:
        a, b = _version(m, page_id, older), _version(m, page_id, newer)

    def lines(v: Any) -> list[str]:
        return [f"# title: {v.title}", f"# seo title: {v.seo_title or ''}",
                f"# seo description: {v.seo_description or ''}", "", *v.body_md.split("\n")]

    diff = list(difflib.unified_diff(lines(a), lines(b), f"version {older}", f"version {newer}", lineterm="", n=2))
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    return {"older": older, "newer": newer, "diff": "\n".join(diff), "added": added, "removed": removed}


def restore_version(page_id: UUID, version: int, *, by: str) -> dict[str, Any]:
    """Copy an old version's content into a new version (history is never rewritten). The status stays as it is."""
    with master_session() as m:
        old = _version(m, page_id, version)
        row = _load_page(m, page_id, lock=True)
        new_version = row.version + 1
        saved = m.execute(text(
            "update master.site_page set title = :t, body_md = :b, seo_title = :st, seo_description = :sd, "
            "version = :v, updated_by = :by, updated_at = now() where id = :i returning " + _PAGE_COLUMNS),
            {"t": old.title, "b": old.body_md, "st": old.seo_title, "sd": old.seo_description, "v": new_version,
             "by": by, "i": str(page_id)}).one()
        _version_row(m, page_id, new_version, old.title, old.body_md, old.seo_title, old.seo_description, row.status,
                     f"Restored from version {version}", by)
    return _stated(_page_dict(saved))


def preview(markdown: str) -> str:
    """The safe HTML for a text (pictures from the library show their text, as they are not public yet)."""
    if len(markdown or "") > MAX_BODY:
        raise ValidationFailed("The text is too long")
    return site_markdown.render(markdown)


def starter_pages(locale: str) -> list[dict[str, str]]:
    if not LOCALE.match(locale or ""):
        raise ValidationFailed("Language codes look like en, sw or pt-BR")
    return site_templates.starters(locale)


# --------------------------------------------------------------------------- the snapshot
def _key(slug: str, locale: str) -> str:
    return f"{locale}/{slug}"


def _asset_rows() -> list[Any]:
    with master_session() as m:
        return list(m.execute(text(
            "select id, name, alt, content_type, width, height, content_hash from master.site_asset")))


class _Working:
    """The working copy as one consistent reading: settings, published pages and the library's pictures."""

    def __init__(self) -> None:
        self.settings = settings_values()
        with master_session() as m:
            self.pages = list(m.execute(text(
                f"select {_PAGE_COLUMNS} from master.site_page where status = 'published' "
                "order by kind, slug, locale")))
            self.all_pages = list(m.execute(text("select slug, locale, kind, status from master.site_page")))
        rows = _asset_rows()
        self.assets_by_id = {str(r.id): r for r in rows}
        self.assets_by_short = {site_assets.asset_id(r.content_hash): r for r in rows}
        self.used: dict[str, Any] = {}

    def asset(self, row: Any) -> dict[str, Any]:
        entry = {"path": f"/media/{site_assets.file_name(row)}", "hash": row.content_hash, "width": row.width,
                 "height": row.height, "alt": row.alt, "content_type": row.content_type,
                 "download": f"/api/v1/public/site/assets/{site_assets.file_name(row)}"}
        self.used[entry["path"]] = entry
        return entry

    def resolve_markdown_asset(self, short_id: str) -> str | None:
        row = self.assets_by_short.get(short_id)
        return self.asset(row)["path"] if row is not None else None

    def asset_setting(self, key: str) -> dict[str, Any] | None:
        row = self.assets_by_id.get(str(self.settings.get(key) or ""))
        return self.asset(row) if row is not None else None


def _social(settings: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name, template in SOCIAL_URLS.items():
        value = settings.get(f"social_{name}")
        if value:
            url = value if value.startswith("http") else template.format(value.lstrip("@"))
            handle = value if not value.startswith("http") else urlsplit(value).path.strip("/").split("/")[-1]
            out[name] = {"handle": handle, "url": url}
    return out


def _public_settings(w: _Working) -> dict[str, Any]:
    s = w.settings
    locales = locales_enabled(s)
    digits = re.sub(r"\D", "", s.get("whatsapp_number") or "")
    analytics_on = bool(s.get("analytics_enabled") and s.get("analytics_id"))
    banner = None
    if s.get("banner_active") and s.get("banner_text"):
        banner = {"text": s["banner_text"], "link": s.get("banner_link"), "starts_at": s.get("banner_starts_at"),
                  "ends_at": s.get("banner_ends_at")}
    return {
        "company": {"legal_name": s.get("company_legal_name"), "trading_name": s.get("company_trading_name"),
                    "tagline": s.get("tagline") or {}, "registration_number": s.get("registration_number"),
                    "tax_id": s.get("tax_id"), "postal_address": s.get("postal_address")},
        "contact": {"support_email": s.get("support_email"), "sales_email": s.get("sales_email"),
                    "phones": s.get("phones") or [],
                    "whatsapp": {"number": s["whatsapp_number"], "link": f"https://wa.me/{digits}"}
                    if s.get("whatsapp_number") else None,
                    "form_target": s.get("contact_form_target")},
        "social": _social(s),
        "seo": {"title_template": s.get("seo_title_template") or {}, "description": s.get("seo_description") or {},
                "og_image": w.asset_setting("og_image")},
        "branding": {"logo": w.asset_setting("logo"), "favicon": w.asset_setting("favicon")},
        "analytics": {"id": s["analytics_id"]} if analytics_on else None,
        "cookie_notice": s.get("cookie_notice_text") or {},
        "links": {"app_url": s.get("app_url"), "status_page_url": s.get("status_page_url")},
        "banner": banner,
        "locales": locales,
        "default_locale": locales[0],
    }


def _snapshot(w: _Working) -> dict[str, Any]:
    settings = _public_settings(w)
    pages = []
    for p in w.pages:
        pages.append({"slug": p.slug, "locale": p.locale, "kind": p.kind, "title": p.title,
                      "html": site_markdown.render(p.body_md, w.resolve_markdown_asset), "markdown": p.body_md,
                      "seo": {"title": p.seo_title, "description": p.seo_description},
                      "updated_at": p.updated_at.astimezone(UTC).isoformat(), "version": p.version})
    return {"settings": settings, "pages": pages, "assets": sorted(w.used.values(), key=lambda a: str(a["path"]))}


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def current_publication() -> dict[str, Any] | None:
    with master_session() as m:
        row = m.execute(text("select id, published_at, published_by, note, version_hash, snapshot "
                             "from master.site_publish order by id desc limit 1")).first()
    return dict(row._mapping) if row else None


def _live_keys() -> set[str]:
    live = current_publication()
    return {_key(p["slug"], p["locale"]) for p in live["snapshot"]["pages"]} if live else set()


def _states() -> dict[str, str]:
    """For each published page: live (same as on the site), changed (edited since) or new (not on the site yet)."""
    live = current_publication()
    on_site = {_key(p["slug"], p["locale"]): p for p in live["snapshot"]["pages"]} if live else {}
    out: dict[str, str] = {}
    with master_session() as m:
        for r in m.execute(text("select slug, locale, title, body_md, seo_title, seo_description from master.site_page "
                                "where status = 'published'")):
            then = on_site.get(_key(r.slug, r.locale))
            if then is None:
                out[_key(r.slug, r.locale)] = "new"
            else:
                same = (then["title"], then["markdown"], then["seo"]["title"], then["seo"]["description"]) == (
                    r.title, r.body_md, r.seo_title, r.seo_description)
                out[_key(r.slug, r.locale)] = "live" if same else "changed"
    return out


def _content(entry: dict[str, Any]) -> dict[str, Any]:
    """A published page as it reads, without when it was saved."""
    return {k: v for k, v in entry.items() if k != "updated_at"}


def pending_changes() -> list[dict[str, str]]:
    """What a publish would change on the live site: settings groups, pages added, changed or taken down."""
    working = _snapshot(_Working())
    live = current_publication()
    before = live["snapshot"] if live else {"settings": {}, "pages": [], "assets": []}
    changes: list[dict[str, str]] = []
    for area in sorted(set(working["settings"]) | set(before["settings"])):
        if working["settings"].get(area) != before["settings"].get(area):
            changes.append({"area": "settings", "ref": area, "change": "changed"})
    now = {_key(p["slug"], p["locale"]): p for p in working["pages"]}
    then = {_key(p["slug"], p["locale"]): p for p in before["pages"]}
    for key in sorted(set(now) | set(then)):
        if key not in then:
            changes.append({"area": "page", "ref": key, "change": "added"})
        elif key not in now:
            changes.append({"area": "page", "ref": key, "change": "removed"})
        elif _content(now[key]) != _content(then[key]):
            changes.append({"area": "page", "ref": key, "change": "changed"})
    return changes


# --------------------------------------------------------------------------- the check before publishing
def _issue(code: str, message: str, where: str) -> dict[str, str]:
    return {"code": code, "message": message, "where": where}


def validate() -> dict[str, Any]:
    """Whether the working copy may be published: `errors` block a publish, `warnings` do not."""
    w = _Working()
    s = w.settings
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    locales = locales_enabled(s)

    for key in ("company_legal_name", "support_email"):
        if not s.get(key):
            errors.append(_issue("required", "This is needed before the site can be published", key))
    for key, value in s.items():
        for fragment in _strings(value):
            found = site_markdown.has_placeholder(fragment)
            if found:
                errors.append(_issue("placeholder", f"Still holds placeholder text ({found})", key))
                break
        if isinstance(value, str) and value.startswith("http://") and urlsplit(value).hostname not in (
                "localhost", "127.0.0.1"):
            warnings.append(_issue("insecure_link", "Uses http, not https", key))
    for key in ("phones", "whatsapp_number"):
        for number in ([s[key]] if isinstance(s.get(key), str) else s.get(key) or []):
            digits = re.sub(r"\D", "", number)
            if len(set(digits)) <= 2:
                errors.append(_issue("placeholder", "This looks like a dummy phone number", key))
    if s.get("analytics_enabled") and not s.get("analytics_id"):
        errors.append(_issue("required", "Analytics is switched on but has no ID", "analytics_id"))
    if s.get("analytics_enabled") and not s.get("cookie_notice_text"):
        errors.append(_issue("required", "Write the cookie notice before switching analytics on", "cookie_notice_text"))
    if s.get("banner_active") and not s.get("banner_text"):
        errors.append(_issue("required", "The banner is on but has no text", "banner_text"))
    for key, label in (("sales_email", "A sales email"), ("phones", "A phone number"),
                       ("postal_address", "A postal address"), ("logo", "A logo"),
                       ("og_image", "A default social-sharing image"), ("seo_description", "A default description")):
        if not s.get(key):
            warnings.append(_issue("missing_optional", f"{label} is not set", key))
    for locale in locales:
        for key in ("tagline", "seo_description", "seo_title_template"):
            if isinstance(s.get(key), dict) and locale not in s[key]:
                warnings.append(_issue("missing_translation", f"No {locale} text", key))

    published = {(p.slug, p.locale): p for p in w.pages}
    for locale in locales:
        for slug in LEGAL_SLUGS:
            if (slug, locale) not in published:
                errors.append(_issue("legal_missing", f"The {slug} page is not published in '{locale}'",
                                     f"{locale}/{slug}"))
    for (slug, locale), p in published.items():
        where = _key(slug, locale)
        if locale not in locales:
            warnings.append(_issue("locale_off", f"'{locale}' is not an enabled language; the page is published anyway",
                                   where))
        else:
            for other in locales:
                if (slug, other) not in published:
                    errors.append(_issue("counterpart_missing", f"No published '{other}' version of this page "
                                         "(alternate-language links need both)", where))
        for part_name, part in (("title", p.title), ("body", site_markdown.plain_text(p.body_md)),
                                ("seo title", p.seo_title or ""), ("seo description", p.seo_description or "")):
            found = site_markdown.has_placeholder(part)
            if found:
                errors.append(_issue("placeholder", f"The {part_name} still holds placeholder text ({found})", where))
                break
        for problem in site_markdown.problems(p.body_md, set(w.assets_by_short)):
            errors.append(_issue("bad_link", problem, where))
        if p.kind == "legal" and len(site_markdown.plain_text(p.body_md)) < 200:
            warnings.append(_issue("short_legal", "A legal page this short is unlikely to be complete", where))
        if p.seo_title and len(p.seo_title) > 60:
            warnings.append(_issue("seo_length", "The search title is longer than 60 characters", where))
        if p.seo_description and len(p.seo_description) > 160:
            warnings.append(_issue("seo_length", "The search description is longer than 160 characters", where))
        if not p.seo_description:
            warnings.append(_issue("seo_missing", "No search description: the site uses its default", where))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"pages": len(published), "locales": len(locales)}}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, list):
        return [t for v in value for t in _strings(v)]
    return []


# --------------------------------------------------------------------------- publishing
def publish(*, by: str, note: str | None, hook_configured: bool) -> dict[str, Any]:
    """Freeze the working copy as the live site content. Refused with the report when the check finds errors, and when
    nothing differs from what is live."""
    report = validate()
    if not report["ok"]:
        raise ValidationFailed("The site cannot be published yet: fix the problems listed", {"report": report})
    snapshot = _snapshot(_Working())
    digest = snapshot_hash(snapshot)
    live = current_publication()
    if live is not None and live["version_hash"] == digest:
        raise Conflict("Nothing has changed since the last publish")
    with master_session() as m:
        row = m.execute(text(
            "insert into master.site_publish (published_by, note, version_hash, snapshot, hook_status, hook_next_at) "
            "values (:by, :n, :h, cast(:s as jsonb), :hs, case when :hs = 'pending' then now() end) "
            "returning id, published_at, published_by, note, version_hash, hook_status"),
            {"by": by, "n": (note or "").strip()[:300] or None, "h": digest, "s": json.dumps(snapshot, default=str),
             "hs": "pending" if hook_configured else "skipped"}).one()
    return {**dict(row._mapping), "pages": len(snapshot["pages"]), "warnings": report["warnings"]}


def history(limit: int = 50) -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(text(
            "select id, published_at, published_by, note, version_hash, hook_status, hook_attempts, hook_next_at, "
            "hook_result, jsonb_array_length(snapshot->'pages') as pages from master.site_publish "
            "order by id desc limit :n"), {"n": limit})
        return [dict(r._mapping) for r in rows]


def deployment_enabled() -> bool:
    """False in a self-hosted deployment: a business running its own copy has no marketing site to manage."""
    return get_settings().deployment_mode.strip().lower() != "selfhosted"


def asset_usage(asset: UUID) -> list[str]:
    """Where a picture is used (settings by key, pages by address), so it is not removed from under them."""
    info = site_assets.get(asset)
    short = f"asset:{info['asset_id']}"
    used = [k for k, v in settings_values().items() if BY_KEY.get(k) and BY_KEY[k].kind == "asset" and v == str(asset)]
    with master_session() as m:
        rows = m.execute(text("select slug, locale from master.site_page where position(:s in body_md) > 0"),
                         {"s": short})
        used += [_key(r.slug, r.locale) for r in rows]
    live = current_publication()
    if live is not None:
        in_snapshot = any(a["hash"] == info["hash"] for a in live["snapshot"]["assets"])
        if in_snapshot:
            used.append("the live site")
    return used
