import { Api, registerBusiness, unique } from "../lib/api";
import { code, company } from "../lib/seed";
import { checkAccessibility, expect, signIn, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";

// J4b: paying a supplier in a business that has no payment account yet. The page says so and lets the owner add a bank
// account right there; mobile money (which needs provider set-up) points to Payments; then the payment goes through.
test("J4b pay a supplier bill when no payment account exists", async ({ page }) => {
  const tag = unique("j4b");
  const owner = await registerBusiness(`J4b ${tag} Traders`, `owner@${tag}.test`, "owner-pass-123");
  const api = await new Api(owner).signIn();
  const { companyId } = await company(api);
  const supplierName = `Rentco ${code(4)}`;
  const supplier = await api.post("/purchasing/suppliers", { company_id: companyId, code: code(5), name: supplierName });
  const accounts = await api.post<any[]>(`/finance/companies/${companyId}/books`);      // the chart is made when first needed
  const rent = accounts.find((a) => a.subtype === "rent");
  const today = new Date().toLocaleDateString("en-CA");
  const bill = await api.post("/purchasing/bills", { supplier_id: supplier.id, supplier_invoice_no: `R-${code(4)}`, bill_date: today, lines: [{ quantity: "1", unit_cost: "100", expense_account_id: rent.id, description: "Rent" }] });
  await api.post(`/purchasing/bills/${bill.id}/submit`);

  await signIn(page, owner);
  await page.goto("/pay-suppliers");
  await pick(page, page.getByRole("combobox", { name: /Supplier/ }), supplierName);
  await expect(page.getByText("No Bank account is set up.")).toBeVisible();
  await expect(page.getByLabel(lbl("Pay from"))).toHaveCount(0);
  await page.getByLabel(lbl("Spread one payment")).fill("100");
  await page.getByRole("button", { name: "Spread" }).click();
  await expect(page.getByRole("button", { name: "Pay $100.00" })).toBeDisabled();           // nowhere to pay from yet
  await checkAccessibility(page, "pay with no account");

  // mobile money needs provider set-up, so it points to the Payments screen instead of a quick form
  await page.getByLabel(lbl("Method")).selectOption("mobile_money");
  await expect(page.getByText("No Mobile money account is set up.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Payments accounts" })).toBeVisible();
  await page.getByLabel(lbl("Method")).selectOption("bank");

  // a bank account is added from the page, chosen automatically, and the payment goes through
  await page.getByRole("button", { name: "Add a Bank account" }).click();
  await drawer(page).getByLabel(lbl("Account name")).fill(`Operating ${code(3)}`);
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/added\.$/).first()).toBeVisible();
  await expect(page.getByLabel(lbl("Pay from"))).toContainText("Operating");
  await page.getByRole("button", { name: "Pay $100.00" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Pay $100.00" }).click();
  await expect(page.getByText("1 payment(s) recorded.")).toBeVisible();
  await expect(page.getByText("Nothing to pay.")).toBeVisible();
});
