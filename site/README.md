# Ziira marketing website

Static, pre-rendered HTML (Astro, TypeScript, hand-written CSS using the product's design tokens). Near-zero client JavaScript
(the header menus are CSS `:hover`/`:focus-within`, the mobile menu is a CSS checkbox, the FAQ is `<details>`, the contact form is a plain HTML form). The product app lives in
`frontend/`; this site is separate so that search engines get real HTML. **Plan and checklist: `SEO.md`.**

```bash
make site-setup        # npm ci
make site              # dev server on http://localhost:4321
make site-build        # static build into site/dist
make site-check        # unit tests + build + SEO audit + link check
npm run a11y           # axe on key pages, light/dark/phone (needs `make e2e-setup` once: uses ../e2e/node_modules)
npm run responsive     # overflow, clipped text and 44px tap targets at 320-1024 widths and landscape, touch emulation (same Playwright setup)
npm run lhci           # Lighthouse (via npx) mobile and desktop against the build; fails below 95
make site-screens      # re-capture ALL marketing screenshots from the running app (:5173 + API :8000, demo business) and rebuild; `npm run screens:stale` lists out-of-date ones
npm run typecheck      # tsc over the TypeScript files (astro check does not support TypeScript 7 yet)
```

## Settings (build-time, all public; see `.env.example`)

| Variable | Meaning |
|---|---|
| `PUBLIC_SITE_URL` | **This site's canonical origin.** Unset or a placeholder (`https://example.invalid`): the build warns loudly (`SITE_STRICT=1` fails it) and `seo:check --production` fails |
| `PUBLIC_APP_URL` | The product web app (Sign in `/`, Get started `/register`); default `http://localhost:5173` |
| `PUBLIC_CONTACT_URL` | Form action for the contact form (static form, honeypot, no JavaScript). Unset: a notice is shown |
| `PUBLIC_CONTACT_EMAIL` | Shown as plain text (never a mailto link) when set |
| `PUBLIC_ORG_NAME`, `PUBLIC_ORG_LEGAL_NAME`, `PUBLIC_SOCIAL_URLS` | Names and profiles for the footer and Organization JSON-LD |
| `PUBLIC_LEGAL_REVIEWED` | `true` only after a lawyer reviewed Privacy and Terms; until then they are `noindex` templates (published legal pages from the platform replace the templates) |
| `PUBLIC_PLATFORM_API_URL` | The platform whose Super Admin publishes this site's content. The build fetches `{url}/api/v1/public/site`, keeps `.cache/platform-site.json` and copies the pictures to `public/media/` (both git-ignored). Unset: the cached copy, else the committed placeholder `content-snapshot.json` |
| `PLATFORM_SNAPSHOT_FILE` | CI and tests: read the content from this JSON file instead of the platform (`tests/fixtures/platform-real.json` is a real-looking payload) |

## Content from the Super Admin

Every editable fact (names, contact, social links, SEO defaults, announcement banner, plans/prices, legal and content pages, logo and
favicon) is edited in the platform's Super Admin (Website) and published through `GET /api/v1/public/site`. The build reads it in
**one place**: `src/lib/platform.ts` fetches it (live, else cached, else the placeholder seed) and `src/lib/siteConfig.ts` turns it into
`siteConfig`; pages never read the payload directly. The environment variables above only fill what the platform does not supply.
A publish in the Super Admin calls the build hook, and the rebuild runs `npm run build`, which pulls the fresh content.

- **Production builds warn loudly** (`DO NOT DEPLOY`, and fail with `SITE_STRICT=1`) when not on real published content: live fetch
  failed, nothing published, placeholder seed in use, or placeholder text remains. Development builds are quiet.
- Footer, contact page, banner, legal pages, pricing and Organization JSON-LD all render from `siteConfig`. Privacy and terms keep
  their addresses; other published legal/content pages become `/<slug>/` (`src/lib/cmsPages.ts`) and are linked
  from the footer. Pricing (`components/PricingPlans.astro`) shows exactly the published prices, a period and currency choice that
  works without JavaScript, and "contact us" for custom plans or a missing price.
- `tests/platform.test.ts` (loading, fallbacks, mapping, pricing) and `tests/platform-build.test.ts` (three full builds: real content
  renders and passes the SEO audit; seed in production warns; strict fails) cover it. Full description: `docs/platform-admin-content.md`.

## Where things are

```
src/content/pages/*.en.ts            page text as data (one PageDef per page; kind "hub" = Product and Intelligence card pages)
src/content/integrations.ts          the Integrations page: cards, status chips, steps (plain words)
src/content/home.ts                  the home page (hero, scenarios, steps, FAQ)
src/content/nav.ts, src/lib/nav.ts   the header menus and footer groups (labels in owners' words; links to missing pages are dropped)
src/styles/global.css                the design system (tokens, layout rules, components): see docs/marketing-site.md "Design system"
src/components/Home.astro            the home page layout; PageHead.astro = inner page heads (screenshot or "what you get" card)
src/content/guides/*.md              the nine guides (frontmatter: title, description, h1, date, topic, faq, related)
src/content/glossary.ts, legal.ts    glossary terms; legal TEMPLATES
src/lib/registry.ts                  every page, its URL, alternates, breadcrumbs; links in text are [label](@page-id)
src/lib/platform.ts, cmsPages.ts     the platform's published content (fetch, fallbacks, warnings) and its pages as page definitions
src/lib/schema.ts, seo.ts            JSON-LD and head metadata
src/pages/[...path].astro            the one route that renders every page kind
src/pages/*.ts                       sitemap.xml, robots.txt, llms.txt, guides/feed.xml, site.webmanifest, og images
scripts/lib/rules.mjs                the SEO audit rules; tests/ has a broken fixture per rule
public/_headers, redirects.json      security/caching headers (template) and the 301 map
```

Adding a page: add a `PageDef` in `src/content/pages/*.en.ts`, link to it from a parent or footer (orphans fail the audit), add its row to `SEO.md`.
Adding a guide: add a Markdown file; it is listed, in the feed, sitemap and llms.txt automatically.

## Help centre (step-by-step user guide)

`/help/` is a docs-style user guide: ten journeys (Get started, Sell, Stock, Buy, Customers and credit, Money, People, Ziira Intelligence, Add-ons and
settings, Help and support) with about fifty guides. It is separate from the SEO articles under `/guides/` (nav label "Articles"): the articles
are essays for people searching a question, the Help guides are instructions for people using the product. **English only** (the website has no
Swahili version).

```
src/content/help/*.ts        one file per journey; each guide is data: title, who, time, need, numbered steps (bold UI labels exactly as in the app,
                             "You should see", an annotated screenshot), three problems with fixes, tips, next steps; types.ts says what each field means
src/lib/help.ts              loads and checks the guides (title length, links), gives the registry its page definitions, reading order
src/lib/helpSchema.ts        HowTo JSON-LD (one HowToStep per visible step) added next to the BreadcrumbList
src/components/HelpPage.astro, HelpLayout.astro, HelpShot.astro, HelpSearch.astro, help.css     the pages, sidebar, "On this page", figures, search
src/pages/help/search-index.json.ts   the search index, built with the site; the search box works as a link to /help/a-z/ without JavaScript
scripts/capture-help-screens.mjs + help-screens.shots.mjs   Playwright: sign in, open each screen, draw numbered circles, crop, write src/assets/help/*.png
```

* **Writing a guide:** add an object to the journey's file (it appears in the sidebar, A to Z list, search, sitemap, `llms.txt` and the OG images by itself),
  give it a screenshot `key`, add that key to `scripts/help-screens.shots.mjs` with one `marks` entry per `legend` item, run `npm run help:screens -- --only key`.
  `tests/help-content.test.ts` fails if a guide has fewer than three steps or problems, no screenshot, a legend without marks, a dead link or a missing picture.
* **Verify every step in the app before writing it** and use the labels as they appear on screen. When the app changes, re-run the capture and re-read the
  guides that mention the changed screen (search the content folder for the label).
* **Screenshots:** `npm run help:screens` needs the app on `:5173`, the demo business (`owner@demo-hardware.test`) and a scratch business for the
  screens that create things (`HELP_SHOP_EMAIL` / `HELP_SHOP_PASSWORD`; make one with `ziira create-tenant "Helpdoc Shop" --code helpdoc-shop ... --edition retail`,
  then move it to Distribution on the Add-ons page, set up a unit, price list, location, till, a product, a customer, a supplier, an order...). The scripts
  use demo data only; every figure is captioned **Demo data**. The app's own language stays English for the pictures.
* **SEO rules for guides** (`scripts/lib/rules.mjs`, tests in `tests/help-rules.test.mjs`): at least 3 numbered steps, a screenshot with alt text in the steps,
  at least 3 "If something goes wrong" items, a "Before you start" list, a "Next steps" link, HowTo JSON-LD whose steps match the page, no orphan pages.
* **In the app:** set `VITE_HELP_URL` (for example `https://example.com/help`) when building the web app to show a **Help** item in the account menu and a
  "How-to guide" link on the Home checklist steps. Unset, nothing is shown.

## Serving

Serve the built `site/dist` folder as static files with the headers in `public/_headers` (copy them into your web server's
configuration if it does not read that file) and the redirects in `dist/_redirects` (same). `404.html` is the not-found page.
Hosting details are not documented here.

## Security headers

`public/_headers` ships a strict policy (no third-party scripts, fonts or embeds exist): `Content-Security-Policy`, HSTS,
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, long caching for hashed assets, short for HTML.
The CSP allows `form-action https:` so the contact form can post to `PUBLIC_CONTACT_URL`; tighten it to that origin once known.
The product app's CSP is separate (`docs/operations.md`).

## Honesty rules for content

Everything stated about the product must be checkable against `docs/` and the code. No prices, ratings, customers, logos,
testimonials or certifications are invented. Integrations that were never run against a live service say so on their page.
M-Pesa appears only as a country plugin example. Legal text is a template until reviewed. See "Claims to verify" in `docs/marketing-site.md`.

## Known limits

- English only. The Swahili site was removed (old `/sw/` URLs redirect); `docs/marketing-site.md` says how to add a language back.
- `?edition=` deep links are not used: the app's Register form does not read that parameter yet.
- `npm audit` reports a moderate advisory in `fflate` (via `satori`, build-time only, parses no untrusted ZIPs).
