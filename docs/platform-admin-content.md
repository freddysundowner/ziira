# Website content in the Super Admin

The marketing site (`site/`, Astro) is **static and SEO-first**: every page is made at build time. Its editable facts do not live
in the site's code. They live in the platform's master database, are edited in the Super Admin (**Website**), and reach the site
like this:

```
Super Admin (Website)  --publish-->  master.site_publish (frozen snapshot)
                                          |  GET /api/v1/public/site   (no sign-in, ETag, cacheable)
                                          v
              site build (npm run build) fetches it  -->  static pages
   publish also POSTs a signed call to ZIIRA_SITE_BUILD_HOOK_URL so the site host rebuilds
```

Nothing is fetched in a visitor's browser; the site works with no tracking and no platform at all (it builds from its last good
copy or from a committed placeholder snapshot).

Code: `ziira/kernel/site_content.py` (settings, pages, versions, the check, publishing), `site_markdown.py` (safe Markdown),
`site_assets.py` (pictures), `site_hook.py` (rebuild call), `site_plans.py` (plans adapter), `site_templates.py` (legal outlines),
`api/site_routes.py` (operator and public routes). Master migration `0011_site_content`. Web: `frontend/src/operator/pages/WebsitePage.tsx`
and `pages/website/`. Site: `site/src/lib/platform.ts` and `cmsPages.ts`.

## What is editable

| Where in the Super Admin | What |
|---|---|
| Company & contact | legal name, trading name, tagline (per language), registration and tax numbers (optional, shown if filled), postal address, support and sales email, phone numbers, WhatsApp number (click-to-chat link), contact form destination (a web address or an email), web app and status page addresses, the site's languages |
| Social | X, LinkedIn, Facebook, Instagram, YouTube, TikTok, GitHub: a handle or a full address each, all optional |
| SEO & branding | title template (`{title} \| Name`, per language), default description, default sharing image, logo, favicon, analytics (off by default; needs an ID and a cookie notice), cookie notice text |
| Legal pages & content | Markdown pages per language: privacy, terms, cookies, refunds/cancellation, acceptable use, data processing, and any other simple page. Version history with a text comparison and restore |
| Media library | PNG, JPEG or WebP pictures |
| Banner | announcement text per language, link, optional start and end |
| Pricing preview | read-only view of the public plans exactly as the site receives them (plans are edited under Plans) |
| Publish | the check, what will change, the publish button, history, and the state of each site rebuild |

Settings are a fixed typed list (`SETTINGS` in `site_content.py`). They are checked when saved, **with no country assumed**: a phone
number must be in international form (`+` and the country calling code, 7 to 15 digits), emails and web addresses are checked by
shape, social handles by character set. A bad value answers 422 with `fields` (a message per setting) and nothing is saved.
Everything in the list is meant to be public; there are no secret settings. The rebuild address and key are environment settings
(below), never stored in the database.

## Publish flow

1. Edit. Everything saved is a **working copy**: it is never visible publicly. Pages have a status: *draft* or *published*; marking a
   page published only means "include it in the next publish". The pages list shows each page as *live*, *edited since publish*,
   *not public yet* or *comes down at next publish*.
2. **Check** (`GET /operator/site/validate`, shown on the Publish tab). Errors block publishing; warnings do not.
   Errors: company legal name or support email missing; any of the six legal pages missing in an enabled language;
   a published page without its counterpart in another enabled language (the site needs both for `hreflang`); placeholder text
   (`TODO`, `TBD`, `lorem ipsum`, `[[...]]`, `example.invalid`/`example.com` addresses, "review with your lawyer", dummy phone
   numbers) in settings or pages; links that are not `http(s)`, `mailto:`, `tel:`, a site path or a fragment; pictures that are not
   in the library; analytics on without an ID or cookie notice; banner on without text.
   Warnings: no sales email, phone, address, logo, sharing image or default description; a missing translation of a setting;
   search title over 60 or description over 160 characters; `http` (not https) addresses; a very short legal page.
