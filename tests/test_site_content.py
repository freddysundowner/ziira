"""Website content in the Super Admin: settings, pages, versions, safe Markdown, pictures, publishing, the public
endpoint and the site rebuild hook (docs/platform-admin-content.md).

Covers: who may use it (no sign-in, a business token, roles without `platform.content`); setting validation without any
country assumption; page create/edit/version/diff/restore/delete; a corpus of hostile Markdown; the validate-before-
publish report; that only published content is public and no operator data, draft or secret ever is; ETag, caching and
the rate limit; picture limits, metadata removal and rejection of non-images; the signed, retried rebuild hook (fake
transport, no secrets recorded); the operator trail; self-hosted mode; the plans adapter.
"""

import hashlib
import hmac
import io
import json
import re
from html.parser import HTMLParser

import httpx
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import make_tenant, sign_in
from tests.test_support_access import API, OP_PASSWORD, new_operator, operator_token
from ziira.kernel import operators, site_assets, site_content, site_hook, site_markdown
from ziira.kernel.api import site_routes
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session

SITE = f"{API}/operator/site"
PUBLIC = f"{API}/public/site"
HOOK_URL = "https://builds.test/hooks/SECRET-TOKEN-123"
HOOK_SECRET = "hook-signing-secret"
TABLES = "master.site_publish, master.site_page_version, master.site_page, master.site_setting, master.site_asset"


@pytest.fixture(scope="module")
def staff(client):  # type: ignore[no-untyped-def]
    email, secret = new_operator()
    return {"email": email, "secret": secret, "headers": operator_token(client, email, secret)}


@pytest.fixture(scope="module")
def roles(client):  # type: ignore[no-untyped-def]
    """Operators with other roles, signed in."""
    from uuid import uuid4

    out = {}
    for role in ("content", "support", "billing", "readonly"):
        email = f"{role}-{uuid4().hex[:6]}@ziira.test"
        _, secret, _ = operators.create_operator(f"{role.title()} Person", email, OP_PASSWORD, role)
        out[role] = operator_token(client, email, secret)
    return out


@pytest.fixture(autouse=True)
def clean_site():  # type: ignore[no-untyped-def]
    """Every test starts with an empty website (truncate is not blocked by the append-only triggers)."""
    with master_session() as m:
        m.execute(text(f"truncate {TABLES}"))
    site_routes.reset_rate_limits()
    yield


