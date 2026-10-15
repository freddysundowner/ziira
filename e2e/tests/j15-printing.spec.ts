import type { Page } from "@playwright/test";

import { closeOpenTills, code, seedCatalogue, seedPayslip } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";

// J15: what is printed. Each printable page is shown in print mode: the app around it (menu, top bar, buttons) is gone, the
// document itself is there, and the browser can turn it into a PDF with something in it.
async function expectPrintable(page: Page, what: string) {
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("aside:visible, header.app-bar:visible"), `${what}: the menu and top bar are not printed`).toHaveCount(0);
  await expect(page.locator(".no-print:visible"), `${what}: buttons marked no-print are not printed`).toHaveCount(0);
  const pdf = await page.pdf({ printBackground: true });
  expect(pdf.subarray(0, 5).toString(), `${what}: a PDF`).toBe("%PDF-");
  expect(pdf.length, `${what}: the PDF has content`).toBeGreaterThan(3000);
}

test("J15 receipt, Z report, statement and payslip print cleanly", async ({ page }) => {
  const s = shared();
  const owner = await signedInApi(s.owner);
  const sam = await signedInApi(s.second);
  await closeOpenTills(owner);
  const cat = await seedCatalogue(owner, [{ name: "Lantern", price: 25, cost: 10, qty: 20 }]);
  const till = await owner.post("/pos/tills", { device_id: cat.deviceId, opening_float: "0" });
  const sale = await owner.post("/pos/sales", { till_session_id: till.id, lines: [{ product_id: cat.products[0].id, quantity: "2" }], payments: [{ method: "cash", amount: "50" }] });
  await owner.post(`/pos/tills/${till.id}/close`, { counted_cash: "50" });
  const supplier = await owner.post("/purchasing/suppliers", { company_id: cat.companyId, code: code(5), name: `Printco ${code(4)}` });
  const slip = await seedPayslip(owner, sam, cat.companyId);

  await signIn(page, s.owner);

  // --- the receipt of a sale
  await page.goto(`/pos/sales/${sale.id}`);
  await page.getByRole("button", { name: "Receipt", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(sale.number)).toBeVisible();
  await page.emulateMedia({ media: "print" });
  const receipt = page.locator(".print-root");
  await expect(receipt).toBeVisible();
  await expect(receipt).toContainText(sale.number);
  await expect(receipt).toContainText("50.00");
  await expect(page.getByRole("dialog")).toBeHidden();                       // the on-screen copy is not printed twice
  await expectPrintable(page, "receipt");
  await page.emulateMedia({ media: "screen" });

  // --- the Z report of the closed till
  await page.goto(`/pos/tills/${till.id}`);
  await expect(page.getByRole("button", { name: "Print Z report" })).toBeVisible();
  await page.emulateMedia({ media: "print" });
  const z = page.locator(".print-root");
  await expect(z).toBeVisible();
  await expect(z).toContainText(/Z report/i);
  await expect(z).toContainText("50.00");
  await expectPrintable(page, "Z report");
  await page.emulateMedia({ media: "screen" });

  // --- a supplier's statement
  await page.goto(`/suppliers/${supplier.id}`);
  await page.getByRole("tab", { name: "Account", exact: true }).click();
  await expect(page.getByRole("button", { name: "Print", exact: true })).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.getByText("Account statement", { exact: true })).toBeVisible();
  await expectPrintable(page, "supplier statement");
  await page.emulateMedia({ media: "screen" });

  // --- a payslip: the page asks the API for a printable document and prints it from a hidden frame
  await page.goto(`/payslips/${slip.payslipId}`);
  await page.getByRole("button", { name: "Print", exact: true }).click();
  const html = await page.locator("iframe[aria-hidden='true']").getAttribute("srcdoc");
  expect(html).toContain(slip.name);
  expect(html).toContain("1,500.00");
  const printed = await page.context().newPage();
  await printed.setContent(html!);
  await printed.emulateMedia({ media: "print" });
  await expect(printed.getByText(slip.name).first()).toBeVisible();
  await expect(printed.getByText("1,500.00").first()).toBeVisible();
  const pdf = await printed.pdf();
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.length).toBeGreaterThan(3000);
  await printed.close();
  await page.emulateMedia({ media: "screen" });
  await checkAccessibility(page, "payslip");
});
