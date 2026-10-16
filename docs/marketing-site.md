# Marketing website (`site/`)

A static, SEO-first website for the whole system, **in English only** (Swahili was removed from the site by owner decision; the web app
keeps its own Swahili). It presents **one product, Ziira**, with Intelligence as its smart part: pages are Product (`/product/` and seven
capability pages), Intelligence (`/intelligence/how-it-works/`, a six-step page; `/intelligence/` redirects there; and "use it with your existing system" with the source pages),
Solutions, Integrations (a card grid), Pricing and Get started (editions in plain words: Retail, Distribution, Books, Intelligence only,
Full), About, Security, Articles (`/guides/`) and a glossary. The term "Ziira Core" is not used on the site (a test fails if it appears).
Words are for business owners: no jargon (add-on, not plugin; alert, not finding), explained where unavoidable (API, webhook).
It is separate from the product web app (`frontend/`), which is a client-rendered SPA. Full documentation:
`site/README.md` (build, settings, structure) and `site/SEO.md` (intent map, technical checklist, post-launch steps).

```bash
make site-setup | site | site-build | site-check     # npm ci | dev :4321 | build to site/dist | tests + build + seo:check + links
cd site && npm run a11y | lhci | screens
```

* Hosting: serve the built `site/dist` folder as static files (headers template `site/public/_headers`, 301 map `site/redirects.json`).
* `PUBLIC_SITE_URL` must be the real origin before deploying; the build warns, `seo:check --production` fails.
* Editable facts live in `site/src/lib/siteConfig.ts` (planned source: the platform's public site endpoint).
* Copy rule: nothing on the site may be unverifiable against these docs; integrations not yet run live say so.

## Design system ("Daybook")

One stylesheet, `site/src/styles/global.css` (an external, hashed file; Astro inlines only tiny sheets; the audit caps CSS at 56 KB, raised from 40 KB when styles stopped being inlined into every page). Brand colours are the product app's tokens as
space-separated RGB (`rgb(var(--brand-strong) / .5)`); light and dark follow `prefers-color-scheme`. Pages reuse these classes, so a new page needs no new CSS.

* **Tokens**: `--bg --surface --sunken --line --ink --muted`, brand (`--brand --brand-strong --brand-deep --brand-soft`), the dark band (`--night`, `--on-night`, `--glow`),
  `--accent` (amber: highlights and the "example" badge only), status colours, `--radius`, `--max` (1200px), `--gutter` (20-64px), `--header`.
* **Type**: headings use *Bricolage Grotesque* (variable, Latin subset, 41 KB, self-hosted in `public/fonts/`, OFL licence beside it, preloaded in `Base.astro`);
  body text uses the system UI stack. Display sizes are fluid (`clamp`), body is 17px / 1.65.
* **Layout rules**: every section is full-bleed (`.section`, variants `.tint`, `.white`, `.dark`, `.tight`) and its content sits in `.container` (max 1200px).
  Running text keeps a 60-75ch measure (`.prose`, `.measure`, `.article`, `.container.read` for articles). Never put text directly in a full-width element.
* **Components**: `.btn` (`-primary`, `-ghost`, `-lg`), `.card` / `.card-link`, `.int-card` (icon tiles), `.pick` (big selector links), `.steps` / `.steps.three`, `.loop`
  (daily timeline), `.parts` (three dark cards), `.alerts` (example alert cards), `.bento` (screenshots), `.mini` (CSS-only illustration panels), `.table-wrap`,
  `.faq-split`, `.rows` (heading left, text right), `.glance` (what the page gives the reader), `.cta-band` (dark band that overlaps the footer), `.float` (hero callouts).
* **Header**: `src/content/nav.ts` is the one list of menus (labels in the words owners use: *What Ziira does*, *Who it is for*, *How it works*, *Pricing*, *Help*).
  `src/lib/nav.ts` resolves page ids to URLs and silently drops a link whose page does not exist. Menus open on hover and keyboard focus (`:hover`, `:focus-within`, no JavaScript);
  below 1040px the same lists show in a checkbox-toggled panel. The footer groups the same pages. `tests/nav.test.ts` checks every link.
* **App launcher**: `appTiles` in `content/nav.ts` is the list of coloured tiles (two-word label, icon, one line, colour 1-8 = `--t1..--t8`). The home page shows them as a grid and as the nodes of the
  "one platform" SVG diagram; the mega menu uses the same icons and colours. Tile colours are decoration only: text never sits on them except white icons.
* **Hero areas**: the home hero is a centred headline plus a composed product stage (screenshot in a frame, an *example* finding card and a summary card, all labelled demo data).
  Inner pages show either the page's screenshot (`hero`) or a "What you get on this page" card (`glance` in the page definition, else the page's own section headings as links).