@pytest.fixture
def env(monkeypatch):  # type: ignore[no-untyped-def]
    """Set a ZIIRA_* setting for one test."""
    def put(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(f"ZIIRA_{key.upper()}", value)
        get_settings.cache_clear()

    yield put
    monkeypatch.undo()
    get_settings.cache_clear()


# --------------------------------------------------------------------------- helpers
LOREM = ("We keep this text short and plain so that the page is long enough to count as a real page for the check. "
         "It says who we are, what we do with your information and how to reach us by email or phone. ")


def good_settings() -> dict:  # type: ignore[type-arg]
    return {"company_legal_name": "Acme Systems Ltd", "company_trading_name": "Acme",
            "tagline": {"en": "Run the whole business", "sw": "Endesha biashara yote"},
            "support_email": "Support@Acme-Systems.test", "sales_email": "sales@acme-systems.test",
            "phones": ["+44 20 7946 0958", "+254 700 123 456"], "whatsapp_number": "+254 700 123 456",
            "postal_address": "1 High Street\nSomewhere", "social_x": "@acme", "social_github": "acme-systems",
            "seo_title_template": {"en": "{title} | Acme"}, "seo_description": {"en": "Business software."},
            "app_url": "https://app.acme-systems.test", "locales": ["en", "sw"]}


def put_settings(client, headers, values):  # type: ignore[no-untyped-def]
    return client.put(f"{SITE}/settings", headers=headers, json={"values": values})


def new_page(client, headers, slug="privacy", locale="en", kind="legal", title="Privacy policy",  # type: ignore[no-untyped-def]
             body=None, **extra):
    r = client.post(f"{SITE}/pages", headers=headers, json={
        "slug": slug, "locale": locale, "kind": kind, "title": title, "body_md": body if body is not None else LOREM * 3,
        **extra})
    assert r.status_code == 201, r.text
    return r.json()


def publish_page(client, headers, page_id):  # type: ignore[no-untyped-def]
    r = client.post(f"{SITE}/pages/{page_id}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def fill_site(client, headers, *, publish_pages=True):  # type: ignore[no-untyped-def]
    """Settings plus all six legal pages in both languages: a site that passes the check."""
    assert put_settings(client, headers, good_settings()).status_code == 200
    ids = []
    for locale in ("en", "sw"):
        for slug in site_content.LEGAL_SLUGS:
            page = new_page(client, headers, slug=slug, locale=locale, title=f"{slug} {locale}")
            ids.append(page["id"])
            if publish_pages:
                publish_page(client, headers, page["id"])
    return ids


def do_publish(client, headers, note="first"):  # type: ignore[no-untyped-def]
    return client.post(f"{SITE}/publish", headers=headers, json={"note": note})


def png(size=(8, 8), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, (10, 120, 200) if mode == "RGB" else 0).save(out, "PNG")
    return out.getvalue()


def upload(client, headers, data: bytes, content_type="image/png", name="logo.png", alt="Logo"):  # type: ignore[no-untyped-def]
    return client.post(f"{SITE}/assets", params={"name": name, "alt": alt}, content=data,
                       headers={**headers, "Content-Type": content_type})


def trail(action: str) -> list[dict]:  # type: ignore[type-arg]
    with master_session() as m:
        rows = m.execute(text("select action, target, outcome, detail from master.operator_action_log "
                              "where action = :a order by id"), {"a": action})
        return [dict(r._mapping) for r in rows]


# --------------------------------------------------------------------------- who can reach it
ROUTES = [("get", "/availability"), ("get", "/settings"), ("get", "/pages"), ("get", "/assets"), ("get", "/validate"),
          ("get", "/status"), ("get", "/publishes"), ("get", "/plans"), ("get", "/pages/starters?locale=en"),
          ("put", "/settings"), ("post", "/pages"), ("post", "/preview"), ("post", "/publish")]


def call(client, method, path, headers=None):  # type: ignore[no-untyped-def]
    body = {"values": {}} if path == "/settings" else {"markdown": "x"} if path == "/preview" else {}
    kwargs = {"headers": headers or {}}
    if method in ("put", "post"):
        kwargs["json"] = body
    return getattr(client, method)(f"{SITE}{path}", **kwargs)


def test_nobody_and_business_users_are_refused(client, staff) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Site Biz")
    owner = sign_in(client, "site-biz", "owner@site-biz.test")
    for method, path in ROUTES:
        assert call(client, method, path).status_code == 401, path
        assert call(client, method, path, owner.headers).status_code == 401, path
    assert t["tenant_id"]


def test_only_content_roles_may_edit(client, roles, staff) -> None:  # type: ignore[no-untyped-def]
    for role in ("support", "billing", "readonly"):
        for method, path in ROUTES:
            if path == "/availability":
                continue
            r = call(client, method, path, roles[role])
            assert r.status_code == 403, (role, path, r.status_code)
        mine = client.get(f"{SITE}/availability", headers=roles[role])
        assert mine.status_code == 200 and mine.json()["can_edit"] is False
    for headers in (roles["content"], staff["headers"]):
        for method, path in ROUTES:
            if method == "get" or path == "/preview":
                assert call(client, method, path, headers).status_code == 200, path
        assert client.get(f"{SITE}/availability", headers=headers).json()["can_edit"] is True


def test_a_change_needs_a_fresh_second_factor(client, staff) -> None:  # type: ignore[no-untyped-def]
    with master_session() as m:
        m.execute(text("update master.operator_session set mfa_verified_at = now() - interval '2 hours' "
                       "where operator_id = (select id from master.operator where lower(email) = :e)"),
                  {"e": staff["email"]})
    r = put_settings(client, staff["headers"], {"company_legal_name": "Acme"})
    assert r.status_code == 403 and r.json()["error"] == "mfa_step_up_required"
    assert client.get(f"{SITE}/settings", headers=staff["headers"]).json()["values"] == {}   # nothing was saved
    lines = trail("site.settings.save")
    assert lines and lines[-1]["outcome"] == "refused"
    with master_session() as m:
        m.execute(text("update master.operator_session set mfa_verified_at = now() where operator_id = "
                       "(select id from master.operator where lower(email) = :e)"), {"e": staff["email"]})


# --------------------------------------------------------------------------- settings
BAD = [
    ("support_email", "not-an-email"), ("support_email", "a b@c.com"), ("sales_email", "x@y"),
    ("phones", ["0700 123 456"]), ("phones", ["+12"]), ("phones", ["call me"]), ("phones", ["+1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6"]),
    ("phones", ["+44 1"] * 6), ("whatsapp_number", "0700123456"),
    ("app_url", "javascript:alert(1)"), ("app_url", "ftp://files.test"), ("app_url", "https://user:pw@host.test/"),
    ("app_url", "not a url"), ("status_page_url", "//evil.test"), ("banner_link", "mailto:a@b.co"),
    ("social_x", "has space"), ("social_github", "../../etc"), ("social_linkedin", "http://"),
    ("company_legal_name", "x" * 300), ("company_legal_name", 5), ("analytics_enabled", "yes"),
    ("analytics_id", "bad id!"), ("seo_title_template", {"en": "no token here"}), ("tagline", {"not a locale": "x"}),
    ("tagline", "plain string"), ("locales", ["en", "en"]), ("locales", ["English"]),
    ("locales", ["en", "sw", "fr", "de", "pt", "it", "es"]), ("banner_starts_at", "tomorrow"), ("logo", "not-a-uuid"),
    ("logo", "00000000-0000-0000-0000-000000000000"), ("unknown_key", "x"),
]


@pytest.mark.parametrize("key,value", BAD)
def test_bad_settings_are_refused_with_a_message_per_field(client, staff, key, value) -> None:  # type: ignore[no-untyped-def]
    r = put_settings(client, staff["headers"], {key: value})
    assert r.status_code == 422, (key, value, r.text)
    assert key in r.json()["fields"]
    assert client.get(f"{SITE}/settings", headers=staff["headers"]).json()["values"] == {}


def test_good_settings_are_saved_and_normalised(client, staff) -> None:  # type: ignore[no-untyped-def]
    r = put_settings(client, staff["headers"], good_settings())
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert values["support_email"] == "support@acme-systems.test"                    # lower case
    assert values["phones"] == ["+44 20 7946 0958", "+254 700 123 456"]               # any country, international form
    assert values["social_x"] == "@acme" and set(r.json()["changed"]) == set(good_settings())
    again = put_settings(client, staff["headers"], {"company_trading_name": "Acme"})
    assert again.json()["changed"] == []                                              # same value: no change


def test_one_bad_value_saves_nothing_and_empty_clears(client, staff) -> None:  # type: ignore[no-untyped-def]
    put_settings(client, staff["headers"], {"company_legal_name": "Old Name Ltd"})
    r = put_settings(client, staff["headers"], {"company_legal_name": "New Name", "support_email": "nope"})
    assert r.status_code == 422 and list(r.json()["fields"]) == ["support_email"]
    assert client.get(f"{SITE}/settings", headers=staff["headers"]).json()["values"]["company_legal_name"] == "Old Name Ltd"
    put_settings(client, staff["headers"], {"company_legal_name": None, "tagline": {"en": "", "sw": " "}})
    assert "company_legal_name" not in client.get(f"{SITE}/settings", headers=staff["headers"]).json()["values"]


def test_banner_window_must_make_sense(client, staff) -> None:  # type: ignore[no-untyped-def]
    ok = put_settings(client, staff["headers"], {"banner_starts_at": "2026-12-01T09:00:00Z",
                                                 "banner_ends_at": "2026-12-31T09:00:00+03:00"})
    assert ok.status_code == 200 and ok.json()["values"]["banner_starts_at"].startswith("2026-12-01T09:00:00")
    bad = put_settings(client, staff["headers"], {"banner_ends_at": "2026-11-01T00:00:00Z"})
    assert bad.status_code == 422 and "banner_ends_at" in bad.json()["fields"]


# --------------------------------------------------------------------------- pages and versions
def test_page_create_rules(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    p = new_page(client, h)
    assert p["status"] == "draft" and p["version"] == 1 and p["state"] == "draft"
    dup = client.post(f"{SITE}/pages", headers=h, json={"slug": "privacy", "locale": "en", "kind": "legal", "title": "x"})
    assert dup.status_code == 409
    for body in ({"slug": "Bad Slug", "locale": "en", "kind": "legal", "title": "x"},
                 {"slug": "ok", "locale": "english", "kind": "legal", "title": "x"},
                 {"slug": "ok", "locale": "en", "kind": "blog", "title": "x"},
                 {"slug": "ok", "locale": "en", "kind": "legal", "title": "  "},
                 {"slug": "ok", "locale": "en", "kind": "legal", "title": "x", "extra": 1}):
        assert client.post(f"{SITE}/pages", headers=h, json=body).status_code == 422, body
    same_slug_other_language = new_page(client, h, locale="sw")
    assert same_slug_other_language["id"] != p["id"]
    assert [x["locale"] for x in client.get(f"{SITE}/pages?locale=sw", headers=h).json()] == ["sw"]


def test_editing_makes_versions_and_stale_saves_are_refused(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    p = new_page(client, h, body="one\ntwo\nthree")
    r = client.put(f"{SITE}/pages/{p['id']}", headers=h, json={
        "expected_version": 1, "title": "Privacy", "body_md": "one\nTWO\nthree", "note": "fix line two"})
    assert r.status_code == 200 and r.json()["version"] == 2
    stale = client.put(f"{SITE}/pages/{p['id']}", headers=h, json={"expected_version": 1, "title": "Privacy",
                                                                    "body_md": "other"})
    assert stale.status_code == 409 and stale.json()["current_version"] == 2
    unchanged = client.put(f"{SITE}/pages/{p['id']}", headers=h, json={"expected_version": 2, "title": "Privacy",
                                                                       "body_md": "one\nTWO\nthree"})
    assert unchanged.json()["version"] == 2                                            # nothing to save
    versions = client.get(f"{SITE}/pages/{p['id']}/versions", headers=h).json()
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["note"] == "fix line two"
    d = client.get(f"{SITE}/pages/{p['id']}/diff?older=1&newer=2", headers=h).json()
    assert "-two" in d["diff"] and "+TWO" in d["diff"] and d["added"] >= 1 and d["removed"] >= 1
    restored = client.post(f"{SITE}/pages/{p['id']}/versions/1/restore", headers=h)
    assert restored.status_code == 200 and restored.json()["version"] == 3 and restored.json()["body_md"] == "one\ntwo\nthree"
    assert client.get(f"{SITE}/pages/{p['id']}/versions/2", headers=h).json()["body_md"] == "one\nTWO\nthree"  # kept
    assert client.get(f"{SITE}/pages/{p['id']}/versions/9", headers=h).status_code == 404


def test_page_history_cannot_be_changed_in_the_database(client, staff) -> None:  # type: ignore[no-untyped-def]
    p = new_page(client, staff["headers"])
    for sql in ("update master.site_page_version set title = 'x'", "delete from master.site_page_version"):
        with pytest.raises(DBAPIError), master_session() as m:
            m.execute(text(sql))
    assert client.get(f"{SITE}/pages/{p['id']}/versions", headers=staff["headers"]).json()


def test_status_and_delete_rules(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    fill_site(client, h)
    do_publish(client, h)
    page = next(p for p in client.get(f"{SITE}/pages", headers=h).json() if p["slug"] == "terms" and p["locale"] == "en")
    assert page["state"] == "live"
    assert client.delete(f"{SITE}/pages/{page['id']}", headers=h).status_code == 409           # published
    r = client.post(f"{SITE}/pages/{page['id']}/unpublish", headers=h)
    assert r.json()["status"] == "draft" and r.json()["state"] == "unpublish_pending"
    assert client.delete(f"{SITE}/pages/{page['id']}", headers=h).status_code == 409           # still on the live site
    gone = new_page(client, h, slug="scratch", kind="content", title="Scratch")
    assert client.delete(f"{SITE}/pages/{gone['id']}", headers=h).status_code == 204
    assert client.get(f"{SITE}/pages/{gone['id']}", headers=h).status_code == 404


def test_starters_are_outlines_that_cannot_be_published(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    starters = client.get(f"{SITE}/pages/starters?locale=sw", headers=h).json()
    assert {s["slug"] for s in starters} == set(site_content.LEGAL_SLUGS)
    assert all("TODO(legal)" in s["body_md"] and "lawyer" in s["body_md"].lower() or "mwanasheria" in s["body_md"]
               for s in starters)
    assert client.get(f"{SITE}/pages/starters?locale=nonsense", headers=h).status_code == 422
    put_settings(client, h, good_settings())
    for locale in ("en", "sw"):
        for s in client.get(f"{SITE}/pages/starters?locale={locale}", headers=h).json():
            page = new_page(client, h, slug=s["slug"], locale=locale, title=s["title"], body=s["body_md"])
            publish_page(client, h, page["id"])
    report = client.get(f"{SITE}/validate", headers=h).json()
    assert report["ok"] is False and {e["code"] for e in report["errors"]} == {"placeholder"}
    assert len(report["errors"]) == 12
    assert do_publish(client, h).status_code == 422


# --------------------------------------------------------------------------- Markdown safety
HOSTILE = [
    "<script>alert(1)</script>", "<SCRIPT SRC=//evil.test/x.js></SCRIPT>", "<iframe src=//evil.test></iframe>",
    "<img src=x onerror=alert(1)>", "<svg onload=alert(1)>", "<a href=\"javascript:alert(1)\">x</a>",
    "[x](javascript:alert(1))", "[x](JaVaScRiPt:alert(1))", "[x](&#106;avascript:alert(1))",
    "[x](jav&#x61;script:alert(1))", "[x](java\tscript:alert(1))", "[x](  javascript:alert(1))",
    "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)", "![x](data:image/svg+xml;base64,AAAA)",
    "[x](vbscript:msgbox(1))", "[x](file:///etc/passwd)", "[x](//evil.test/x)", "[x](\\\\evil.test\\x)",
    "<object data=x></object><embed src=x>", "<form action=//evil.test><input></form>", "<style>@import 'x'</style>",
    "<meta http-equiv=refresh content='0;url=//evil.test'>", "<base href=//evil.test>", "<link rel=stylesheet href=x>",
    "<details open ontoggle=alert(1)>", "<math><mtext></mtext></math>", "<body onload=alert(1)>",
    "[x](https://ok.test \"title\" onmouseover=\"alert(1)\")", "![a\" onerror=\"alert(1)](x.png)",
    "```\n<script>alert(1)</script>\n```", "`<img src=x onerror=alert(1)>`", "[<img src=x onerror=alert(1)>](https://ok.test)",
    "<a href='https://ok.test' onclick=alert(1)>x</a>", "[x]: javascript:alert(1)\n\n[x]", "<!-- <script> -->",
    "&lt;script&gt;alert(1)&lt;/script&gt;", "‮<script>", "<scr<script>ipt>alert(1)</scr</script>ipt>",
]
ALLOWED_TAGS = {"p", "a", "img", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4",
                "h5", "h6", "hr", "br", "table", "thead", "tbody", "tr", "th", "td", "s"}
ALLOWED_ATTRS = {"a": {"href", "rel", "title"}, "img": {"src", "alt", "loading", "title"}, "th": {"style"}, "td": {"style"},
                 "ol": {"start"}, "code": {"class"}}


class Audit(HTMLParser):
    """Collects what a browser would see: tags, attributes and the addresses in them."""

    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        if tag not in ALLOWED_TAGS:
            self.problems.append(f"tag {tag}")
        for name, value in attrs:
            if name not in ALLOWED_ATTRS.get(tag, set()):
                self.problems.append(f"attribute {name} on {tag}")
            if name in ("href", "src") and value and not site_markdown.is_safe_address(value):
                self.problems.append(f"address {value}")
            if name.startswith("on"):
                self.problems.append(name)


@pytest.mark.parametrize("payload", HOSTILE)
def test_hostile_markdown_comes_out_safe(client, staff, payload) -> None:  # type: ignore[no-untyped-def]
    html = site_markdown.render(payload)
    audit = Audit()
    audit.feed(html)
    assert audit.problems == [], (payload, html)
    assert not re.search(r"<\s*(script|iframe|object|embed|style|svg|form|meta|base|link)", html, re.I), html
    via_api = client.post(f"{SITE}/preview", headers=staff["headers"], json={"markdown": payload})
    assert via_api.status_code == 200 and via_api.json()["html"] == html


def test_good_markdown_still_renders(client, staff) -> None:  # type: ignore[no-untyped-def]
    html = site_markdown.render("# Hello\n\n**bold** [site](https://ok.test) [mail](mailto:a@b.co) [here](/about) "
                                "[top](#top)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two")
    assert "<h1>Hello</h1>" in html and "<strong>bold</strong>" in html and "<table>" in html and "<li>one</li>" in html
    assert 'href="https://ok.test" rel="noopener noreferrer"' in html and 'href="/about"' in html


def test_unsafe_links_and_missing_pictures_are_reported_before_publishing(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    fill_site(client, h)
    page = next(p for p in client.get(f"{SITE}/pages", headers=h).json() if p["slug"] == "terms" and p["locale"] == "en")
    body = LOREM * 3 + "\n[bad](javascript:alert(1)) ![gone](asset:0123456789abcdef) [dummy](https://example.invalid/x)"
    client.put(f"{SITE}/pages/{page['id']}", headers=h, json={"expected_version": page["version"], "title": "Terms",
                                                               "body_md": body})
    errors = client.get(f"{SITE}/validate", headers=h).json()["errors"]
    messages = " | ".join(e["message"] for e in errors if e["code"] == "bad_link")
    assert "not allowed" in messages and "media library" in messages and "placeholder address" in messages


# --------------------------------------------------------------------------- the check and publishing
def codes(report, kind="errors"):  # type: ignore[no-untyped-def]
    return {(e["code"], e["where"]) for e in report[kind]}


def test_an_empty_site_cannot_be_published(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    report = client.get(f"{SITE}/validate", headers=h).json()
    assert report["ok"] is False
    assert ("required", "company_legal_name") in codes(report) and ("required", "support_email") in codes(report)
    assert ("legal_missing", "en/privacy") in codes(report) and ("legal_missing", "sw/data-processing") in codes(report)
    r = do_publish(client, h)
    assert r.status_code == 422 and r.json()["report"]["ok"] is False
    assert client.get(PUBLIC).json()["published"] is False


def test_check_rules(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    ids = fill_site(client, h)
    ok = client.get(f"{SITE}/validate", headers=h).json()
    assert ok["ok"] is True, ok["errors"]
    # placeholder text in settings and pages, a dummy phone number
    put_settings(client, h, {"tagline": {"en": "TODO write a tagline"}, "phones": ["+000 000 0000"],
                             "support_email": "info@example.com"})
    bad = client.get(f"{SITE}/validate", headers=h).json()
    assert {("placeholder", "tagline"), ("placeholder", "phones"), ("placeholder", "support_email")} <= codes(bad)
    put_settings(client, h, {"tagline": None, "phones": None, "support_email": "help@acme-systems.test"})
    p = client.get(f"{SITE}/pages/{ids[0]}", headers=h).json()
    client.put(f"{SITE}/pages/{ids[0]}", headers=h, json={"expected_version": p["version"], "title": p["title"],
                                                           "body_md": LOREM + "Lorem ipsum dolor sit amet."})
    assert ("placeholder", "en/privacy") in codes(client.get(f"{SITE}/validate", headers=h).json())
    client.put(f"{SITE}/pages/{ids[0]}", headers=h, json={"expected_version": p["version"] + 1, "title": p["title"],
                                                           "body_md": LOREM * 3})
    # the Swahili counterpart of a content page is missing
    c = new_page(client, h, slug="about", kind="content", title="About")
    publish_page(client, h, c["id"])
    assert ("counterpart_missing", "en/about") in codes(client.get(f"{SITE}/validate", headers=h).json())
    sw = new_page(client, h, slug="about", locale="sw", kind="content", title="Kuhusu")
    publish_page(client, h, sw["id"])
    assert client.get(f"{SITE}/validate", headers=h).json()["ok"] is True
    # analytics needs an id and the cookie notice
    put_settings(client, h, {"analytics_enabled": True})
    assert {("required", "analytics_id"), ("required", "cookie_notice_text")} <= codes(
        client.get(f"{SITE}/validate", headers=h).json())
    # an enabled language needs its own legal pages
    put_settings(client, h, {"analytics_enabled": None, "locales": ["en", "sw", "fr"]})
    assert ("legal_missing", "fr/privacy") in codes(client.get(f"{SITE}/validate", headers=h).json())


def test_publish_goes_live_and_drafts_never_do(client, staff, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import plans

    # other test files leave public plans in the shared master database; this test is about pages, not plans
    monkeypatch.setattr(plans, "public_plans", lambda: {"plans": [], "addons": [], "updated_at": None})
    h = staff["headers"]
    fill_site(client, h)
    draft = new_page(client, h, slug="secret-plans", kind="content", title="Draft only", body="DRAFT-MARKER-4711 " + LOREM)
    r = do_publish(client, h, "launch")
    assert r.status_code == 201, r.text
    assert r.json()["hook_status"] == "skipped" and r.json()["pages"] == 12 and r.json()["published_by"] == "Sam Support"
    live = client.get(PUBLIC)
    assert live.status_code == 200
    body = live.json()
    assert body["published"] is True and body["version_hash"] == r.json()["version_hash"]
    assert body["settings"]["company"]["legal_name"] == "Acme Systems Ltd"
    assert body["settings"]["contact"]["whatsapp"]["link"] == "https://wa.me/254700123456"
    assert body["settings"]["social"]["x"] == {"handle": "@acme", "url": "https://x.com/acme"}
    assert body["settings"]["analytics"] is None                                        # tracking is off unless chosen
    assert body["settings"]["default_locale"] == "en" and body["plans"] == [] and body["assets"] == []
    assert {(p["slug"], p["locale"]) for p in body["pages"]} == {(s, lo) for s in site_content.LEGAL_SLUGS
                                                                 for lo in ("en", "sw")}
    sample = body["pages"][0]
    assert set(sample) == {"slug", "locale", "kind", "title", "html", "markdown", "seo", "updated_at", "version"}
    assert "DRAFT-MARKER-4711" not in live.text and draft["id"] not in live.text
    # an edit is invisible until the next publish, and shown as pending
    p = next(x for x in client.get(f"{SITE}/pages", headers=h).json() if x["slug"] == "privacy" and x["locale"] == "en")
    client.put(f"{SITE}/pages/{p['id']}", headers=h, json={"expected_version": p["version"], "title": "Privacy policy",
                                                            "body_md": LOREM * 4 + " EDITED-MARKER-9"})
    put_settings(client, h, {"company_trading_name": "Acme Two"})
    assert "EDITED-MARKER-9" not in client.get(PUBLIC).text and "Acme Two" not in client.get(PUBLIC).text
    status = client.get(f"{SITE}/status", headers=h).json()
    assert {"area": "page", "ref": "en/privacy", "change": "changed"} in status["pending"]
    assert {"area": "settings", "ref": "company", "change": "changed"} in status["pending"]
    assert next(x for x in client.get(f"{SITE}/pages", headers=h).json() if x["id"] == p["id"])["state"] == "changed"
    assert do_publish(client, h, "second").status_code == 201
    assert "EDITED-MARKER-9" in client.get(PUBLIC).text
    assert client.get(f"{SITE}/status", headers=h).json()["pending"] == []
    assert do_publish(client, h).status_code == 409                                      # nothing changed
    history = client.get(f"{SITE}/publishes", headers=h).json()
    assert [x["note"] for x in history] == ["second", "launch"] and history[0]["published_by"] == "Sam Support"


def test_unpublishing_a_page_removes_it_with_the_next_publish(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    fill_site(client, h)
    about = new_page(client, h, slug="about", kind="content", title="About")
    about_sw = new_page(client, h, slug="about", locale="sw", kind="content", title="Kuhusu")
    publish_page(client, h, about["id"])
    publish_page(client, h, about_sw["id"])
    do_publish(client, h)
    assert any(p["slug"] == "about" for p in client.get(PUBLIC).json()["pages"])
    client.post(f"{SITE}/pages/{about['id']}/unpublish", headers=h)
    assert any(p["slug"] == "about" for p in client.get(PUBLIC).json()["pages"])        # still live until published
    client.post(f"{SITE}/pages/{about_sw['id']}/unpublish", headers=h)
    assert do_publish(client, h).status_code == 201
    assert not any(p["slug"] == "about" for p in client.get(PUBLIC).json()["pages"])


def test_the_public_content_never_carries_operator_data_or_secrets(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    env(site_build_hook_url=HOOK_URL, site_build_hook_secret=HOOK_SECRET)
    site_hook.transport = httpx.MockTransport(lambda request: httpx.Response(200))
    try:
        fill_site(client, h)
        assert do_publish(client, h).status_code == 201
    finally:
        site_hook.transport = None
    text_ = client.get(PUBLIC).text
    for needle in (staff["email"], "Sam Support", "updated_by", "created_by", "published_by", "password", "mfa", "secret",
                   "SECRET-TOKEN", HOOK_SECRET, "hook_", "builds.test", "credential", "operator", "session",
                   "Bearer", "master."):
        assert needle.lower() not in text_.lower(), needle
    assert set(client.get(PUBLIC).json()) == {"published", "settings", "pages", "plans", "addons", "assets",
                                              "published_at", "version_hash"}


# --------------------------------------------------------------------------- caching and limits
def test_etag_and_cache_headers(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    fill_site(client, h)
    do_publish(client, h)
    first = client.get(PUBLIC)
    tag = first.headers["etag"]
    assert tag.startswith('"') and "max-age=60" in first.headers["cache-control"] and "public" in first.headers["cache-control"]
    assert first.headers["content-type"].startswith("application/json")
    same = client.get(PUBLIC, headers={"If-None-Match": tag})
    assert same.status_code == 304 and same.content == b"" and same.headers["etag"] == tag
    assert client.get(PUBLIC, headers={"If-None-Match": '"other"'}).status_code == 200
    put_settings(client, h, {"company_trading_name": "Changed"})
    do_publish(client, h, "again")
    assert client.get(PUBLIC).headers["etag"] != tag
    assert client.get(PUBLIC, headers={"If-None-Match": tag}).status_code == 200      # the old tag no longer matches


def test_public_endpoint_is_rate_limited(client, env) -> None:  # type: ignore[no-untyped-def]
    env(site_public_rate_per_minute="3")
    assert [client.get(PUBLIC).status_code for _ in range(3)] == [200, 200, 200]
    limited = client.get(PUBLIC)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


def test_plans_are_embedded_through_the_adapter(client, staff, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import plans

    h = staff["headers"]
    fill_site(client, h)
    do_publish(client, h)
    offered = {"plans": [{"code": "growth", "name": "Growth", "prices": [{"currency": "USD", "interval": "month",
                                                                           "amount": "30.00"}]}],
               "addons": [{"code": "extra"}], "updated_at": "2026-10-15T00:00:00+00:00"}
    monkeypatch.setattr(plans, "public_plans", lambda: offered)
    body = client.get(PUBLIC).json()
    assert body["plans"][0]["code"] == "growth" and body["addons"] == [{"code": "extra"}]
    assert client.get(f"{SITE}/plans", headers=h).json()["plans"][0]["name"] == "Growth"
    tag = client.get(PUBLIC).headers["etag"]
    offered["plans"][0]["name"] = "Growth+"                                           # a plan change changes the tag
    assert client.get(PUBLIC).headers["etag"] != tag

    def broken() -> dict:  # type: ignore[type-arg]
        raise RuntimeError("plans are down")

    monkeypatch.setattr(plans, "public_plans", broken)
    ok = client.get(PUBLIC)
    assert ok.status_code == 200 and ok.json()["plans"] == []                         # the site still gets its content


def test_self_hosted_has_no_website_area(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    env(deployment_mode="selfhosted")
    assert client.get(f"{SITE}/availability", headers=staff["headers"]).json()["available"] is False
    for method, path in ROUTES:
        if path != "/availability":
            assert call(client, method, path, staff["headers"]).status_code == 404, path
    assert client.get(PUBLIC).status_code == 404
    assert client.get(f"{PUBLIC}/assets/0123456789abcdef.png").status_code == 404


# --------------------------------------------------------------------------- pictures
def test_pictures_are_checked_and_cleaned(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    jpeg = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    exif[0x0112] = 6                                                                  # rotated: 40x20 becomes 20x40
    Image.new("RGB", (40, 20), (200, 10, 10)).save(jpeg, "JPEG", exif=exif.tobytes(), comment=b"private note")
    r = upload(client, h, jpeg.getvalue(), "image/jpeg", "photo.jpg", "A photo")
    assert r.status_code == 201, r.text
    info = r.json()
    assert (info["width"], info["height"]) == (20, 40) and info["content_type"] == "image/jpeg"
    with master_session() as m:
        stored = bytes(m.execute(text("select data from master.site_asset where id = :i"), {"i": info["id"]}).scalar_one())
    assert b"SecretCamera" not in stored and b"private note" not in stored and not Image.open(io.BytesIO(stored)).getexif()
    assert info["hash"] == hashlib.sha256(stored).hexdigest() and info["asset_id"] == info["hash"][:16]
    shown = client.get(f"{SITE}/assets/{info['id']}/file", headers=h)
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg"
    assert client.get(f"{SITE}/assets/{info['id']}/file").status_code == 401
    again = upload(client, h, jpeg.getvalue(), "image/jpeg")
    assert again.status_code in (201, 409)                                            # re-encoded bytes equal: 409
    assert upload(client, h, png((9, 9))).status_code == 201


def big_png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("1", (width, height)).save(out, "PNG", optimize=True)
    return out.getvalue()


@pytest.mark.parametrize("data,kind", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/png"),
    (b"<html><script>alert(1)</script></html>", "image/png"), (b"%PDF-1.4 fake", "image/png"),
    (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "image/gif"), (b"not an image at all", "image/png"), (b"", "image/png"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "image/png"),
])
def test_non_images_are_rejected(client, staff, data, kind) -> None:  # type: ignore[no-untyped-def]
    r = upload(client, staff["headers"], data, kind)
    assert r.status_code == 422, (kind, r.text)
    assert client.get(f"{SITE}/assets", headers=staff["headers"]).json() == []


def test_picture_size_limits(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    assert upload(client, h, big_png(4097, 10)).status_code == 422                       # too wide
    assert upload(client, h, big_png(4000, 4000)).status_code == 422                     # over 12 million pixels, tiny file
    assert upload(client, h, b"x" * 1_600_000).status_code == 422                        # over the byte limit
    r = client.post(f"{SITE}/assets", headers={**h, "Content-Type": "text/plain"}, content=png())
    assert r.status_code == 422                                                         # must say it is an image
    assert upload(client, h, big_png(2000, 2000)).status_code == 201                     # 4 million pixels is fine


def test_pictures_are_public_only_when_published_and_in_use(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    fill_site(client, h)
    logo = upload(client, h, png((12, 12))).json()
    spare = upload(client, h, png((13, 13)), name="spare.png").json()
    put_settings(client, h, {"logo": logo["id"]})
    page = next(p for p in client.get(f"{SITE}/pages", headers=h).json() if p["slug"] == "terms" and p["locale"] == "en")
    client.put(f"{SITE}/pages/{page['id']}", headers=h, json={
        "expected_version": page["version"], "title": "Terms", "body_md": LOREM * 3 + f"\n![Our logo](asset:{logo['asset_id']})"})
    name = f"{logo['asset_id']}.png"
    assert client.get(f"{PUBLIC}/assets/{name}").status_code == 404                      # not published yet
    do_publish(client, h)
    body = client.get(PUBLIC).json()
    assert [a["path"] for a in body["assets"]] == [f"/media/{name}"]                     # the unused spare is not there
    assert body["assets"][0]["alt"] == "Logo" and body["assets"][0]["width"] == 12
    assert body["settings"]["branding"]["logo"]["path"] == f"/media/{name}"
    terms = next(p for p in body["pages"] if p["slug"] == "terms" and p["locale"] == "en")
    assert f'src="/media/{name}"' in terms["html"] and "asset:" not in terms["html"]
    served = client.get(f"{PUBLIC}/assets/{name}")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert "immutable" in served.headers["cache-control"] and "max-age=31536000" in served.headers["cache-control"]
    assert client.get(f"{PUBLIC}/assets/{name}", headers={"If-None-Match": served.headers["etag"]}).status_code == 304
    assert Image.open(io.BytesIO(served.content)).size == (12, 12)
    assert client.get(f"{PUBLIC}/assets/{spare['asset_id']}.png").status_code == 404     # in the library, not public
    assert client.get(f"{PUBLIC}/assets/../../etc/passwd").status_code == 404
    assert client.get(f"{PUBLIC}/assets/nothex.png").status_code == 404
    assert client.delete(f"{SITE}/assets/{logo['id']}", headers=h).status_code == 422    # in use
    assert client.delete(f"{SITE}/assets/{spare['id']}", headers=h).status_code == 204
    alt = client.put(f"{SITE}/assets/{logo['id']}", headers=h, json={"alt": "New alt"})
    assert alt.json()["alt"] == "New alt"


# --------------------------------------------------------------------------- the rebuild hook
def hook_publish(client, staff, env, handler, **extra):  # type: ignore[no-untyped-def]
    env(site_build_hook_url=HOOK_URL, site_build_hook_secret=HOOK_SECRET, **extra)
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls))

    site_hook.transport = httpx.MockTransport(respond)
    fill_site(client, staff["headers"])
    return calls, do_publish(client, staff["headers"])


@pytest.fixture(autouse=True)
def no_fake_transport():  # type: ignore[no-untyped-def]
    yield
    site_hook.transport = None


def due_now(publish_id: int) -> None:
    with master_session() as m:
        m.execute(text("update master.site_publish set hook_next_at = now() where id = :i"), {"i": publish_id})


def test_the_hook_is_signed_and_recorded(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    calls, r = hook_publish(client, staff, env, lambda req, n: httpx.Response(200, text="queued"))
    assert r.status_code == 201 and r.json()["hook_status"] == "pending"                 # attempted after the reply
    assert len(calls) == 1
    request = calls[0]
    body = request.content
    stamp = request.headers["ziira-timestamp"]
    expected = hmac.new(HOOK_SECRET.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert request.headers["ziira-signature"] == f"v1={expected}"
    assert request.headers["ziira-event-id"] == f"site-publish-{r.json()['id']}"
    assert json.loads(body) == {"event": "site.published", "publish_id": r.json()["id"],
                                "version_hash": r.json()["version_hash"],
                                "published_at": json.loads(body)["published_at"]}
    line = client.get(f"{SITE}/publishes", headers=staff["headers"]).json()[0]
    assert line["hook_status"] == "ok" and line["hook_attempts"] == 1 and line["hook_result"] == "builds.test: answered 200"
    assert "SECRET-TOKEN" not in json.dumps(client.get(f"{SITE}/publishes", headers=staff["headers"]).json())
    assert "SECRET-TOKEN" not in json.dumps(trail("site.publish"), default=str)


def test_a_failing_hook_is_retried_with_growing_waits_then_given_up(client, staff, env, caplog) -> None:  # type: ignore[no-untyped-def]
    calls, r = hook_publish(client, staff, env, lambda req, n: httpx.Response(503))
    pid = r.json()["id"]
    state = site_hook.status(pid)
    assert state["hook_status"] == "pending" and state["hook_attempts"] == 1 and "503" in state["hook_result"]
    waits = []
    for expected_attempts in range(2, 7):
        assert site_hook.run_pending() == 0                                              # not due yet: nothing is sent
        due_now(pid)
        assert site_hook.run_pending() == 1
        state = site_hook.status(pid)
        assert state["hook_attempts"] == expected_attempts
        if state["hook_next_at"]:
            with master_session() as m:
                waits.append(int(m.execute(text("select extract(epoch from hook_next_at - now()) from master.site_publish "
                                                "where id = :i"), {"i": pid}).scalar_one()))
    assert state["hook_status"] == "failed" and len(calls) == 6
    assert [round(w, -1) for w in waits] == [120, 480, 1800, 7200]                       # grows
    assert site_hook.run_pending() == 0
    assert "SECRET-TOKEN" not in caplog.text and HOOK_SECRET not in caplog.text


def test_a_hook_that_recovers_is_recorded_ok(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    calls, r = hook_publish(client, staff, env, lambda req, n: httpx.Response(500 if n < 3 else 202))
    pid = r.json()["id"]
    for _ in range(2):
        due_now(pid)
        site_hook.run_pending()
    assert site_hook.status(pid)["hook_status"] == "ok" and len(calls) == 3


def test_a_refused_hook_is_not_retried_and_can_be_retried_by_hand(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    calls, r = hook_publish(client, staff, env, lambda req, n: httpx.Response(404 if n == 1 else 200))
    pid = r.json()["id"]
    assert site_hook.status(pid)["hook_status"] == "failed" and len(calls) == 1          # a 404 will not get better
    retry = client.post(f"{SITE}/publishes/{pid}/retry-hook", headers=staff["headers"])
    assert retry.status_code == 200 and retry.json()["hook_status"] == "ok" and len(calls) == 2
    assert client.post(f"{SITE}/publishes/99999/retry-hook", headers=staff["headers"]).status_code == 404


def test_unreachable_hook_and_insecure_address(client, staff, env) -> None:  # type: ignore[no-untyped-def]
    def down(request, n):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("refused http://builds.test/hooks/SECRET-TOKEN-123")

    calls, r = hook_publish(client, staff, env, down)
    state = site_hook.status(r.json()["id"])
    assert state["hook_status"] == "pending" and "ConnectError" in state["hook_result"]
    assert "SECRET-TOKEN" not in state["hook_result"]                                  # the error text is not kept
    env(site_build_hook_url="http://builds.test/hooks/x", env="production")
    due_now(r.json()["id"])
    site_hook.run_pending()
    state = site_hook.status(r.json()["id"])
    assert state["hook_status"] == "failed" and "https" in state["hook_result"]


def test_no_hook_configured_is_skipped(client, staff) -> None:  # type: ignore[no-untyped-def]
    fill_site(client, staff["headers"])
    assert do_publish(client, staff["headers"]).json()["hook_status"] == "skipped"
    assert site_hook.run_pending() == 0


# --------------------------------------------------------------------------- the trail
def test_changes_leave_lines_in_the_operator_trail(client, staff) -> None:  # type: ignore[no-untyped-def]
    h = staff["headers"]
    before = {a: len(trail(a)) for a in ("site.settings.save", "site.publish", "site.page.create", "site.page.delete")}
    fill_site(client, h)
    do_publish(client, h, "audit me")
    assert client.post(f"{SITE}/publish", headers=h, json={}).status_code == 409
    saved = trail("site.settings.save")[before["site.settings.save"]:]
    assert saved and set(saved[0]["detail"]["changed"]) == set(good_settings())
    published = trail("site.publish")[before["site.publish"]:]
    assert [line["outcome"] for line in published] == ["ok", "refused"]
    assert published[0]["detail"]["pages"] == 12 and published[1]["detail"]["why"]
    assert len(trail("site.page.create")) - before["site.page.create"] == 12 and trail("site.page.mark_published")
    assert "Acme Systems" not in json.dumps(saved, default=str)                          # the trail holds what, not content
    new = new_page(client, h, slug="trail-me", kind="content")
    client.delete(f"{SITE}/pages/{new['id']}", headers=h)
    assert trail("site.page.delete")[-1]["detail"] == {"slug": "trail-me", "locale": "en"}
    assert len(trail("site.page.delete")) - before["site.page.delete"] == 1


def test_the_database_keeps_published_snapshots_as_they_were(client, staff) -> None:  # type: ignore[no-untyped-def]
    fill_site(client, staff["headers"])
    do_publish(client, staff["headers"])
    for sql in ("update master.site_publish set snapshot = '{}'::jsonb", "delete from master.site_publish"):
        with pytest.raises(DBAPIError), master_session() as m:
            m.execute(text(sql))
    with master_session() as m:                                                         # only the hook columns may change
        m.execute(text("update master.site_publish set hook_status = 'failed'"))


def test_assets_module_limits_are_what_the_docs_say() -> None:
    assert (site_assets.MAX_BYTES, site_assets.MAX_SIDE, site_assets.MAX_PIXELS) == (1_500_000, 4096, 12_000_000)
