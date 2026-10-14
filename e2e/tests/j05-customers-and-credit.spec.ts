import { closeOpenTills, code, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";

// J5: a customer with a credit limit , a credit sale at the till that the limit
// refuses and then allows, a payment received, and the customer on the ageing list.
test("J5 customers and credit", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Drill", price: 50, cost: 30, qty: 20 }]);
  const drill = cat.products[0];
  const name = `Wanjiru ${code(4)}`;

  await signIn(page, s.owner);
  await page.goto("/customers");
  await page.getByRole("button", { name: "New customer" }).first().click();
  await drawer(page).getByLabel(lbl("Name")).fill(name);
  await drawer(page).getByLabel(lbl("Payment terms")).fill("30");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();      // lands on the new customer
  await checkAccessibility(page, "customer");

  // --- a credit limit of 100
  await page.getByRole("tab", { name: "Credit" }).click();
  await page.getByRole("button", { name: "Change credit" }).click();
  await drawer(page).getByLabel(lbl("Credit limit")).fill("100");
  await drawer(page).getByLabel(lbl("Reason")).fill("Trusted for years");
  await drawer(page).getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.getByText("Credit updated.")).toBeVisible();       // no approval rule is set up in a new business: it applies at once

  await page.reload();
  await page.getByRole("tab", { name: "Credit" }).click();
  await expect(page.getByText("100.00").first()).toBeVisible();

  // --- at the till: 3 drills = 150 is over the limit, 2 = 100 is fine
  await page.goto("/pos/terminal");
  await page.getByLabel(lbl("Till (device)")).selectOption(cat.deviceId);
  await page.getByLabel(lbl("Opening float")).fill("0");
  await page.getByRole("button", { name: "Open till and start selling" }).click();
  const search = page.getByLabel("Search or scan: name, SKU or barcode");
  await search.fill(drill.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: "One more" }).click();
  await page.getByRole("button", { name: "One more" }).click();
  await pick(page, page.getByRole("combobox", { name: /Walk-in customer/ }), name);
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Remove payment" }).click();
  await page.getByRole("button", { name: "On account" }).click();
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByRole("alert").or(page.getByText(/credit limit/i)).first()).toBeVisible();
  await page.getByRole("button", { name: "Back to sale" }).click();
  await page.getByRole("button", { name: "One less" }).click();
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Remove payment" }).click();
  await page.getByRole("button", { name: "On account" }).click();
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();

  // --- the customer owes 100; they pay 40
  await page.goto("/customers");
  await page.getByRole("cell", { name }).click();
  await page.getByRole("button", { name: "Receive payment" }).click();
  await drawer(page).getByLabel(lbl("Amount")).fill("40");
  await drawer(page).getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText(/recorded|received/i).first()).toBeVisible();
  await page.getByRole("tab", { name: "Account" }).click();
  await expect(page.getByText("60.00").first()).toBeVisible();

  // --- ageing
  await page.goto("/receivables");
  await expect(page.getByText(name)).toBeVisible();
  await checkAccessibility(page, "receivables");
});