3. **Publish** (`POST /operator/site/publish`, with an optional note). A fresh second-factor confirmation is needed like every
   console change. The working copy is frozen as one snapshot (settings, published pages rendered to HTML, the pictures they use),
   hashed, and stored in `master.site_publish`; the public endpoint serves the newest one. Publishing when nothing differs is
   refused (409). Every publish is in the operator action trail and in the publish history (who, when, hash, note, rebuild state).
4. **Rebuild hook.** If `ZIIRA_SITE_BUILD_HOOK_URL` is set, the publish POSTs it. See below.
5. Un-publishing a page = mark it draft, then publish. Restoring an old version of a page makes it a new version (history is
   immutable: a database trigger refuses updates and deletes) and is public only after the next publish. There is no "unpublish
   everything"; publish the previous state instead.

## The public endpoint

`GET /api/v1/public/site` (no sign-in) returns

```json
{ "published": true, "settings": {...}, "pages": [{"slug","locale","kind","title","html","markdown","seo","updated_at","version"}],
  "plans": [...], "addons": [...], "assets": [{"path","hash","width","height","alt","content_type","download"}],
  "published_at": "...", "version_hash": "..." }
```

- Only the newest publish's snapshot, plus the plans from `ziira.kernel.platform.plans.public_plans()` (through the adapter
  `site_plans.py`, which answers empty lists if that service is missing or fails: the site then shows its "get in touch" state).
  A plan flagged `contact_only` or `custom` is shown as "contact us" by the site; a plan with no price for the chosen currency and
  period is too. The site never invents a price.
- It cannot leak drafts or operator data: it is built from the frozen snapshot and the plans list and nothing else (a test greps
  the response for operator names, emails, secrets and draft text).
- `ETag` (the snapshot hash combined with the plans), `Cache-Control: public, max-age=60, stale-while-revalidate=300`, `304` on
  `If-None-Match`. Rate limit: `ZIIRA_SITE_PUBLIC_RATE_PER_MINUTE` (default 120) per address, counted in the process (put a proxy limit in front for more).
- `GET /api/v1/public/site/assets/{hash16}.{png|jpg|webp}`: only pictures that are part of the live snapshot, `immutable`, one year.
- 404 in a self-hosted deployment (`ZIIRA_DEPLOYMENT_MODE=selfhosted`), where the Website area is also hidden.
- The banner's start and end are in the payload as given; the site applies them at build time and again in the visitor's browser.

## Pictures

Upload is the raw image as the request body (`POST /operator/site/assets?name=&alt=`, `Content-Type: image/*`).
PNG, JPEG, WebP only (no SVG, GIF, ICO or PDF); at most 1.5 MB, 4096 pixels a side, 12 million pixels (checked from the header
before decoding); the picture is decoded and **re-encoded**, so EXIF (camera, location, time), comments and colour-profile blocks
are gone, and the camera's orientation is applied first. Pictures are stored in the master database (`master.site_asset`, bytea),
so backups and restores carry them; the library is limited to 300. A picture still used by a setting, a page or the live site
cannot be removed. In Markdown a picture is `![alt](asset:<id>)` (the library has a "copy Markdown" button).

## Markdown safety

Raw HTML in a page is never rendered (`<script>`, `<iframe>`, `onerror=` come out as visible text). Link and image addresses
must be `http`, `https`, `mailto`, `tel`, a site path (`/x`, not `//host`), a fragment or `asset:<id>`; `javascript:`, `data:`,
`vbscript:` and friends (also when hidden with entities, spaces or mixed case) are not links. The console shows previews inside a
sandboxed frame without scripts as a second line of defence. The test corpus is in `tests/test_site_content.py` (`HOSTILE`).

## The rebuild hook

