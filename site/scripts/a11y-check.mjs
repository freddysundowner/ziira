// npm run a11y: axe-core (WCAG 2.0/2.1 A and AA) on key pages of the built site, in light and dark mode and at phone width.
// Uses Playwright and @axe-core/playwright from ../e2e/node_modules (run `make e2e-setup` once). Needs `npm run build` first.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./lib/static-server.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../e2e/package.json"));
const { chromium } = require("playwright");
const AxeBuilder = require("@axe-core/playwright").default;

const PAGES = (process.env.A11Y_PAGES ?? "/,/product/,/product/pos-and-till/,/intelligence/how-it-works/,/intelligence/complete-guide/,/intelligence/on-your-existing-system/,/intelligence/on-your-existing-system/odoo/,/solutions/retail/,/integrations/,/integrations/whatsapp/,/security-and-privacy/,/get-started/,/pricing/,/guides/,/guides/cashier-voids-discount-abuse/,/glossary/,/help/,/help/a-z/,/help/sell/,/help/get-started/create-your-account/,/help/sell/open-a-till-and-make-a-sale/,/help/intelligence/connect-your-system/,/privacy-policy/,/404.html").split(",");
const MODES = [
  { name: "desktop light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desktop dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
  { name: "phone light", viewport: { width: 375, height: 812 }, colorScheme: "light" },
];

const srv = await serve(path.resolve(process.env.SITE_DIST ?? path.join(here, "../dist")));
const browser = await chromium.launch();
let violations = 0;
for (const mode of MODES) {
  const ctx = await browser.newContext({ viewport: mode.viewport, colorScheme: mode.colorScheme });
  for (const p of PAGES) {
    const page = await ctx.newPage();
    await page.goto(`http://127.0.0.1:${srv.port}${p}`, { waitUntil: "networkidle" });
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    // horizontal scroll check (a layout bug at phone width)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    if (overflow) { violations++; console.error(`[${mode.name}] ${p}: page scrolls horizontally`); }
    for (const v of res.violations) {
      violations++;
      console.error(`[${mode.name}] ${p}: ${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    }
    await page.close();
  }
  await ctx.close();
}
await browser.close();
srv.close();
console.log(`a11y: ${PAGES.length} pages x ${MODES.length} modes, ${violations} violation(s)`);
process.exit(violations ? 1 : 0);
