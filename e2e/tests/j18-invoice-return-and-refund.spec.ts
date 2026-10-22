import { closeOpenTills, code, customerWithCredit, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";

// J18: goods come back against an invoice (a credit note while it is owed, cash once it is paid), and money a customer
// paid in advance is given back and then reversed.
test("J18 return against an invoice and a refund of an advance", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Chisel", price: 40, cost: 25, qty: 20 }]);
  const chisel = cat.products[0];
  const customer = await customerWithCredit(api, cat.companyId, `Achieng Hardware ${code(4)}`);
  // 3 chisels at 40 = 120, issued through the API; the browser does the returns and refunds
  const invoice = await api.post("/pos/invoices", { customer_id: customer.id, branch_id: cat.branchId, location_id: cat.locationId,
    lines: [{ product_id: chisel.id, quantity: "3" }] });
  expect(invoice.total).toBe("120.00");

  await signIn(page, s.owner);
  await page.goto(`/pos/invoices/${invoice.id}`);
  await expect(page.getByText("Unpaid", { exact: true }).first()).toBeVisible();

  // --- one chisel back while the invoice is owed: a credit note, so the customer owes 80
  await page.getByRole("button", { name: "Return goods" }).click();
  await drawer(page).getByLabel("Returning").fill("1");
  await drawer(page).getByLabel(lbl("Reason")).selectOption({ index: 1 });
  await expect(drawer(page).getByLabel("Refund as").locator("option")).toHaveText(["Credit on account", "Exchange"]);
  await drawer(page).getByRole("button", { name: "Record return" }).click();
  await expect(page.getByText(/recorded: \$40\.00 refunded/)).toBeVisible();
  const owed = page.locator("dt", { hasText: /^Owed$/ }).locator("xpath=following-sibling::dd");
  await expect(owed).toHaveText(/80\.00/);
  await checkAccessibility(page, "invoice after return");

  // --- it is paid in full; now money goes back: one more chisel, refunded in cash from an open till
  await api.post("/pos/receipts", { customer_id: customer.id, amount: "80.00", method: "cash", branch_id: cat.branchId });
  await api.post("/pos/tills", { device_id: cat.deviceId, opening_float: "100" });
  await page.reload();
  await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Return goods" }).click();
  await drawer(page).getByLabel("Returning").fill("1");
  await drawer(page).getByLabel(lbl("Reason")).selectOption({ index: 1 });
  await expect(drawer(page).getByLabel("Refund as").locator("option")).toHaveText(["Cash", "Mobile money", "Exchange"]);
  await drawer(page).getByRole("button", { name: "Record return" }).click();
  await expect(page.getByText(/recorded: \$40\.00 refunded/)).toBeVisible();

  // --- the returns list shows both
  await page.goto("/pos/returns");
  await expect(page.getByRole("cell", { name: "$40.00" }).nth(1)).toBeVisible();      // both returns, 40 each

  // --- the customer pays 50 in advance (held on account); give 20 back, then reverse that refund
  await api.post("/pos/receipts", { customer_id: customer.id, amount: "50.00", method: "cash", branch_id: cat.branchId, hold_balance: true });
  await page.goto("/pos/refunds");
  await expect(page.getByRole("main").getByRole("link", { name: "Refunds" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "New refund" }).click();
  await pick(page, drawer(page).getByRole("combobox"), customer.name);
  await drawer(page).getByRole("button", { name: "Give back" }).click();
  await expect(drawer(page).getByLabel(lbl("Amount"))).toHaveValue("50.00");
  await drawer(page).getByLabel(lbl("Amount")).fill("20");
  await drawer(page).getByLabel(lbl("Reason")).fill("Customer changed their mind");
  await drawer(page).getByRole("button", { name: "Give back" }).click();
  await expect(page.getByText(/\$20\.00 given back/)).toBeVisible();
  await expect(page.getByRole("cell", { name: customer.name })).toBeVisible();
  await checkAccessibility(page, "refunds");

  await page.getByRole("cell", { name: customer.name }).click();
  await drawer(page).getByRole("button", { name: "Reverse" }).click();
  await page.getByRole("dialog", { name: /Reverse/ }).last().getByLabel(lbl("Reason")).fill("Money did not leave the till");
  await page.getByRole("dialog", { name: /Reverse/ }).last().getByRole("button", { name: "Reverse" }).click();
  await expect(page.getByText("reversed.").first()).toBeVisible();
  await expect(drawer(page).getByText("Reversed", { exact: true }).first()).toBeVisible();

  await closeOpenTills(api);
});
