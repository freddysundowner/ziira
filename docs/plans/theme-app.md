# Theme: web app (status)

Scope (owner, final): COLOUR theme and gradient primary buttons only. Layout, sizing and typography of the signed-in app are as before the theme work.

## Kept
- Palette tokens, light and dark (navy, blue, cyan, green, ink, muted, line, backgrounds, status colours; `src/index.css`, `tailwind.config.js`), contrast-checked text colours.
- `btn-gradient` on primary buttons (navy text: white fails AA on cyan/blue), the Z tile and sign-up header tile filled with the gradient.
- Inter self-hosted (`src/fonts`), SVG logo/favicon (`public/brand`, `sdk/ui/brand.tsx`).
- Auth screens in the login mockup's split layout (`shell/AuthShell.tsx`): sign-in, forgot/reset password, second factor, MFA setup.
- Token fixes in modules (filled buttons, status ink colours, `text-brand` links).

## Reverted
Sidebar width, brand block, business block, section headings, row spacing and accent bar, top bar height and contents, Home header and shortcut cards, radii, control heights, badge shape, table head, modal/drawer style, page header sizes, Super Admin shell structure.
