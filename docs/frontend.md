# The web app (`frontend/`)

React + TypeScript + Vite + Tailwind. A **shell** (sign-in, layout, router) plus **modules** that mirror
the backend units: a module appears only when the business has that unit enabled, and each page, menu
item and slot contribution only for users holding its permission.

```bash
make web-setup     # npm ci
make web           # http://localhost:5173 (proxies /api to :8000, so start the API first)
make web-check     # lint, types, tests, build (CI runs it)
make api-types     # regenerate src/api/schema.d.ts after backend route/schema changes (CI checks it is committed)
```

Demo sign-in: `owner@demo-hardware.test`, `demo-pass-123` (no workspace code; the screen asks which business only if the same login works for several).

## Layout

```
src/shell/      sign-in/register, layout (menu from active modules, command palette), home dashboard, error boundary
src/sdk/        the only thing modules import: api client, session, <Slot>, UI parts, i18n
src/modules/<unit>/   module.ts (manifest), pages/, slots/, i18n/en.json + sw.json, public.ts
src/api/schema.d.ts   generated from the backend; never edit
```

`src/operator/` is not a module: it is the platform staff's console (`/operator`, `docs/security.md`), a separate lazy-loaded app with its own sign-in
and session, API client (operator token, never the business token), translations namespace `operator` and tests. It reuses the kit from `@/sdk`.

## Adding a module

