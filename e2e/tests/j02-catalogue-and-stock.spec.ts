import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";
import { unique } from "../lib/api";

// J2: units, tax code and price list, products with prices, opening stock, the stock page, a stock adjustment with a reason.
test("J2 catalogue and stock", async ({ page }) => {
  const s = shared();
  const tag = Array.from({ length: 4 }, () => String.fromCharCode(65 + Math.floor(Math.random() * 26))).join("");
  await signIn(page, s.owner);

  // --- setup: unit, tax code, price list
  await page.goto("/products-setup");
  await page.getByRole("button", { name: "New unit" }).click();
  await drawer(page).getByLabel(lbl("Code")).fill(`PC${tag}`);
  await drawer(page).getByLabel(lbl("Name")).fill("Piece");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: `PC${tag}` })).toBeVisible();

  await page.getByRole("tab", { name: "Tax codes" }).click();
  await page.getByRole("button", { name: "New tax code" }).click();
  await drawer(page).getByLabel(lbl("Code")).fill(`S${tag}`);
  await drawer(page).getByLabel(lbl("Rate (%)")).fill("20");
  await drawer(page).getByLabel(lbl("Name")).fill("Standard 20");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "20%" })).toBeVisible();

  await page.getByRole("tab", { name: "Price lists" }).click();
  await page.getByRole("button", { name: "New price list" }).click();
  await drawer(page).getByLabel(lbl("Name")).fill(`Retail ${tag}`);
  await drawer(page).getByLabel(lbl("Use as the default price list")).check();
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: `Retail ${tag}` })).toBeVisible();
  await expect(page.getByText("Default", { exact: true })).toBeVisible();
  await checkAccessibility(page, "catalogue setup");

  // --- products
  await page.goto("/products");
  for (const [name, sku] of [[`Hammer ${tag}`, `HAM${tag}`], [`Nails ${tag}`, `NAI${tag}`]]) {
    await page.getByRole("button", { name: "New product" }).first().click();
    await drawer(page).getByLabel(lbl("Name")).fill(name);
    await drawer(page).getByLabel(lbl("SKU")).fill(sku);
    await drawer(page).getByRole("button", { name: "Save product" }).click();
    await expect(page.getByText(`${name} added.`)).toBeVisible();
    await expect(page.getByRole("cell", { name })).toBeVisible();
  }
  await page.getByPlaceholder("Search by name, SKU or barcode").fill(`Hammer ${tag}`);
  await expect(page.getByRole("cell", { name: `Nails ${tag}` })).toBeHidden();
  await checkAccessibility(page, "products");

  // --- a price on the hammer
  await page.getByRole("cell", { name: `Hammer ${tag}` }).click();
  await page.getByRole("tab", { name: "Prices" }).click();
  await page.getByLabel(lbl("Price")).fill("12.50");
  await page.getByRole("button", { name: "Save price" }).click();
  await expect(page.getByText("Price saved.")).toBeVisible();
  await expect(page.getByText("12.50").first()).toBeVisible();

  // --- opening stock: a location first
  await page.goto("/stock/locations");
  await page.getByRole("button", { name: "New location" }).first().click();
  await drawer(page).getByLabel(lbl("Code")).fill("MAIN");
  await drawer(page).getByLabel(lbl("Name")).fill("Main store");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Main store" })).toBeVisible();

  await page.goto("/stock/opening");
  await page.getByLabel(lbl("Location")).selectOption({ label: "MAIN · Main store" });
  await pick(page, page.getByRole("combobox", { name: /Choose a product/ }), `Hammer ${tag}`);
  await page.getByLabel(lbl("Quantity 1")).fill("40");
  await page.getByLabel(lbl("Unit cost")).fill("7");
  await page.getByRole("button", { name: "Post opening stock" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Post opening stock" }).click();
  await expect(page.getByText(/posted/i).first()).toBeVisible();

  await page.goto("/stock");
  await expect(page.getByRole("row", { name: new RegExp(`Hammer ${tag}.*40`) })).toBeVisible();
  await checkAccessibility(page, "stock");

  // --- adjustment with a reason: remove 3 broken hammers
  await page.goto("/stock/adjustments");
  await page.getByRole("button", { name: "New adjustment" }).first().click();
  await drawer(page).getByLabel(lbl("Location")).selectOption({ label: "MAIN · Main store" });
  await pick(page, drawer(page).getByRole("combobox", { name: /Choose a product/ }), `Hammer ${tag}`);
  await drawer(page).getByLabel(lbl("Direction")).selectOption("out");
  await drawer(page).getByLabel(lbl("Quantity 1")).fill("3");
  await drawer(page).getByRole("button", { name: "Save draft" }).click();
  await page.waitForURL(/\/stock\/adjustments\/[0-9a-f-]+/);
  await page.getByRole("button", { name: "Submit" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit" }).click();
  await page.goto("/stock");
  await expect(page.getByRole("row", { name: new RegExp(`Hammer ${tag}.*37`) })).toBeVisible();

  // the books and the API agree with what the screen shows
  const api = await signedInApi(s.owner);
  const balances = await api.get<{ quantity: string }[]>("/inventory/balances");
  expect(balances.map((b) => Number(b.quantity))).toContain(37);
});
