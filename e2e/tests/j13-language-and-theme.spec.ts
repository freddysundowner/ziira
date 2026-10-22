import type { Page } from "@playwright/test";

import { checkAccessibility, expect, shared, signIn, test } from "../lib/test";

// J13: Swahili and dark mode. In Swahili the menu and the page headings are translated and no screen shows a raw
// translation key, "undefined" or "NaN"; in dark mode the screens pass the contrast scan and nothing keeps a light
// background of its own; both choices survive a reload.

/** Text on the page that should never reach a person: a translation key that was not found, or a value that was never set. */
const BROKEN = [
  /\b(kernel|shell|pos|products|inventory|finance|purchasing|crm|payments|people|intel|command|imports|messaging):[A-Za-z_.]+/,   // namespace:key
  /(^|\s)[a-z]+(\.[a-zA-Z_]+){1,3}(\s|$)/,                                                                                         // key.with.dots
  /\bundefined\b|\[object Object\]|\bNaN\b|\{\{\w+\}\}/,
];
async function brokenText(page: Page): Promise<string[]> {
  const text = await page.locator("body").innerText();
  const found: string[] = [];
  for (const line of text.split("\n")) {
    const words = line.trim();
    // e-mail addresses, file names and the business's own names may contain dots; they are data, not keys
    if (!words || /@|\.(test|csv|pdf|png|com)\b|^\d/.test(words)) continue;
    if (BROKEN.some((r) => r.test(words))) found.push(words);
  }
  return found;
}

/** The page's heading once it has loaded (the till terminal and the home page have none of their own). */
async function headingOf(page: Page): Promise<string> {
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => undefined);      // a screen that polls never goes quiet
  const h1 = page.locator("h1").first();
  return (await h1.count()) ? (await h1.innerText()).trim() : "";
}

/** A menu entry's words without the small count badge ("Waiting for you 4") that comes and goes with the business's open items. */
const label = (text: string) => text.replace(/\s*\n?\s*\d+$/, "").trim();
const menuLinks = (page: Page) => page.getByRole("navigation", { name: "Main" }).getByRole("link");
/** The section headings and the single links (Home, Settings): what is translated at the top level. */
const menuEntries = (page: Page) => page.getByRole("navigation", { name: "Main" }).locator("h2, :scope > a");
async function chooseFromAccountMenu(page: Page, item: string) {
  await page.getByRole("button", { name: /^Account$|^Akaunti$/ }).click();
  await page.getByRole("menuitem", { name: item }).click();
}

/** The sidebar keeps most sections folded (the person's choice is remembered); open them all so every link is listed. */
async function openAllSections(page: Page) {
  const folded = page.getByRole("navigation", { name: "Main" }).locator('h2 button[aria-expanded="false"]');
  while (await folded.count()) await folded.first().click();
}

test("J13 language and theme", async ({ page }) => {
  test.setTimeout(480_000);      // every page of the menu is visited in English, Swahili and dark mode
  const s = shared();
  await signIn(page, s.owner);
  await openAllSections(page);

  // --- the English menu and headings, to compare with
  const sections = await menuEntries(page).count();
  expect(sections).toBeGreaterThanOrEqual(5);
  const englishLabels = (await menuEntries(page).allInnerTexts()).map(label);
  // the pages: every sidebar link (every section opened above), plus the tab bars and Settings' own list found by opening each area's first page
  const hrefs = new Set<string>(await menuLinks(page).evaluateAll((els) => els.map((a) => a.getAttribute("href")!)));
  for (const h of [...hrefs]) {
    await page.goto(h);
    for (const t of await page.locator("main nav a[href]").evaluateAll((els) => els.map((a) => a.getAttribute("href")!))) hrefs.add(t);
  }
  const pages = [...hrefs].slice(0, 60).map((href) => ({ href }));
  expect(pages.length).toBeGreaterThan(20);
  const english = new Map<string, string>();
  for (const l of pages) {
    await page.goto(l.href);
    english.set(l.href, await headingOf(page));
  }

  // --- Swahili
  await chooseFromAccountMenu(page, "Kiswahili");
  await expect(page.locator("html")).toHaveAttribute("lang", "sw");
  const swahiliLabels = (await menuEntries(page).allInnerTexts()).map(label);
  const unchanged = swahiliLabels.filter((label, i) => label === englishLabels[i]);
  // a few names are the same in both languages (a word borrowed from English, a product name); most of the menu is not
  expect(unchanged.length, `menu entries still in English: ${unchanged.join(", ")}`).toBeLessThan(englishLabels.length / 4);

  const problems: string[] = [];
  const sameHeading: string[] = [];
  for (const l of pages) {
    await page.goto(l.href);
    const heading = await headingOf(page);
    if (heading && heading === english.get(l.href)) sameHeading.push(`${l.href} "${heading}"`);
    for (const bad of await brokenText(page)) problems.push(`${l.href}: ${bad}`);
  }
  expect(problems, "text that looks like a missing translation or an unset value").toEqual([]);
  expect(sameHeading.length, `headings still in English: ${sameHeading.join("; ")}`).toBeLessThan(pages.length / 4);
  await checkAccessibility(page, "a Swahili page");

  // --- it is still Swahili after a reload
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "sw");
  expect((await menuEntries(page).allInnerTexts()).map(label)).toEqual(swahiliLabels);

  // --- back to English, then dark mode
  await chooseFromAccountMenu(page, "English");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await chooseFromAccountMenu(page, "Dark");
  await expect(page.locator("html")).toHaveClass(/dark/);

  const lightBackgrounds: string[] = [];
  for (const l of pages.slice(0, 30)) {
    await page.goto(l.href);
    await headingOf(page);
    await expect(page.locator("html")).toHaveClass(/dark/);
    await checkAccessibility(page, `dark ${l.href}`);
    const light = await page.evaluate(() => {
      const luminance = (c: string) => {
        const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/);
        if (!m || (m[4] !== undefined && Number(m[4]) < 0.9)) return 0;      // transparent: shows what is behind it
        const [r, g, b] = [m[1], m[2], m[3]].map((v) => Number(v) / 255);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const out: string[] = [];
      for (const el of Array.from(document.body.querySelectorAll("*"))) {
        const box = el.getBoundingClientRect();
        if (box.width < 4 || box.height < 4 || box.width <= 24 ||   // (a toggle's round white knob is meant to be white)
             el.closest(".print-root, [data-keeps-light]") || el.tagName === "IMG" || el.tagName === "svg") continue;
        if (luminance(getComputedStyle(el).backgroundColor) > 0.75) out.push(`${el.tagName.toLowerCase()}.${String(el.getAttribute("class") ?? "").slice(0, 60)}`);
      }
      return out.slice(0, 5);
    });
    for (const x of light) lightBackgrounds.push(`${l.href}: ${x}`);
  }
  expect(lightBackgrounds, "elements with a light background in dark mode").toEqual([]);

  // --- dark survives a reload
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
