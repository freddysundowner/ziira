import { code, customerWithCredit, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, pick } from "../lib/ui";

// J17: a quotation is made, sent and accepted into a sales order; the order is confirmed and delivered into an invoice;
// the customer pays the invoice. Every step is done in the browser, and the figures are checked against hand sums.
test("J17 quotation to order to invoice to payment", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  const cat = await seedCatalogue(api, [{ name: "Anvil", price: 50, cost: 30, qty: 20 }]);
  const anvil = cat.products[0];
  const customer = await customerWithCredit(api, cat.companyId, `Kamau Traders ${code(4)}`);

  await signIn(page, s.owner);

  // --- the menu has one entry for all the sales documents
  await expect(page.getByRole("link", { name: "Sales documents" })).toBeVisible();

  // --- a quotation for 3 anvils at the list price: 3 x 50 = 150
  await page.goto("/pos/quotations");
  await expect(page.getByRole("tab", { name: "Quotations" })).toHaveAttribute("aria-selected", "true");
  await checkAccessibility(page, "quotations list");
  await page.getByRole("link", { name: "New quotation" }).click();
  await pick(page, page.getByRole("combobox", { name: /^Customer/ }), customer.name);
  await pick(page, page.getByRole("combobox", { name: /^Product 1/ }), anvil.name);
  await page.getByLabel("Quantity").fill("3");
  await page.getByLabel("Goods leave from").selectOption(cat.locationId);       // an order is delivered from a named store
  await page.getByRole("button", { name: "Save quotation" }).click();
  await expect(page.getByText(/saved/).first()).toBeVisible();
  const quote = (await page.getByRole("heading", { level: 1 }).innerText()).trim();
  expect(quote).toMatch(/\S+/);
  await expect(page.getByText("Draft").first()).toBeVisible();
  await expect(page.getByText("150.00").first()).toBeVisible();     // total, from the server
  await checkAccessibility(page, "quotation");

  // --- send, then accept: the order appears
  await page.getByRole("button", { name: "Mark as sent" }).click();
  await drawer(page).getByRole("button", { name: "Mark as sent" }).click();
  await expect(page.getByText("Sent", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await drawer(page).getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText(/Accepted\. Sales order/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Sales orders" }).or(page.getByRole("tab", { name: "Sales orders" })).first()).toBeAttached();
  await expect(page.getByText("Made from")).toBeVisible();
  const order = (await page.getByRole("heading", { level: 1 }).innerText()).trim();
  expect(order).not.toBe(quote);

  // --- confirm the order, then deliver two now and the rest later
  await page.getByRole("button", { name: "Confirm order" }).click();
  await drawer(page).getByRole("button", { name: "Confirm order" }).click();
  await expect(page.getByText("Confirmed", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Deliver", exact: true }).click();
  await expect(drawer(page).getByLabel(/Goods leave from/)).toHaveValue(cat.locationId);   // carried from the quotation
  await drawer(page).getByLabel("Deliver now").fill("2");
  await drawer(page).getByRole("button", { name: "Deliver and invoice" }).click();

  // --- the invoice for 2 x 50 = 100 is open
  await expect(page.getByText(/Invoice .* was made/)).toBeVisible();
  await expect(page.getByText("Unpaid", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("100.00").first()).toBeVisible();
  const invoice = (await page.getByRole("heading", { level: 1 }).innerText()).trim();
  await checkAccessibility(page, "invoice");

  // --- the customer pays it
  await page.getByRole("button", { name: "Receive payment" }).click();
  await expect(drawer(page).getByLabel("Amount")).toHaveValue("100.00");
  await drawer(page).getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Receive payment" })).toBeHidden();

  // --- the order shows its delivery and one anvil is still to deliver; the payment is in the payments list
  await page.goto("/pos/orders");
  await page.getByRole("cell", { name: order }).click();
  await expect(page.getByRole("cell", { name: invoice })).toBeVisible();
  await page.getByRole("button", { name: "Deliver", exact: true }).click();
  await expect(drawer(page).getByLabel("Deliver now")).toHaveValue("1");
  await drawer(page).getByRole("button", { name: "Cancel" }).click();

  await page.goto("/pos/receipts");
  await expect(page.getByRole("tab", { name: "Payments received" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("cell", { name: customer.name })).toBeVisible();
  await page.getByRole("cell", { name: customer.name }).first().click();
  await expect(drawer(page).getByText("100.00").first()).toBeVisible();
  await expect(drawer(page).getByRole("link", { name: invoice })).toBeVisible();

  // --- the manager's inbox of refused offline sales is reachable and, with nothing refused, says so
  await page.goto("/pos/sync/rejections");
  await expect(page.getByRole("link", { name: "Offline rejections" })).toBeVisible();      // and it has its own menu entry
  await expect(page.getByRole("heading", { name: "Offline rejections" })).toBeVisible();
  await expect(page.getByText("No sale is waiting for attention.")).toBeVisible();
  await checkAccessibility(page, "offline rejections");
});