Settings: `ZIIRA_SITE_BUILD_HOOK_URL` (an `https` address; **treat it as a secret**: many build services put a token in the
path) and `ZIIRA_SITE_BUILD_HOOK_SECRET`. A publish records `hook_status = pending`, and after the reply the API makes the first
try; `ziira worker` retries what is due.

- Body: `{"event":"site.published","publish_id":N,"version_hash":"...","published_at":"..."}`.
- Headers: `Ziira-Timestamp` (unix seconds), `Ziira-Event-Id: site-publish-N` (same on every retry),
  `Ziira-Signature: v1=<hex HMAC-SHA256 of "{timestamp}.{body}" with the secret>`. A build service that only takes a plain URL
  works too (leave the secret empty); verify the signature if you put your own receiver in front.
- Retries: 30 s, 2 min, 8 min, 30 min, 2 h (6 tries in all) for network errors, 408, 425, 429 and 5xx. Other 4xx answers fail at once.
  The Publish tab shows each publish's state and has **Try again now**.
- The address is never logged or stored; the record keeps the host name, the status and a short reason (the HTTP client's own
  request log is filtered too). In production the address must be `https`.

## How the static site consumes it

`site/src/lib/platform.ts` loads the content once per build (top-level await), in this order: `PLATFORM_SNAPSHOT_FILE` (CI, tests),
the live API (`PUBLIC_PLATFORM_API_URL`; the answer is kept in `site/.cache/platform-site.json` and the pictures are copied to
`site/public/media/` after checking their hashes), the cached copy, then the committed `site/content-snapshot.json` (placeholders,
marked). `site/src/lib/siteConfig.ts` turns it into the one config object the pages read. What renders from it: header banner, footer
(contact, address, social, registration numbers, links to every published page), the contact page, legal pages (privacy and terms
keep their addresses; the other published pages get `/<slug>/` and `/sw/<slug>/` and are linked from the footer), the pricing page
(period and currency choices that work without JavaScript), Organization JSON-LD (name, legal name, logo, `sameAs` from the
social handles, `contactPoint`, address, tax ID), search text for CMS pages, the sitemap `lastmod` from each page's `updated_at`,
and the favicon.

A **production build** (`NODE_ENV=production`, which `astro build` sets) prints a loud `DO NOT DEPLOY` warning when it is not on
real, published content: the live fetch failed, nothing is published, the committed seed is in use, or placeholder text remains.
`SITE_STRICT=1` turns the warning into a failed build. A development build is quiet. The same `npm run build` pulls fresh
content, so the hook only has to start a build.

To change what the site shows, change it in the Super Admin and publish. To wire a new piece of platform data into the site, add
it to `PlatformSettings` in `platform.ts`, map it in `siteConfig.ts` and read it from `siteConfig` (never from the payload directly).

## Legal text is yours to get right

The starters (`GET /operator/site/pages/starters`) are outlines, not legal advice, and say so. Every section carries a `TODO(legal)`
line and the page opens with a "review with your lawyer" note; the check refuses a page that still has them, so an outline can
never go live by accident. Have a lawyer review every legal page for the places where you operate and the languages you publish
in. Ziira does not supply or vouch for legal text.

## Operations

- Environment: `ZIIRA_SITE_BUILD_HOOK_URL`, `ZIIRA_SITE_BUILD_HOOK_SECRET`, `ZIIRA_SITE_PUBLIC_RATE_PER_MINUTE`
  (`.env.example`); the Website area follows `ZIIRA_DEPLOYMENT_MODE`.
- Permission: `platform.content` (roles `superadmin` and `content`). Every route needs it; every change needs a fresh
  second-factor confirmation and is written to `master.operator_action_log` (what changed, never the page text).
- `ziira worker` makes the retries (`site_hook.run_pending`); `ziira worker --once` reports how many it made.
- Backups: pages, settings, pictures and publish history are in the master database, so the normal backup carries them.
- Untested live: the signed rebuild call has only been run against a fake transport. Try it once against the real build service
  before relying on it.
