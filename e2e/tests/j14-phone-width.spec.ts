import type { Locator, Page } from "@playwright/test";

import { closeOpenTills, code, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl } from "../lib/ui";

// J14: at the width of a phone (390 x 844) the menu opens as a drawer, the main lists need no sideways scrolling of the
// page, a form in a drawer fits and can be saved, and the till terminal can ring up and take payment for a sale.
test.use({ viewport: { width: 390, height: 844 } });

async function expectNoSidewaysScroll(page: Page, where: string) {
  const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
  expect(scroll, `${where}: the page is ${scroll}px wide in a ${width}px window`).toBeLessThanOrEqual(width + 1);
}

/** The element is fully inside the 390px screen (once any slide-in animation has settled). */
async function expectOnScreen(locator: Locator, where: string) {
  await expect(locator).toBeVisible();
  await expect.poll(async () => {
    const box = (await locator.boundingBox())!;
    return box.x >= -1 && box.x + box.width <= 391 ? "inside" : `x ${Math.round(box.x)}, right edge ${Math.round(box.x + box.width)}`;
  }, { message: `${where} is inside the screen` }).toBe("inside");
}

test("J14 the web app at phone width", async ({ page }) => {
  const s = shared();
  const tag = code(5).toLowerCase();
  await signIn(page, s.owner);

  // --- the menu is a drawer
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav).toBeVisible();
  await expectNoSidewaysScroll(page, "menu open");
  await checkAccessibility(page, "phone menu");
  await nav.getByRole("link", { name: "Products", exact: true }).click();
  await expect(page).toHaveURL(/\/products$/);
  await expect(nav).toBeHidden();                       // choosing a page closes the drawer

  // --- the main lists: the page itself never scrolls sideways, and their first column is on screen
  for (const path of ["/products", "/stock", "/pos/sales", "/customers", "/suppliers", "/bills", "/finance/journal", "/employees", "/admin/users", "/findings", "/command", "/admin/organisation", "/"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => undefined);
    await expect(page.getByRole("main")).toBeVisible();
    await expectNoSidewaysScroll(page, path);
    const firstRow = page.getByRole("row").nth(1);
    if (await firstRow.count()) await expectOnScreen(firstRow.getByRole("cell").first(), `${path} first cell`);
  }
  await page.goto("/admin/users");
  await checkAccessibility(page, "phone users list");

  // --- a form in a drawer fits the screen and can be saved
  const person = { name: `Pia ${tag}`, email: `pia${tag}@phone.test`, password: "phone-pass-123" };
  await page.getByRole("button", { name: "New user" }).first().click();
  const form = drawer(page);
  await expectOnScreen(form, "new user drawer");
  await form.getByLabel(lbl("Full name")).fill(person.name);
  await form.getByLabel(lbl("Email")).fill(person.email);
  await form.getByLabel(lbl("Password")).fill(person.password);
  await expectOnScreen(form.getByRole("button", { name: "Save", exact: true }), "save button");
  await checkAccessibility(page, "phone form");
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(person.name).first()).toBeVisible();
  await expectNoSidewaysScroll(page, "users after saving");

  // --- the till terminal: a cash sale from search to receipt
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Bulb", price: 8, cost: 3, qty: 30 }]);
  const bulb = cat.products[0];
  // the terminal opens the first till device of the branch, which earlier journeys made: stock the bulb in every store
  for (const loc of (await api.get<any[]>("/inventory/locations")).filter((l) => l.id !== cat.locationId && l.kind === "store")) {
    await api.post("/inventory/opening-stock", { company_id: cat.companyId, location_id: loc.id, lines: [{ product_id: bulb.id, quantity: "30", unit_cost: "3" }] });
  }
  await page.goto("/pos/terminal");
  await expectNoSidewaysScroll(page, "terminal open till");
  await page.getByLabel(lbl("Opening float")).fill("50");
  await expectOnScreen(page.getByRole("button", { name: "Open till and start selling" }), "open till button");
  await page.getByRole("button", { name: "Open till and start selling" }).click();
  const search = page.getByLabel("Search or scan: name, SKU or barcode");
  await expect(search).toBeVisible();
  await search.fill(bulb.sku);
  await search.press("Enter");
  const views = page.getByRole("navigation", { name: "Switch view" });
  await expectOnScreen(views, "terminal view switch");
  await views.getByRole("button", { name: /^Sale/ }).click();
  await expect(page.getByText("8.00").locator("visible=true").first()).toBeVisible();      // the cart, not the product list behind it
  await expectNoSidewaysScroll(page, "terminal cart");
  await expectOnScreen(page.getByRole("button", { name: /^Pay/ }), "pay button");
  await checkAccessibility(page, "phone terminal");
  await page.getByRole("button", { name: /^Pay/ }).click();
  await expectOnScreen(page.getByRole("button", { name: "Complete sale" }), "complete sale button");
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  await expectNoSidewaysScroll(page, "sale complete");
  await expectOnScreen(page.getByRole("button", { name: "New sale" }), "new sale button");
  await page.getByRole("button", { name: "New sale" }).click();
  await closeOpenTills(api);                           // leave nothing open for the other journeys
});
