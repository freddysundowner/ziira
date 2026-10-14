import { seedCatalogue } from "../lib/seed";
import { code } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";

// J4: a supplier, a purchase order, goods received into stock, the supplier's bill entered and matched, then paid.
test("J4 buy: supplier, order, receive, bill, pay", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  const cat = await seedCatalogue(api, [{ name: "Pipe", price: 30, cost: 20, qty: 0 }]);
  const pipe = cat.products[0];
  const supplier = `Acme ${code(4)}`;

  await signIn(page, s.owner);
  await page.goto("/suppliers");
  await page.getByRole("button", { name: "New supplier" }).first().click();
  await drawer(page).getByLabel(lbl("Code")).fill(code(5));
  await drawer(page).getByLabel(lbl("Name")).fill(supplier);
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: supplier })).toBeVisible();
  await checkAccessibility(page, "suppliers");

  // --- the order: 10 pipes at 20.00 = 200.00
  await page.goto("/orders/new");
  await pick(page, page.getByRole("combobox", { name: /Supplier/ }), supplier);
  await pick(page, page.getByRole("combobox", { name: /Product/ }).first(), pipe.name);
  await page.getByLabel(lbl("Quantity")).fill("10");
  await page.getByLabel(lbl("Unit cost (before tax)")).fill("20");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.waitForURL(/\/orders\/[0-9a-f-]+$/);
  await expect(page.getByText("200.00").first()).toBeVisible();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  // a business with no approval rule approves at once; otherwise a second person decides
  const approve = page.getByRole("button", { name: "Approve", exact: true });
  if (await approve.isVisible().catch(() => false)) await approve.click();
  await expect(page.getByRole("button", { name: "Mark as sent" })).toBeVisible();
  await page.getByRole("button", { name: "Mark as sent" }).click();

  // --- receive the goods
  await page.getByRole("link", { name: "Receive goods" }).click();
  await page.getByLabel(lbl("Receive into")).selectOption(cat.locationId);
  await page.getByRole("button", { name: "Confirm and add to stock" }).click();
  await page.waitForURL(/\/receipts\/[0-9a-f-]+$/);
  const stock = await api.get<{ product_id: string; quantity: string }[]>("/inventory/balances");
  expect(Number(stock.find((b) => b.product_id === pipe.id)?.quantity)).toBe(10);

  // --- the bill, matched to the receipt
  await page.goto("/bills/new");
  await pick(page, page.getByRole("combobox", { name: /Supplier/ }), supplier);
  await page.getByLabel(lbl("Supplier's invoice no.")).fill(`INV-${code(4)}`);
  await page.getByRole("button", { name: "Goods from a receipt" }).click();
  await page.getByRole("dialog").getByRole("checkbox").first().check();
  await page.getByRole("dialog").getByRole("button", { name: /^Add/ }).click();
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.waitForURL(/\/bills\/[0-9a-f-]+$/);
  await page.getByRole("button", { name: "Submit and check" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.getByText("Matched").first()).toBeVisible();
  await expect(page.getByText("200.00").first()).toBeVisible();

  // --- pay the bill
  const bank = await api.post("/payments/accounts", { company_id: cat.companyId, kind: "bank", name: `Operating ${code(3)}`, provider: "fake", environment: "sandbox" });
  await page.goto("/pay-suppliers");
  await pick(page, page.getByRole("combobox", { name: /Supplier/ }), supplier);
  await page.getByLabel(lbl("Pay from")).selectOption(bank.id);
  await page.getByLabel(lbl("Spread one payment")).fill("200");
  await page.getByRole("button", { name: "Spread" }).click();
  await page.getByRole("button", { name: "Pay $200.00" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Pay $200.00" }).click();
  await expect(page.getByText("1 payment(s) recorded.")).toBeVisible();
  await expect(page.getByText("Nothing to pay.")).toBeVisible();

  // --- payables: nothing is owed to this supplier any more
  const payables = await api.get<any[]>("/purchasing/payables");
  expect(JSON.stringify(payables)).not.toContain(supplier);
  await page.goto("/payables");
  await checkAccessibility(page, "payables");
});
