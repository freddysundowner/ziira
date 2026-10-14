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
