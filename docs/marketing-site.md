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

## Design system (navy theme, from the owner's homepage mockup)

One stylesheet, `site/src/styles/global.css` (external, hashed; the audit caps CSS at 66 KB). The theme follows the owner's mockup (`ziira_homepage_mockup (3).html`): navy `#0B0F1A` page with deeper layers `#111827`/`#172238`, blue `#2B7CFF`, cyan `#24B9C7`, green `#10CD8D`, the gradient `linear-gradient(110deg,#2B7CFF,#24B9C7 52%,#10CD8D)`, Inter, pill buttons, a 1160px container. The site is dark-themed with light bands; it no longer follows `prefers-color-scheme`.

* **Two colour contexts, one set of tokens.** `:root` is the LIGHT context (content bands: white, `.tint` = `#F4F6F9`). The DARK context (header, announcement, home hero and strip, `.page-head`, `.section.dark`, `.cta-section`, footer, `.on-dark`) re-declares the same tokens (`--bg --surface --sunken --line --ink --muted --brand*`), so every component works in both. Tokens are space-separated RGB (`rgb(var(--ink) / .5)`). Brand blue on light is `--brand-strong` (#1F63D8, AA on white and on #F4F6F9); on dark it is a lighter blue. Gradient text: `.gradient-text` / `.hl` use a brighter gradient on dark and a darker one (`--grad-text`) on light so large headings keep 3:1.
* **Buttons**: `.btn-primary` = gradient with navy text `#06111c` (4.9:1 on the blue end, more on the rest); `.btn-ghost` adapts to context; `.btn-light`. Headings Inter 800 (h1, letter-spacing -0.065em) / 700.
* **Fonts**: Inter 400/600/700/800, Latin subset, self-hosted in `public/fonts/` (from `@fontsource/inter`, OFL licence beside it); 400 and 800 are preloaded in `Base.astro`. No runtime third-party requests. Bricolage Grotesque and Gochi Hand were removed.
* **Logo**: `components/Logo.astro` is an inline SVG recreation (white/`currentColor` wordmark, gradient dots mark; `uid` keeps the gradient id unique). Files: `public/brand/ziira-logo-on-dark.svg`, `ziira-logo-on-light.svg`, the owner's PNG `ziira-logo-on-dark.png` (kept as supplied), `public/favicon.svg` (navy tile, "z" and dots) and the PNG icons from `scripts/make-icons.mjs`. The SVG is a hand-built approximation of the PNG, not the original artwork: replace it when the designer supplies a vector.
* **Layout rules**: every section is full-bleed (`.section`, variants `.tint`, `.white`, `.dark`, `.dark.flat`, `.tight`); content sits in `.container` (max 1160px, side gutter 16-28px plus safe-area). Running text keeps a 60-75ch measure.
* **Components** (unchanged names): `.btn`, `.card`, `.int-card`, `.steps`, `.trust`, `.glance`, `.faq-split`, `.rows`, `.cta-band` (now a centred navy closing band), `.table-wrap`; new for the home page: `.strip` (works-with strip), `.problem-*`, `.evidence-panel`, `.daily`, `.arch-*`, `.cap-*`, `.use-*`, `.integration-*`, `.source-row`, `.teaser`.
* **Header**: sticky, blurred navy, white logo, mega menu opens on hover/focus (no JavaScript) from 1180px; below that a full-screen panel with checkbox accordions. Footer: grouped like the menus, on `#080C14`.
* **Home page order** (follows the mockup): hero with a perspective product frame (the real Today screenshot, an example card labelled demo data) > works-with strip (real integrations from `content/integrations.ts`, anything held back in `availability.ts` is left out) > "why a daily check" (quote + the three example alerts) > daily check (four steps + example summary panel) > Run/Watch/Connect cards > capability grid (app tiles) > one-platform diagram > what you can do (numbered cards + kinds of business) > product screenshots > start in three steps (`#how-it-works`) > comparison > connect your tools (dark) > trust > pricing teaser > FAQ > closing CTA. Content stays in `content/home.ts` (new fields `stripLabel`, `problem`, `intel`).
* **Motion**: hover lifts and a slow float on the hero card only; all stop under `prefers-reduced-motion`.
* **Honesty**: the strip lists only integrations that exist; the example finding and summary are labelled demo data; the mockup's placeholder partner names, numbers and text are not used.

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

A step-by-step user guide, separate from the SEO articles (`/guides/`, nav label "Articles"). Sixteen journeys and about eighty-six guides, English only. The service-business journeys (First week by kind of business, Bookings, Jobs, Time and projects, Memberships, Files) were written from the app's English labels and docs, without screenshots.
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


## Positioning and Ziira AI (2026-10-19, owner request)

Ziira is presented as the AI-first business system for every kind of business (shops to salons, garages with insurer claims, clinics, gyms, agencies, schools), AI at the centre.
* Home: the hero, then ONE slim dark strip (`section.ask-strip#ai`, button "Ask Ziira anything" with `data-ask-ziira`), then the rest as before. The big AI sections (animated conversation, daily work, AI by area, rules, providers) were removed by owner decision ("too much"); the proof is the live assistant below.
* `/ai/` (nav "Ziira AI", footer): kind `ai`, short: five plain lines of what it does, one short list of safety rules, the Ask button and a small FAQ. Copy in `src/content/ai.ts` (`does`, `safety`, `strip`, `pageFaq`).
* Numbers (checks, areas, next-step kinds, lookups) come from `checks.catalog.json` through `lib/catalog`; `tests/ai-content.test.ts` guards that and bans invented proof words.
* "Who it is for": `/solutions/every-business/` first, then retail, distribution, multi-branch, salons, garages, clinics, gyms, consultants (`content/pages/ai.en.ts`). No dedicated schools page: there is no education pack yet.
* Budgets (`scripts/lib/rules.mjs`): HTML 86 KB (was 80: the richer menus add ~6 KB to every page and the home page was 81.7 KB), CSS 67 KB (was 66: the strip). The `data-showcase` budgets are gone. The chat is not counted: it loads lazily.
* The hero CTA is "Get started", not "Start free": trial terms are platform data.


## Floating "Ask Ziira" (2026-10-19, owner request)

A round gradient button, bottom right of every page (not 404, not `/get-started/`), opens a phone-style chat (device frame, status bar, header with avatar, "AI" badge and green online dot, bubbles, input bar, home indicator; full screen without the bezel under 521 px). Live answers from the Ziira API, never invented client-side.

* Files: `src/components/Assistant.astro` (in `layouts/Base.astro`) adds `public/assistant.js` (about 6 KB, about 2.5 KB gzipped, deferred): after load/idle it loads `assistant.css` and **always** adds the button (owner decision 2026-10-19: "the website assistant should always be there"; it never reads the config route to decide, tested in `tests/assistant-launcher.test.ts`), then loads `assistant-chat.js` on idle or on the first click and asks `GET <api>/api/v1/public/assistant/config` (4 s timeout; cached in `sessionStorage` only when `enabled` is true). Every "Ask Ziira anything" link (`data-ask-ziira`) opens the same chat, and stays an ordinary link to `/ai/` until the script runs.
* **Limited mode.** If the config call fails or is blocked (CORS, network), or says `enabled: false` (no AI provider in use, a spend ceiling or the daily total reached), the chat still opens: the greeting (the API's, else a built-in line), then "I can't answer live right now. These pages should help:" with plain links to Pricing, Who it is for, Security and Get started or contact us (urls from `data-*` attributes built with `urlFor`), no quick-reply chips, a disabled input ("Live answers are paused") and a grey status dot. If a live question later gets an `off` or `budget` error, the chat switches to the same state. Nothing is ever answered client-side.
* **Look (owner request 2026-10-19: "like WhatsApp 100%").** The conversation screen inside the phone frame imitates a familiar messaging app, using only CSS and SVG drawn here (no logo or copied artwork): teal header (`#008069`, dark `#1F2C34`) with a back arrow (closes), a white round avatar with the Ziira mark, the name "Ziira", a subtitle that is `online` or `typing…` while an answer is being composed (also `answers paused` in limited mode) and a kebab menu with "New chat" and "Close"; a beige wallpaper (`#EFEAE2`, dark `#0B141A`) with a faint repeating doodle pattern (inline SVG data URI, 5-7% opacity); a "Today" date chip and a pale yellow notice ("Ziira's assistant is AI. Answers come from Ziira's public pages. Please do not share personal or business data."; it does not claim encryption); bubbles with a tail on the first of a group, time stamps, and for the visitor's messages one grey tick (sent), two grey (delivered, response headers received) and two blue ticks `#53BDEB` (Ziira has started answering); a white three-dot typing bubble; quick replies as stacked white reply buttons with teal text; link previews with a teal left strip, bold title and grey address; a composer with an inert smiley and paperclip, the placeholder "Message" and a round teal button that is a microphone when empty (it only focuses the input), a send arrow with text and a stop square while answering. The palette follows `prefers-color-scheme: dark`; pop-in, smooth scrolling and tick transitions are off under `prefers-reduced-motion`. System font stack, 14.2px message text. Colours are CSS variables (`--wa-*`) on `.zr-root` in `public/assistant.css`.
* **The invitation (owner request 2026-10-19: "auto open the mobile window").** On the home page, `/ai/`, `/pricing/` and the `/solutions/...` pages only (never the 404 page, `/get-started/`, legal pages, the Help centre or any other page), once per browser session (`sessionStorage` key `zr-assistant-seen`, set when it fires and when the visitor opens or closes the chat by hand, so a visitor who closes it never sees it open again that session), about 2.5 s after load:
  * **Tablet and desktop (521px and wider):** the phone-shaped window opens by itself at bottom right (the round button hides while it is open). Typing dots show for about a second, then the greeting and the quick-reply chips appear (no dots and no motion under `prefers-reduced-motion`). It is *passive*: no overlay, the page behind is not inert and scrolls normally, no scroll lock, keyboard focus is not moved into it, and nothing is announced to screen readers. It becomes an ordinary dialog (focus trap, announcements) only when the visitor clicks, taps or tabs into it. Closing it (x or Escape) ends the invitation for the session.
  * **Phone widths (520px and below):** the chat is a full-screen sheet, so it is **never** opened automatically (intrusive interstitials are penalised by search engines and annoy visitors). Instead a small bubble "Hi, ask me anything about Ziira" appears above the round button after 2.5 s and goes away on click (which opens the chat), on scroll, or after 8 s.
  * The rules are the pure function `autoMode(path, narrow, alreadySeen)` in `public/assistant.js` (exposed as `window.ZiiraLauncher`), tested in `tests/assistant-launcher.test.ts`.
* API host = the app host (`siteConfig.appUrl`); `PUBLIC_ASSISTANT_API_URL` overrides it at build (mock or separate host). CSP: `public/_headers` has `connect-src 'self' https:`; narrow it to the app host when deploying. **`deploy/installer/nginxconf.py` (site CSP, line 26) still says `connect-src 'self'` and must allow the app host too.** CORS for the site origin, no cookies (`credentials: "omit"`).
* Contract: `GET /api/v1/public/assistant/config` -> `{enabled, greeting, suggestions[]}`; `POST /api/v1/public/assistant/stream` body `{message, history:[{role:"user"|"assistant",text}] (last 6), page: location.pathname, lang:"en"}` -> SSE `status {text}`, `text {text}` (one sentence or list line each; lines starting `- `, `* `, a bullet or `1.` render as list items; plain text only), `links {items:[{title,href}]}`, `done {}`, `error {reason: off|busy|budget|provider_failed|too_long, message, retry_after?}`. Errors show the message with Try again (not for off/budget/too_long; `retry_after` counts down) plus "Open pricing" and "Contact us" links.
* Behaviour: message appears at once, typing dots with the live status line, text typed word by word (click a bubble to skip; instant under `prefers-reduced-motion`), suggestion chips (config, with built-in defaults), link cards, Stop button, 500-character limit with a counter from 400, Enter sends, Esc closes, focus trap with the page made `inert`, `role=dialog`, `role=log aria-live=polite`, conversation kept in `sessionStorage` across pages, privacy note under the input.
* Develop without the API: `node site/scripts/mock-assistant.mjs [port]` (default 8099; canned events; words "error", "busy", "off", "long", "cut" trigger each path; `MOCK_OFF=1` makes config say `enabled: false`, which shows limited mode; point `PUBLIC_ASSISTANT_API_URL` at an unreachable address to see the unreachable case), then `PUBLIC_ASSISTANT_API_URL=http://localhost:8099 npm run build` and serve `dist`.

### Knowledge file: `dist/assistant-knowledge.json`

Written on every build by `src/pages/assistant-knowledge.json.ts` from `src/lib/knowledge.ts` (so `make site-build` and `make site-check` produce it; the API reads it from the site dist folder). A JSON array of chunks:

```json
{ "id": "pricing", "title": "Pricing", "url": "/pricing/", "text": "plain text, 150 to 300 words (a few shorter tail chunks)..." }
```

`id` is unique (`<page>-<n>` when a page needs several chunks), `url` is the site path (prefix with the site origin) of a built page, `text` is plain text (no HTML or Markdown). Sources: home, product, solutions (every business first), the AI page, intelligence and each source page, integrations with their availability (`availability.ts`, so "Coming soon" items say so), security and privacy, about, get started, pricing (published plans, or a plain "none published"), FAQs, the checks in numbers from `checks.catalog.json`, and the Help centre's journeys with every guide's title and summary. Sentences naming a country, a country-specific service or invented proof are dropped, and the mobile-money integration is described generically. Guarded by `tests/knowledge.test.ts` (packing and banned words) and the audit rule `assistant-knowledge` in `scripts/lib/rules.mjs` (valid JSON, at least 10 chunks, at most 300 words, plain text, banned words, every url a built page); the audit also requires the assistant files.