1. Create `src/modules/<unit>/module.ts` with `defineModule({ unit, routes, menu, slots, translations })`
   (`unit` = backend unit name; the kernel's own screens use `"kernel"`). Every route needs a permission (or `anySignedIn: true` for pages every signed-in user may open).
2. List it in `src/modules/index.ts`.
3. Provide English and Swahili strings with the same keys (a test checks it).

## Slots (screen sockets, the frontend twin of extension points)

A page offers `<Slot name="products.product.tabs" props={{ productId }} />`; other modules contribute
under `slots` in their `module.ts`. The slot name is exported from the owner's `public.ts`.
Contributions appear only when their module is active and the user has the permission.
Slots offered today: `dashboard.widgets` (shell), `products.product.tabs` (Products), `command.panels` (Command Center; Intelligence puts
the Ask Ziira panel there).

## Rules (ESLint enforces them)

Modules import only `@/sdk`, their own files and other modules' `public.ts`. Call the API with the typed
`api` client, never raw `fetch`. Access tokens live in memory; the refresh token is in localStorage.


## Design system and screen patterns

The look lives in two places: **tokens** (`src/index.css` CSS variables, mapped to Tailwind names in `tailwind.config.js`: `bg`,
`surface`, `sunken`, `line`, `ink`, `muted`, `brand`, `ok`/`warn`/`bad`/`info` with `-soft`) and the **kit** in `src/sdk/ui/`
(exported from `@/sdk`). Never use raw colours (`slate-500`, `#fff`); use the tokens, so dark mode and re-branding work.

| Need | Use |
| --- | --- |
| Page frame | `PageHeader` (title, description, actions, `back`), `Card`, `Tabs`, `Stat`, `DetailList`, `FormGrid` |
| Tables | `DataTable` (loading skeleton, error + retry, empty state, search, sort, client paging, row links, responsive columns); server-paged lists use `usePagedList` + `Pager` |
| Forms | `Field` (label, hint, error) around `Input` / `Select` / `Textarea` / `NumberInput` / `Combobox` / `Checkbox` / `Switch`; state with `useFormState` (server field errors via `f.fail(error)`) |
| Create / edit | a `Drawer` (or `Modal` for short ones) with `<form id>` and footer buttons using `form="id"`; success -> `toast(..., "ok")`, invalidate the list query, close |
| Irreversible or money-moving actions | `ConfirmDialog` first |
| Status | `StatusBadge status="posted"` (colours by code), `Badge tone=...` |
| Feedback | `toast(text, tone)`, `Alert`, `EmptyState`, `ErrorState`, `Skeleton` |
| Numbers | `money(value, currency)` with `useCurrency()`, `quantity`, `percent`, `formatDate`, `today()`; amounts from the API are decimal **strings**: display them, never do money arithmetic in the browser (the backend owns it) |

Rules every screen follows:

1. **Every request goes through `unwrap(api.GET(...))`** in a query or mutation, so a failure is an error state with a retry, never an
   empty list. Queries: `useQuery({ queryKey, queryFn: () => unwrap(...) })`; show `error.message` and `refetch`.
2. **Every state is designed**: loading, empty (with a next step), error (with retry), no permission (the route is hidden; buttons use
   `useCan`).
3. **Mutations** show success with a toast. Failures toast automatically (the app's mutation cache); add `meta: { silent: true }`
   and show field errors yourself when the form maps them (`onError: f.fail`).
4. Anything a client may send twice (a sale, a payment) uses a client-made `local_id` / `Idempotency-Key` and is disabled while
   pending.
5. Menu entries set `area` (see "Navigation") and `icon` (see `src/sdk/icons.tsx`).
6. English and Swahili strings with the same keys (a test checks it). No text in components.
7. Works at phone width (tables hide low-priority columns with `hideBelow`), keyboard friendly, labelled controls, 44px-ish targets.
8. No country in code: currency, tax names, phone codes come from the company and the API.

## Theme (colours, type, shapes)

The theme is the owner's brand system, taken from three mockups (app shell, sign-in, website). It lives only in tokens and the shared kit, so
a module picks it up without edits. Change the look in `src/index.css` (variables) and `tailwind.config.js` (names), never in a module.

- **Brand colours**: navy `#0B0F1A` (`navy`), blue `#2B7CFF` (`brand`), cyan `#24B9C7` (`cyan`), green `#10CD8D` (`mint`). The signature gradient
  (`linear-gradient(110deg, blue, cyan 52%, green)`, variable `--gradient`) is used for the primary button (`Button` primary = class `btn-gradient`),
  the active-page accent bar, progress bars and the brand mark. Utilities: `bg-brand-gradient`, `text-brand-gradient`, `btn-gradient`.
- **Text on the gradient is navy, not white**: white fails 4.5:1 on cyan (about 2.3) and on blue (3.9); navy is 4.9 on blue and 8+ on cyan/green.
  `brand-ink` is that navy (use it on any filled `bg-brand`). `bad-ink` / `ok-ink` are the text colours for filled danger / success (white in light, navy in dark).
- **Surfaces**: `bg` page `#F5F7FA`, `surface` white panels with a 1px `line` border and 12px radius (`rounded-xl`), `sunken` for quiet fills. Controls are 10px
  (`rounded-[10px]`, 40px high), buttons 9px (`rounded-lg`). Shadows are soft (`shadow-card`, `shadow-pop`).
- **Text**: `ink` `#182334`, `muted` is `#5F6B7F` (the mockup's `#718096` is only 4.0:1 on white, so it was darkened to pass 4.5:1). Links and active
  navigation use `brand-strong` (a deep teal in light, a light cyan in dark), on `brand-soft` pale teal.
- **Status colours** (`ok`, `warn`, `bad`, `info`, each with `-soft`): the text colours are darkened versions of the mockup's pills so they pass 4.5:1 on their
  soft background; `indigo` is the fourth chip colour of the Home cards. `Badge` is a small rounded-rectangle pill.
- **Dark mode** (`html.dark`) uses the same navy: page `#0B0F1A`, panels `#121826`, lines `#263046`, brighter brand and status colours.
- **Type**: Inter 400 to 800, self-hosted from `src/fonts` (latin subset; the content-security policy allows fonts from this site only, so no Google Fonts).
  Headings use tight negative letter-spacing (`h1` -0.03em). `eyebrow` (class) is the small uppercase grey label (sidebar sections, detail-list labels, the date above Home's greeting).
- **Focus**: every focusable element gets a 3px ring in the brand blue at 45% (`:focus-visible` in `index.css`).
- **Shell**: sidebar 250px (68px collapsed): brand mark and name with the collapse button on the right, a business block (initial, company name, currency) under it,
  sections as small uppercase labels, pages with a pale-teal active row and a gradient accent bar, Add-ons and Settings pinned at the foot. Top bar 76px (64px on a phone):
  rounded search field, account menu with name and business. The Super Admin console uses the same tokens and shapes.
- **Sign-in and sign-up**: `shell/AuthShell.tsx` is the split layout of the login mockup: a navy panel with electric line art (inline SVG), the tagline and subtitle
  (`auth.tagline`, `auth.subtitle`) and the wordmark, beside a light form panel (a compact navy strip above the form under 768px). Auth forms get 48px fields (`.auth-form`).
  The sign-up wizard (`register/RegisterLayout`) keeps its own wizard layout, themed with the same tokens.
- **Logos**: `BrandMark`, `Wordmark` (strokes, `tone="dark"` for navy backgrounds) and `BrandName` in `sdk/ui/brand.tsx`; SVG files `public/brand/ziira-mark.svg`
  (favicon) and `ziira-logo.svg` for light backgrounds. `ziira-logo-on-dark.png` is kept for reference only.
- **Rules for modules**: use tokens only. A filled button is `Button` (never hand-made `bg-brand-strong`); text on a filled `bg-brand` is `text-brand-ink`;
  blue text on white (`text-brand`) fails contrast, so a link is `text-brand-strong`.

## Navigation: areas and sidebar sections

The sidebar has Home, then **every area at once**: a section heading (icon and title) followed by its pages, a thin divider between sections, no accordion
and no remembered state; the sidebar scrolls. Settings and one-page areas (Connected systems, Add-ons) are plain links; Add-ons (`/addons`, formerly Apps & plugins in Settings, then Features; `/admin/apps`, `/features` and `/plugins-store` redirect; the display name is the single key `nav.areas.addons` and the route is `ADDONS_PATH` in `modules/admin/paths.ts`, so a rename touches only those and the hint strings that mention it) is a full-width page just above Settings, and Point of sale is a filled button at the top of
Sell. Each page is its own page with its own URL and header; only pages that are the same kind of list share one sidebar entry and a small tab bar
(Quotations | Sales orders, see `under`). Collapsed to icons, hovering or focusing an area shows its pages in a flyout; the phone drawer lists everything the same
way. Pages are about 14px rows (32px high) with a tinted background, stronger text and an accent bar when active, a hover state and a focus ring; contrast is
at least 4.5:1 in light and dark. Pure rules: `sdk/areas.ts` (tests in `sdk/areas.test.ts`); drawing: `shell/Sidebar.tsx`; the tab bar and Settings' own grouped
list: `shell/AreaFrame.tsx`. There is no area-level tab bar.

**Settings** is about eight plain entries (Overview, Business, People and access, Notifications, Intelligence, Data and privacy, Plan and billing, Advanced collapsed): `under` merges pages into one entry with a tab bar here too, `/settings` (`SettingsHomePage`) is the landing page with "Find a setting" and one card per entry, and the till pages plus Selling settings (`TILL_PAGES` in `sdk/kindProfile.ts`) are left out for kinds of business with no counter. Rarely changed fields sit behind "More options" (`<details>`).

**Intelligence and Waiting for you.** The `command` area is titled **Intelligence** (Today, Things to look at, Daily summary, Suggestions); **Waiting for you** (`waiting` area, one sidebar link directly under Home with a count from `setNavBadge`) holds Approvals and Exceptions, which are not Intelligence. The Intelligence screens follow the **vocabulary rule**: no technical term in the Simple layer (finding, baseline, severity, check code, fingerprint, coverage, entity, connector, evidence, parameter ...): use the words in `docs/intelligence.md` ("Plain words"); technical names only in the glossary popover and behind "Show technical details" / "Show technical names" (Expert layer, `useTechnical`). Swahili strings for these screens are written carefully but still need a native speaker's review.

A module places a page by giving its **menu entry** an `area` (`AREA_IDS` in `sdk/module.ts`):

| Entry field | Meaning |
| --- | --- |
| `area` | the section that lists it; an entry without one is a sidebar item of its own (third-party modules) |
| `order` | position in the section (lower first) |
| `tab` | translation key of the name shown in the sidebar or Settings list when it differs from `label` (which search and the tab bar use): the name of a family ("Quotes and orders") or a shorter name |
| `under: "<to>"` | the page shares the sidebar entry whose page is `<to>`: the entry covers both and each page shows a small tab bar (keep to 3-4 tabs and merge only same-kind lists, never unrelated pages); if the entry is not available to the person the page gets an entry of its own |
| `setup: true` | rarely used (locations, payment accounts): last in the section |
| `primary: true` | a filled button at the top of the section (Point of sale in Sell) |
| `keywords` | translation key of extra search words (Add-ons matches apps, plugins, modules, features) |
| `hidden: true` | only found by search (My account, opened from the account menu) |
| `when` | the entry is listed only while this navigation flag is on (`setNavFlag` in `sdk/navFlags.ts`); a module switches flags from a component it contributes to the `shell.background` slot, which the layout keeps mounted (Suggestions appears when the action mode is Prepare or Act for me, or any suggestion exists) |
| `section` | Settings only: orders the entries (business, access, channels, intelligence, data, platform) and `advanced` puts the page in the collapsed Advanced group of the list |

Detail and form pages need nothing: a page belongs to the entry whose path is its longest prefix (`/orders/:id` keeps Purchase orders highlighted). A
page whose path does not start with its entry's (`/payslips/:id` under `/payroll`) names it with `tab: "/payroll"` on its route. Rows follow the person's
permissions and the enabled units; an area with nothing allowed disappears. cmd-K finds every page, with its section beside the name.

## Document families and one-menu-entry modules

A family of related screens is a group of pages in one sidebar section (the sales documents in Sell), merged with `under` only when they are the same kind of list. Details open as a page
(documents with lines) or as a drawer opened by `?open=<id>` on the list (receipts, refunds, offline rejections), so a
row link works with the back button and can be shared. A module may put a feature area in its own folder with an `index.ts`
that exports `routes`, `menu` and `translations` (placed under a sub-key of the module's namespace, as the till does with
`terminal`); keep it flat, because ESLint forbids `../../` imports. Line editors reuse the product `Combobox`, show price and
discount only to people holding `price.override`, and show the server's figures after saving (the estimate is labelled).
Another module's component is shared through its `public.ts` (`ReceivePayment` from Customers).

## Help link (`VITE_HELP_URL`)

Set `VITE_HELP_URL` to the website's Help centre (for example `https://example.com/help`) when building the web app and the account menu shows **Help**
(opens in a new tab) and the Home checklist shows a **How-to guide** link beside each step that has one (`src/shell/help.ts`, step id to guide path).
Unset, neither is shown. The guides are on the marketing site (`docs/marketing-site.md`).

## Sign-up wizard (`src/shell/register/`)

`Register.tsx` orchestrates five steps (`Step*.tsx`), each given a `FormApi` (answers, set, blur, translated error). Pure rules are in
`validators.ts` (email typo suggestions, phone length, password rules and strength, tax pattern) and `state.ts` (step gating,
server-field to step mapping, the sessionStorage draft that never holds the password); layout in `RegisterLayout.tsx` and `SidePanel.tsx`.
`VerifyRegistration.tsx` shows the honest wait (`Creating.tsx`) and retries a 503 once. New strings live under `signup.*` (English and Swahili).

## Super Admin shell (`frontend/src/operator`)

Sidebar entries live in `operator/nav.ts` (id, address, permission, optional feature, `match`); words under `nav.i.<id>` in `i18n/*.shell.json`.
Shell pieces are in `operator/shell/` (sidebar, top bar, search palette, alerts bell, risk banners, breadcrumbs); charts are inline SVG in
`operator/components/charts.tsx` with pure helpers in `helpers/chart.ts`. Each dashboard block reads its own data so one failure never blanks the page.
