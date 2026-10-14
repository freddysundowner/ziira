import { closeOpenTills, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { lbl } from "../lib/ui";

const money = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// J9: a till closed with a cash difference; the check's limit is lowered in the UI and the checks are run from the UI; a
// finding appears and is acknowledged and explained; the Command Center shows today's sales; a brief preview renders.
test("J9 intelligence findings and the Command Center", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Lamp", price: 25, cost: 12, qty: 20 }]);
  const till = await api.post("/pos/tills", { device_id: cat.deviceId, opening_float: "0" });
  await api.post("/pos/sales", { till_session_id: till.id, lines: [{ product_id: cat.products[0].id, quantity: "2" }], payments: [{ method: "cash", amount: "50" }] });
  const reasons = await api.get<any[]>("/settings/reason-codes?category=till_variance").catch(() => [] as any[]);
  await api.post(`/pos/tills/${till.id}/close`, { counted_cash: "40", reason_code_id: reasons[0]?.id ?? null, note: "short in the drawer" });

  await signIn(page, s.owner);
  await page.goto("/findings/checks");
  const card = page.getByText("Till closed with a cash difference", { exact: true }).locator('xpath=ancestor::div[contains(@class,"py-4")][1]');
  await card.getByLabel(lbl("Limit")).fill("5");
  await card.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Limits saved.")).toBeVisible();
  await checkAccessibility(page, "check settings");
  await page.getByRole("button", { name: "Run checks now" }).first().click();
  await expect(page.getByText(/checks run: \d+ new/)).toBeVisible();

  // --- the finding
  await page.goto("/findings");
  await page.getByRole("row").filter({ hasText: "closed USD 10.00 short" }).first().click();
  await expect(page.getByText(/closed USD 10.00 short: USD 40.00 counted against USD 50.00 expected/).first()).toBeVisible();
  await page.getByRole("button", { name: "I have seen this" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Mark as seen" }).click();
  await expect(page.getByText("Marked as seen.")).toBeVisible();
  await page.getByRole("button", { name: "Explain", exact: true }).click();
  await page.getByRole("dialog").getByRole("textbox").fill("The cashier gave 10 too much change; we retrained her.");
  await page.getByRole("dialog").getByRole("button", { name: "Save explanation" }).click();
  await expect(page.getByText("Explanation saved.")).toBeVisible();
  await expect(page.getByText("Explained").first()).toBeVisible();
  await checkAccessibility(page, "finding");

  // --- the Command Center: today's sales after a refresh equal the sales made today (from the sales API)
  const today = new Date().toLocaleDateString("en-CA");
  const sold = (await api.get<any[]>(`/pos/sales?limit=500&business_date=${today}`)).filter((x) => x.status === "posted").reduce((a, x) => a + Number(x.total), 0);
  await page.goto("/command");
  await page.getByRole("button", { name: "Refresh figures" }).click();
  await expect(page.getByText(/Last refreshed/)).toBeVisible();
  await expect(page.getByText(`$${money(sold)}`).first()).toBeVisible();
  await checkAccessibility(page, "command center");

  // --- a brief preview
  await page.goto("/command/briefs");
  await page.getByRole("button", { name: "Show preview" }).click();
  await expect(page.getByText(/sales|Sales/).first()).toBeVisible();
  await checkAccessibility(page, "briefs");
});
