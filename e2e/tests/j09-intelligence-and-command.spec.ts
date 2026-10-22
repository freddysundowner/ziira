import { closeOpenTills, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";

const money = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// J9: a till closed with a cash difference; the check's limit is lowered in the UI and the checks are run from the UI; a
// finding appears and is acknowledged and explained; Intelligence's Today page shows today's sales; a brief preview renders.
test("J9 intelligence: things to look at and Today", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Lamp", price: 25, cost: 12, qty: 20 }]);
  const till = await api.post("/pos/tills", { device_id: cat.deviceId, opening_float: "0" });
  await api.post("/pos/sales", { till_session_id: till.id, lines: [{ product_id: cat.products[0].id, quantity: "2" }], payments: [{ method: "cash", amount: "50" }] });
  const reasons = await api.get<any[]>("/settings/reason-codes?category=till_variance").catch(() => [] as any[]);
  await api.post(`/pos/tills/${till.id}/close`, { counted_cash: "40", reason_code_id: reasons[0]?.id ?? null, note: "short in the drawer" });

  await signIn(page, s.owner);
  await page.goto("/intelligence/watching");
  const card = page.getByText("A till is out by more than usual", { exact: true }).locator('xpath=ancestor::div[contains(@class,"py-4")][1]');
  await card.getByLabel("Amount above which it is flagged").fill("5");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved.").first()).toBeVisible();
  await checkAccessibility(page, "check settings");
  await page.getByRole("button", { name: "Look again now" }).first().click();
  await expect(page.getByText(/things checked: \d+ new/)).toBeVisible();

  // a new business is not greeted with a finding about the owner's own role, made when it was registered
  const all = await api.get<any[]>("/intel/findings?limit=200");
  expect(all.filter((f) => /Olive Owner was given the role/.test(f.summary))).toEqual([]);

  // --- the finding
  // (the shared business has had other tills close short in earlier journeys, and the list groups them: open this journey's finding by its own id)
  const mine = (await api.get<any[]>("/intel/findings?limit=200")).find((f) => /closed USD 10.00 short: USD 40.00 counted against USD 50.00 expected/.test(f.summary));
  expect(mine, "the check found this journey's till").toBeTruthy();
  await page.goto("/intelligence/things");
  await expect(page.getByRole("link", { name: "A till is out by more than usual" }).first()).toBeVisible();
  await page.goto(`/intelligence/things/${mine.id}`);
  await expect(page.getByText(/closed USD 10.00 short: USD 40.00 counted against USD 50.00 expected/).first()).toBeVisible();
  await page.getByRole("button", { name: "I'm on it" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "I'm on it" }).click();
  await expect(page.getByText("Noted. Your team can see you are on it.")).toBeVisible();
  await page.getByRole("button", { name: "Explain what happened", exact: true }).click();
  await page.getByRole("dialog").getByRole("textbox").fill("The cashier gave 10 too much change; we retrained her.");
  await page.getByRole("dialog").getByRole("button", { name: "Save what happened" }).click();
  await expect(page.getByText("Saved.").first()).toBeVisible();
  await expect(page.getByText("Explained").first()).toBeVisible();
  await checkAccessibility(page, "finding");

  // --- Today: today's sales after a refresh equal the sales made today (from the sales API)
  const today = new Date().toLocaleDateString("en-CA");
  const sold = (await api.get<any[]>(`/pos/sales?limit=500&business_date=${today}`)).filter((x) => x.status === "posted").reduce((a, x) => a + Number(x.total), 0);
  await page.goto("/intelligence");
  await page.getByRole("button", { name: "Show how the business is doing" }).click();
  await page.getByRole("button", { name: "Update figures" }).click();
  await expect(page.getByText(/Last refreshed/)).toBeVisible();
  await expect(page.getByText(`$${money(sold)}`).first()).toBeVisible();
  await checkAccessibility(page, "today");

  // --- a brief preview
  await page.goto("/intelligence/summary");
  await page.getByRole("button", { name: "See today's note" }).click();
  await expect(page.getByText(/sales|Sales/).first()).toBeVisible();
  await checkAccessibility(page, "briefs");
});