* **Container and breakpoints**: `.container` is full width minus a 16-24px gutter (plus safe-area insets) below 700px, 90% from 700px, 80% from 1100px, capped at 1600px on ultrawide screens (beyond that the extra width stays as margin; sections stay full-bleed). Text blocks keep their own 60-75ch measure inside it.
  The desktop header and mega menu start at 1180px (the labels do not fit one line before that); below that the menu is a full-screen panel with checkbox accordions (no JavaScript; a tiny inline script closes it after a link tap). Home app tiles: 2 columns below 760px, 5 above (10 tiles do not split evenly in 3). Comparison tables become stacked cards below 720px (`data-label` on cells); other tables scroll inside a labelled region.
  Phones: body text 16px, tap targets at least 44px, buttons full width in the hero and call-to-action band, 16px form text (no iOS zoom), footer in two columns, floating hero cards stack under the screenshot. Help pages: the "All guides" drawer and "On this page" start closed below 1100px, and a tap on a step screenshot enlarges it (small script in `HelpLayout.astro`).
* **Responsive test**: `npm run responsive` (part of `make site-check`) opens 17 page types at 320, 360, 375, 390, 414, 600, 768, 1024 and two landscape phone sizes with touch emulation, plus the open phone menu, and fails on horizontal overflow, elements sticking out of the screen, text overflowing its box and tap targets under 44px (inline text links are checked by height only). It skips with a notice when Playwright is not installed (`make e2e-setup`).
* **Hero style**: the home headline uses *Gochi Hand* (OFL, Latin subset, 10 KB, `public/fonts/`, licence beside it), only for the headline and the handwritten note. A marker swash behind `h1Em`, a wavy underline under `h1Und` and an arrow from the note to the buttons are inline SVG paths drawn with `pathLength` for a draw-on animation that runs only without `prefers-reduced-motion`; all are `aria-hidden` and the H1 stays plain text. The hero's product stage rises out of an arc (`.section.arc`). `.hl` is the small marker highlight for a few section headings.
* **Motion**: CSS only (hover lifts, a slow float on the hero cards); everything stops under `prefers-reduced-motion`.
* **Honesty**: the hero's trust line contains only true statements (offline till, read-only on an existing system, built for several branches); the example finding is labelled.

## Claims to verify (flagged by the author)

- "Around 90 checks inside Ziira, about 20 on connected systems": from `docs/PROGRESS.md` (~90) and the standalone check table (22 listed).
- Product screenshots show the demo business (a Kenyan hardware business with three branches, KES) and are labelled "demo data" in every
  caption. They are regenerated, never edited by hand: see "Product screenshots" below.
- Retail/Distribution editions are described from `docs/registration.md`; `?edition=` links are not used because Register.tsx does not read it.
- Sales-document, offline-till and webhook statements follow `docs/offline-pos.md` and `docs/webhooks.md`.
- "No certifications, no independent penetration test yet": from `docs/security.md`; update when that changes.
- SAP Business One is in the Intelligence spec but has no connector: the site says it is not supported yet.
- The unsupported claim risks avoided on purpose: eTIMS (parked), AI against the live provider, WhatsApp/SMS/M-Pesa live (all marked "not yet run live").

## English only, and adding a language later

* Old Swahili URLs (`/sw/...`) and the old `/ziira-core/...`, `/ziira-intelligence/...` paths are 301-redirected to their English
  equivalents in `site/redirects.json` (written to `dist/_redirects`, `/sw/*` falls back to `/`). Keep these rows.
