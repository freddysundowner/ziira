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
src/shell/      sign-in, layout (menu from active modules), home page
src/sdk/        the only thing modules import: api client, session, <Slot>, UI parts, i18n
src/modules/<unit>/   module.ts (manifest), pages/, slots/, i18n/en.json + sw.json, public.ts
src/api/schema.d.ts   generated from the backend; never edit
```

## Adding a module

1. Create `src/modules/<unit>/module.ts` with `defineModule({ unit, routes, menu, slots, translations })`
   (`unit` = backend unit name; the kernel's own screens use `"kernel"`). Every route needs a permission.
2. List it in `src/modules/index.ts`.
3. Provide English and Swahili strings with the same keys (a test checks it).

## Slots (screen sockets, the frontend twin of extension points)

A page offers `<Slot name="products.product.tabs" props={{ productId }} />`; other modules contribute
under `slots` in their `module.ts`. The slot name is exported from the owner's `public.ts`.
Contributions appear only when their module is active and the user has the permission.

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
5. Menu entries set `group` (`sell | stock | buy | money | people | admin`) and `icon` (see `src/sdk/icons.tsx`).
6. English and Swahili strings with the same keys (a test checks it). No text in components.
7. Works at phone width (tables hide low-priority columns with `hideBelow`), keyboard friendly, labelled controls, 44px-ish targets.
8. No country in code: currency, tax names, phone codes come from the company and the API.
