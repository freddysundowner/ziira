# Theme: web app (status)

Goal: the owner's three mockups (`ziira_dashboard_ui_redesign.html`, `ziira_login_page_final.html`, the website mockup) are THE theme of the signed-in
app, the auth screens and the Super Admin console. Done through tokens and the shared kit so modules need no edits (docs/frontend.md "Theme").

## Done
- Tokens (light and dark), Tailwind names (`navy`, `cyan`, `mint`, `indigo`, `bad-ink`, `ok-ink`), 9px `lg` radius, soft shadows, focus ring, Inter self-hosted (`src/fonts`).
- Kit: Button (gradient primary, secondary, ghost, danger), Input/Select/Textarea (40px, 10px radius), Field labels, Card, PageHeader, Stat, Tabs, Badge/StatusBadge,
  tables (uppercase small heads), Modal/Drawer (navy scrim), toasts, Alert, Empty/Error states.
- Shell: sidebar (brand, business block, uppercase section labels, pale-teal active, gradient accent, count pills, collapsed icon mode, mobile drawer), top bar (76px, search, account),
  Home (date eyebrow, greeting, tinted shortcut chips, widgets), AuthShell (split layout with electric art) for sign-in, forgot, reset, second factor, MFA setup;
  sign-up wizard header and progress bar; Super Admin sidebar, top bar and sign-in.
- Raw colours replaced by tokens in a few modules (`bg-brand-strong` fills, white-on-status text, `text-slate-500`).

## Not done / open
- Home has no date-range selector, Create button, health ring or daily-check strip of its own: the mockup's data is not in our widgets, and nothing was invented.
  The Intelligence widgets are the nearest equivalent.
- Modules' own charts (and the operator charts) keep their colours; only `--brand` changed. A shared chart palette is not defined yet.
- Sign-up wizard is not the split layout (it is a five-step wizard with a progress rail); public booking/approval pages inherit tokens but have no brand panel.
- `public/brand/ziira-logo-on-dark.png` is unused now (SVG wordmark replaces it).
- Contrast spot-checks were computed, not run through an automated audit (see the report in the session notes): muted text 5.0:1 on page, brand-strong 5.5:1 on pale teal.