* The pages are still written per language (`Lang` type, `LANGS`, `LANG_PREFIX`, `Record<Lang, ...>` content), so adding one is:
  widen `Lang`/`LANGS` in `src/content/types.ts`, add `LANG_PREFIX`, page files (`*.xx.ts`, `home.ts`, `glossary.ts`, `integrations.ts`,
  `i18n/ui.ts`, `screens.ts`, legal banner), a language switch in `Header`/`Footer`, `alternates`/`x-default` in `src/lib/seo.ts` and the
  sitemap (the audit's `hreflang-*` rules are kept and become active as soon as alternates exist), and re-add the language to the tests.

## Help centre (`/help/`)

A step-by-step user guide, separate from the SEO articles (`/guides/`, nav label "Articles"). Ten journeys and about fifty guides, English only.
How it is built and how to add a guide: `site/README.md` ("Help centre"). Rules the guides follow:

* Every step was performed in the running app (demo business, plus a scratch business for the create-and-sell screens) and uses the labels on screen.
  Where a flow could not be completed or a label is guessed, the guide says so in a "Status" note. The audit lists bugs found in the app in the session report.
* Features that were never run against a live service (SMS, email, M-Pesa-type mobile money prompts, ERP connectors, Ask Ziira's AI provider, photo reading of statements)
  carry a **Status** note and are not described as working. Mobile money is a payment method with a provider, never country code (rule 15); M-Pesa is not named in step text.
* Pictures are crops of the web app with numbered circles, captioned "Demo data". They are regenerated with `npm run help:screens`.
* Help centre pages are in the sitemap, `llms.txt` and the nav ("Help"); the home page, Get started page and the web app (`VITE_HELP_URL`) link to it.
  Swahili: not provided (the website is English only; the web app's own Swahili is untouched).
* Claims to re-check before launch: the exact wording of the app's labels (they change), "Matched" and approval behaviour with approval rules switched on
  (tested only with no rules), credit increase approval, payroll steps after Calculate (read from the app's text, not run), and the two-step setup dialog (it
  stayed on "Loading" in the author's test run).

## Product screenshots (keep them current)

The marketing pictures are real captures of the web app, not mock-ups. They go stale whenever the app UI changes (new menu, renamed
tabs, new screens), so they are produced by a script and checked for staleness.

```bash
bash scripts/run_local.sh      # or the usual API :8000 + web app :5173 with the demo business (owner@demo-hardware.test)
make site-screens              # captures every picture, then rebuilds the optimised assets (about 4 minutes)
node scripts/capture-screens.mjs --only till,command    # (in site/) just some of them
```

* `site/scripts/capture-screens.mjs` signs in to the demo business, opens each route in `shots[]`, and writes `site/src/assets/screens/<key>.webp`.
  Framing is fixed: desktop 1440x1000 at 2x, phone 390x844 at 3x, light mode, no scrollbars/cursor/toasts; emails and phone numbers on screen are
  replaced by examples. Playwright comes from `e2e/node_modules` (`make e2e-setup` once). The till shots open a till on a free device (D1/D2 of a branch)
  and put three items in the cart without selling; if every device already has an open till, close one in the app (Sell > Tills and devices).
* `site/src/assets/screens/manifest.json` records, per picture: the page route captured, capture date, viewport, size and the git commit of the app
  (`+uncommitted` if `frontend/src` had local changes) plus the newest `frontend/src` file time.
* The site renders them through `components/Screenshot.astro` (AVIF + WebP at several widths, small WebP `<img>`, width/height set). Alt text and captions live
  in `src/lib/screens.ts` and must describe what is visible: **when you re-capture after a UI change, re-read the alt/caption of every picture and the
  page copy that mentions screens.** The keys are the `ScreenKey` type in `src/content/types.ts`.
* **When to re-run**: after any change to `frontend/src` that alters a screen shown on the site (menus, tab names, layout, new screens), before a
  release/launch, and whenever `npm run seo:check` / `make site-check` prints the warning below. Rule of thumb: at least monthly.
* `site/scripts/screens-stale.mjs` (run by `seo:check`, so by `make site-check`; also `npm run screens:stale`) prints a **warning, never a failure** for each
  picture that is older than `SCREENS_MAX_DAYS` (default 45), was captured before later commits that touched `frontend/src`, or is older than a newer
  `frontend/src` edit (uncommitted work counts), or has no manifest row.
* Adding a picture: add a row to `shots[]` in the capture script, a `ScreenKey` and an alt/caption in `screens.ts`, then use it as a page `hero`
  (page definitions in `src/content/pages/*.en.ts`) or in the home page gallery (`screens` in `src/content/home.ts`). Page image budgets
  (`seo:check`) apply.
* Known limits of the demo data: no suggested actions are waiting (Intelligence is at level 1), and the demo business has two stray test connections, so
  the Connected systems picture is cropped to the coverage panel (which reads 0% until something is connected).

## The complete guide to Intelligence (`/intelligence/complete-guide/`)

A long-form flagship page (kind `complete`): sticky contents with scroll-spy, 15 numbered sections, previous/next links, original SVG diagrams and annotated real screenshots (numbered pins at percentage positions in `content/completeGuide.ts`; re-check them after `make site-screens`).
* Text: `site/src/content/completeGuide.ts` (blocks); rendered by `components/CompleteGuide.astro`, `GuideBlock`, `GuideDiagram`, `GuideCatalog`, `GuideActions`; its own stylesheet `styles/guide.css` is loaded by a `<link>` on this page only.
* **Counts are never typed by hand.** `make site-catalog` (run by `site-build`/`site-check`) runs `scripts/export_check_catalog.py`, which loads the real registry (`intel.check`, `intel.action`, `intel.ask_tool`) and writes `src/content/checks.catalog.json`. Plain-language text per check/action lives in `checks.plain.json` / `actions.plain.json`; `tests/test_check_catalog.py` (backend) and `tests/complete-guide.test.ts` fail on a missing or stale entry or a hand-typed count; the audit rule `catalogue-count` checks the built HTML.
* Budgets: pages with `data-longform` may be up to 300 KB HTML and 80 KB CSS. "Last reviewed" is the build date (`SITE_BUILD_DATE` overrides). JSON-LD: TechArticle, FAQPage, BreadcrumbList.
* Linked from the Intelligence hub, the mega menu, footer, home daily-check section, the Help centre's Intelligence journey, `llms.txt`, and (in the app, when `VITE_SITE_URL` or `VITE_HELP_URL` is set) the Command Center and Findings headers.
* Claims to verify: the AI cost answer states no price; "independent security test: on our list"; coverage matrix cells come from `docs/connectors.md`.


## Writing style (guides, Help centre, the Intelligence step-by-step page)

Straight to the point, in plain words (owner decision, 2026-10-16): menus and cards land on real content, never on a page that only links onward.
Short sentences (about 25 words at most), paragraphs of at most 4 lines, at most 2 internal links per paragraph, reading grade about 7.
Banned in guide and help text: baseline (say "your normal"), finding (say "thing to look at"; the old word may appear once with a note where the app still shows it), connector, endpoint,
OAuth, webhook, extension point, plugin (say "add-on"), tenant, provider, idempotent, RLS, cursor, schema, coverage matrix, entity, "out of the box",
leverage, robust, seamless, "end to end", "read-only key". `tests/style.test.ts` fails on the banned list and prints warnings for long sentences/paragraphs,
link-heavy paragraphs and the worst reading grades. Help guides: title as the goal, one short intro sentence, numbered steps (one action each, real
button names in bold), "You should see" in one line, 1 to 3 problems, at most 2 "Next" links, no tips, no "before you start" unless something is truly required.

## Availability switch

The site is written for customers, not as a status report: no internal-status language ("not tested", "stand-in", "pilot test", "not built yet", "no certifications"; enforced by `site/tests/availability.test.ts`). Every capability that depends on an outside service has one entry in `site/src/content/availability.ts` and is `available` by default. To hold an item back, set it to `soon` in that file and rebuild: a "Coming soon" chip, a one-line note and a "Get notified" link appear and pages stop promising it. `docs/go-live-checklist.md` stays the owner's internal manual-test list.
