import { Api } from "../lib/api";
import { closeOpenTills, code, scopedUser, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl } from "../lib/ui";

// J8b: a second branch is added in the UI; a user scoped to it sees only its sales, stock, findings and Command Center
// figures, and the other branch's records answer 403 or 404 through the API.
test("J8b branch scoping: two branches, one scoped user", async ({ page, second }) => {
  const s = shared();
  const tag = code(5);
  const owner = await signedInApi(s.owner);
  await closeOpenTills(owner);
  const cat = await seedCatalogue(owner, [{ name: "Torch", price: 30, cost: 12, qty: 40 }]);

  // --- the subject: add a branch through the Organisation screen, then edit it
  await signIn(page, s.owner);
  await page.goto("/admin/organisation");
  await expect(page.getByRole("heading", { name: "Organisation" })).toBeVisible();
  await page.getByRole("button", { name: "Add branch" }).first().click();
  await drawer(page).getByLabel(lbl("Code")).fill(`b${tag}`.toLowerCase());
  await drawer(page).getByLabel(lbl("Name")).fill(`Lakeside ${tag}`);
  await drawer(page).getByLabel(lbl("Address")).fill("Shore Road");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: `Lakeside ${tag}` });
  await expect(row).toBeVisible();
  await expect(row.getByText(`B${tag}`, { exact: true })).toBeVisible();      // the code is kept in capitals
  await checkAccessibility(page, "organisation");
  await row.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("menuitem", { name: "Edit" }).click();
  await drawer(page).getByLabel(lbl("Name")).fill(`Lakeside ${tag} Market`);
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  const shop = page.getByRole("row").filter({ hasText: `Lakeside ${tag} Market` });
  await expect(shop).toBeVisible();

  const company = (await owner.get<any[]>("/organisation")).find((c) => c.id === cat.companyId);
  const branch = company.branches.find((b: any) => b.name === `Lakeside ${tag} Market`);
  expect(branch.address).toBe("Shore Road");

  // --- the new branch works at once: a store with stock, a till, and a manager scoped to it
  const store = await owner.post("/inventory/locations", { company_id: cat.companyId, branch_id: branch.id, kind: "store", code: `L${tag}`.slice(0, 10), name: `Lakeside store ${tag}` });
  await owner.post("/inventory/opening-stock", { company_id: cat.companyId, location_id: store.id, lines: [{ product_id: cat.products[0].id, quantity: "10", unit_cost: "12" }] });
  const device = await owner.post("/pos/devices", { branch_id: branch.id, code: `X${tag}`.slice(0, 8), name: `Lakeside till ${tag}`, location_id: store.id });
  const mgr = { name: `Mona ${tag}`, email: `mona${tag}@scoped.test`, password: "scoped-pass-123" };
  await scopedUser(owner, { ...mgr, role: "Branch Manager", companyId: cat.companyId, branchId: branch.id });
  const mona = await new Api({ ...mgr, name: mgr.name }).signIn();

  // --- a sale and a till that closes short at each branch
  const sellAndClose = async (api: Api, deviceId: string, quantity: number, counted: string) => {
    const till = await api.post("/pos/tills", { device_id: deviceId, opening_float: "1000" });
    const sale = await api.post("/pos/sales", { till_session_id: till.id, lines: [{ product_id: cat.products[0].id, quantity: String(quantity) }], payments: [{ method: "cash", amount: String(quantity * 30) }] });
    const reasons = await api.get<any[]>("/settings/reason-codes?category=till_variance").catch(() => [] as any[]);
    await api.post(`/pos/tills/${till.id}/close`, { counted_cash: counted, reason_code_id: reasons[0]?.id ?? null, note: "short" });
    return { till: till.id as string, sale: sale as { id: string; number: string; total: string } };
  };
  const hq = await sellAndClose(owner, cat.deviceId, 2, "100");        // 2 x 30 = 60 at the first branch
  const lake = await sellAndClose(mona, device.id, 1, "100");           // 1 x 30 = 30 at the new one
  await owner.post("/intel/run", { company_id: cat.companyId });
  await owner.post(`/command/pulse/refresh?company_id=${cat.companyId}`, {});

  // --- what Mona sees in the browser
  const monaPage = await second({ ...mgr });
  await monaPage.goto("/pos/sales");
  await expect(monaPage.getByRole("cell", { name: lake.sale.number })).toBeVisible();
  await expect(monaPage.getByRole("cell", { name: hq.sale.number })).toHaveCount(0);
  await checkAccessibility(monaPage, "scoped sales");

  await monaPage.goto("/stock");
  const stockRow = monaPage.getByRole("row").filter({ hasText: cat.products[0].name });
  await expect(stockRow).toBeVisible();
  await expect(stockRow).toContainText(/\b9(\.0+)?$/);                                              // her store's 10 less her 1 sale, not the business's 47
  await expect(stockRow).not.toContainText(/\b(38|47)\b/);
  await expect(monaPage.getByRole("option", { name: new RegExp(`Lakeside store ${tag}`) })).toHaveCount(1);
  await expect(monaPage.getByRole("option", { name: new RegExp(`Store ${cat.products[0].sku.slice(3)}`) })).toHaveCount(0);   // the first branch's store

  await monaPage.goto("/intelligence/things");
  await monaPage.getByRole("button", { name: "List" }).click();
  await monaPage.getByLabel("Given to me").uncheck();
  const shorts = monaPage.getByRole("row").filter({ hasText: /closed .* short/ });
  await expect(shorts.first()).toBeVisible();
  await expect(shorts.filter({ hasText: `Lakeside ${tag} Market` })).toHaveCount(await shorts.count());   // every till finding she sees is her branch's

  await monaPage.goto("/intelligence");
  await monaPage.getByRole("button", { name: "Show how the business is doing" }).click();
  await expect(monaPage.getByText(/Last refreshed/)).toBeVisible();
  await expect(monaPage.getByText("$30.00").first()).toBeVisible();
  await expect(monaPage.getByText("$60.00")).toHaveCount(0);
  await expect(monaPage.getByText("$90.00")).toHaveCount(0);

  // --- the API agrees: her lists hold only her branch, and the other branch's records are refused
  const salesSeen = (await mona.get<any[]>("/pos/sales?limit=500")).map((x) => x.id);
  expect(salesSeen).toContain(lake.sale.id);
  expect(salesSeen).not.toContain(hq.sale.id);
  const balances = await mona.get<any[]>("/inventory/balances");
  expect(balances.length).toBeGreaterThan(0);
  expect(balances.every((b) => b.location_id === store.id)).toBe(true);
  const findings = await mona.get<any[]>("/intel/findings?limit=200");
  expect(findings.length).toBeGreaterThan(0);
  expect(findings.every((f) => f.branch_id === branch.id || f.branch_id === null)).toBe(true);
  const overview = await mona.get<any>("/command/overview");
  expect(overview.figures.length).toBeGreaterThan(0);
  expect(overview.figures.every((f: any) => f.branch_id === branch.id), "no company-wide or other-branch figure").toBe(true);
  const sales = overview.figures.find((f: any) => f.metric === "pos.sales_total" && f.branch_id === branch.id);
  expect(sales, "a sales figure for her branch").toBeTruthy();
  expect(Number(sales.value)).toBe(30);

  const refused = (path: string) => mona.statusOf(path);
  for (const path of [`/pos/sales/${hq.sale.id}`, `/pos/tills/${hq.till}`, `/pos/tills/${hq.till}/report`]) expect([403, 404], path).toContain(await refused(path));
  const hqFinding = (await owner.get<any[]>("/intel/findings?limit=200")).find((f) => f.branch_id === cat.branchId && /closed/.test(f.summary));
  expect(hqFinding, "the first branch's short till should be a finding the owner sees").toBeTruthy();
  expect([403, 404]).toContain(await refused(`/intel/findings/${hqFinding.id}`));
  const hqBalances = await mona.get<any[]>(`/inventory/balances?location_id=${cat.locationId}`).catch(() => [] as any[]);
  expect(hqBalances).toEqual([]);

  // --- the owner still sees both
  const all = (await owner.get<any[]>("/pos/sales?limit=500")).map((x) => x.id);
  expect(all).toEqual(expect.arrayContaining([lake.sale.id, hq.sale.id]));
});
