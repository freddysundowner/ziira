import { Api } from "../lib/api";
import { closeOpenTills, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { lbl } from "../lib/ui";

// J3: open a till in the terminal, sell for cash, hold and resume, a mobile-money sale by code, close the till with a
// counted amount and see the variance; then the back office: sales list, receipt, void with a reason, a return.
test("J3 sell at the till, close it, review, void and return", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Cable", price: 10, cost: 6, qty: 50 }, { name: "Plug", price: 4, cost: 2, qty: 30 }]);
  const [cable, plug] = cat.products;

  await signIn(page, s.owner);
  await page.goto("/pos/terminal");
  await checkAccessibility(page, "terminal open till");
  await page.getByLabel(lbl("Till (device)")).selectOption({ label: `Till ${cat.deviceId ? "" : ""}`.trim() }).catch(() => undefined);
  await page.getByLabel(lbl("Opening float")).fill("100");
  await page.getByRole("button", { name: "Open till and start selling" }).click();

  // --- sale 1: two cables for cash, 30 handed over, 10 change
  const search = page.getByLabel("Search or scan: name, SKU or barcode");
  await expect(search).toBeVisible();
  await search.fill(cable.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: "One more" }).click();
  await expect(page.getByText("20.00").first()).toBeVisible();
  await checkAccessibility(page, "terminal selling");
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByLabel(lbl("Handed over")).fill("30");     // the dialog starts with a cash leg for the full amount
  await expect(page.getByText("Change", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  await expect(page.getByText("Give change")).toBeVisible();
  await page.getByRole("button", { name: "New sale" }).click();

  // --- sale 2: hold it, then resume and pay exactly
  await search.fill(plug.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: "Hold", exact: true }).click();
  await expect(page.getByText("Sale held")).toBeVisible();
  await page.getByRole("button", { name: /^Held/ }).click();
  await page.getByRole("button", { name: "Resume" }).click();
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  await page.getByRole("button", { name: "New sale" }).click();

  // --- sale 3: mobile money with the code typed in (no prompt account is set up)
  await search.fill(plug.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Remove payment" }).click();
  await page.getByRole("button", { name: "Mobile money" }).click();
  await page.getByLabel(lbl("Mobile money code")).fill("QWE123XYZ");
  await page.getByRole("button", { name: "Complete sale" }).click();
  // no mobile-money account exists yet: a clear message, the cart is unchanged
  await expect(page.getByText(/No mobile_money account is set up/)).toBeVisible();
  await expect(page.getByText("Fix this and press Try again. The cart is unchanged.")).toBeVisible();
  await api.post("/payments/accounts", { company_id: cat.companyId, branch_id: cat.branchId, kind: "mobile_money", name: "Till wallet", provider: "fake", environment: "sandbox", shortcode: "174379" });
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  await expect(page.getByText(/Mobile money · QWE123XYZ/)).toBeVisible();
  await page.getByRole("button", { name: "New sale" }).click();

  // --- void the mobile-money sale from the back office (only possible while the till is open)
  const before = await api.get<any[]>("/pos/sales");
  const mobile = before.find((x) => Number(x.total) === 4 && x.payments?.some((p: any) => p.method === "mobile_money")) ?? (await Promise.all(before.map((x) => api.get<any>(`/pos/sales/${x.id}`)))).find((x) => x.payments.some((p: any) => p.method === "mobile_money"));
  await page.goto(`/pos/sales/${mobile.id}`);
  await page.getByRole("button", { name: "Void sale" }).click();
  await page.getByRole("dialog").getByLabel(lbl("Reason")).selectOption({ index: 1 });
  await page.getByRole("dialog").getByRole("button", { name: "Void sale" }).click();
  await expect(page.getByText("This sale was voided.")).toBeVisible();
  await page.goto("/pos/terminal");

  // --- a return of one cable, refunded in cash from the open till
  const twenty = (await api.get<any[]>("/pos/sales")).find((x) => Number(x.total) === 20);
  await page.goto(`/pos/sales/${twenty.id}`);
  await expect(page.getByText(cable.name).first()).toBeVisible();
  await page.getByRole("button", { name: "Receipt" }).click();
  await expect(page.getByRole("dialog").getByText(cable.name)).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Return goods" }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByLabel(lbl("Returning")).fill("1");
  await drawer.getByLabel(lbl("Reason")).selectOption({ index: 1 });
  await drawer.getByRole("button", { name: "Record return" }).click();
  await expect(page.getByText(/recorded: .*10\.00 refunded|waiting for a manager/)).toBeVisible();

  await page.goto("/pos/terminal");
  // --- close the till: float 100 + cash sales 20 + 4 - 10 cash refund = 114 expected; count 110
  await page.getByRole("button", { name: "Close till" }).click();
  await expect(page.getByText("114.00").first()).toBeVisible();
  await page.getByLabel(lbl("Cash counted")).fill("110");
  await expect(page.getByText(/4\.00 short/)).toBeVisible();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(lbl("Reason for the difference")).selectOption({ index: 1 });
  await dialog.getByRole("button", { name: "Close till" }).click();
  await expect(page.getByText("Till closed")).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  // after the till is closed a cash refund is refused with a clear reason
  await page.goto(`/pos/sales/${twenty.id}`);
  await page.getByRole("button", { name: "Return goods" }).click();
  await page.getByRole("dialog").getByLabel(lbl("Returning")).fill("1");
  await page.getByRole("dialog").getByLabel(lbl("Reason")).selectOption({ index: 1 });
  await page.getByRole("dialog").getByRole("button", { name: "Record return" }).click();
  await expect(page.getByText("Open a till to pay a cash refund")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

  // --- the sales list
  await page.goto("/pos/sales");
  await expect(page.getByRole("row").filter({ hasText: "20.00" })).toHaveCount(1);
  await expect(page.getByRole("row").filter({ hasText: "Voided" })).toHaveCount(1);
  await checkAccessibility(page, "sales list");

  // the till report and the stock agree with what was done at the screen
  const stock = await api.get<{ product_id: string; quantity: string }[]>("/inventory/balances");
  const qty = (id: string) => Number(stock.find((b) => b.product_id === id)?.quantity);
  expect(qty(cable.id)).toBe(49);   // 50 - 2 sold + 1 returned
  expect(qty(plug.id)).toBe(29);    // 30 - 1 (held, then sold) - 1 (mobile sale) + 1 (that sale voided)
});
