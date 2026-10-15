import { closeOpenTills, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl, pick } from "../lib/ui";

const money = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// J6: the books after trading: the journal lists the entries, the trial balance balances, profit and loss agrees with what
// was sold (read from the sales API, an independent source), an expense is captured (and approved if asked), a bank reconciliation starts.
test("J6 money: journal, trial balance, profit and loss, expense, reconciliation", async ({ page, second }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Saw", price: 25, cost: 15, qty: 10 }]);
  const till = await api.post("/pos/tills", { device_id: cat.deviceId, opening_float: "0" });
  const sale = await api.post("/pos/sales", { till_session_id: till.id, lines: [{ product_id: cat.products[0].id, quantity: "3" }], payments: [{ method: "cash", amount: "75" }] });

  const today = new Date().toLocaleDateString("en-CA");
  await signIn(page, s.owner);
  await page.goto("/finance/journal");
  await expect(page.getByRole("row").filter({ hasText: sale.number })).toBeVisible();
  await page.getByPlaceholder("Search by number or description").fill(sale.number);
  await page.getByRole("row").filter({ hasText: sale.number }).click();
  await expect(page.getByText("Sales").first()).toBeVisible();          // the entry's lines: cash in, sales income
  await checkAccessibility(page, "journal entry");

  // --- trial balance
  await page.goto("/finance/reports/trial");
  await expect(page.getByRole("tab", { name: "Trial balance" })).toHaveAttribute("aria-selected", "true");
  const tb = await api.get<any>(`/finance/reports/trial-balance?company_id=${cat.companyId}&as_of=${today}`);
  expect(tb.balanced).toBe(true);
  await expect(page.getByText(money(Number(tb.total_debit))).first()).toBeVisible();
  await checkAccessibility(page, "trial balance");

  // --- profit and loss: sales income = posted sales less returns, from the sales API
  const sales = (await api.get<any[]>("/pos/sales?limit=500")).filter((x) => x.status === "posted");
  const returns = (await api.get<any[]>("/pos/returns?limit=500")).filter((x) => x.status === "posted");
  const income = sales.reduce((a, x) => a + Number(x.total), 0) - returns.reduce((a, x) => a + Number(x.total), 0);
  await page.goto("/finance/reports/pnl");
  await expect(page.getByRole("row", { name: /Total income/ })).toContainText(`$${money(income)}`);
  await checkAccessibility(page, "profit and loss");

  const expensesNow = async () => {
    const r = await api.get<any>(`/finance/reports/profit-and-loss?company_id=${cat.companyId}&date_from=${today.slice(0, 8)}01&date_to=${today}`);
    return Number(r.consolidated.total_expenses);
  };
  const expensesBefore = await expensesNow();

  // --- an expense of 35.00 paid in cash
  await page.goto("/finance/expenses");
  await page.getByRole("button", { name: "New expense" }).first().click();
  await drawer(page).getByLabel(lbl("Description")).fill("Diesel for the van");
  await drawer(page).getByRole("combobox", { name: /Category/ }).click();
  // categories are what a person spends on: the accounts the system posts by itself are not offered
  await expect(page.getByRole("listbox").getByRole("option", { name: /Transport/ })).toBeVisible();
  for (const system of [/Cost of goods sold/, /Inventory shrinkage/, /Purchase price variance/]) await expect(page.getByRole("listbox").getByRole("option", { name: system })).toHaveCount(0);
  await page.getByRole("listbox").getByRole("option", { name: /Transport/ }).click();
  await drawer(page).getByLabel(lbl("Amount")).fill("35");
  await drawer(page).getByRole("button", { name: "Save and submit" }).click();
  await expect(page.getByText(/Sent for approval|Posted|posted/).first()).toBeVisible();
  const expense = (await api.get<any[]>("/finance/expenses")).find((x) => x.description === "Diesel for the van");
  if (expense.status === "pending_approval") {
    const sam = await second(s.second);
    await sam.goto("/admin/approvals");
    await sam.getByRole("row").filter({ hasText: /expense/i }).getByRole("button", { name: "Approve" }).first().click();
    await sam.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  }
  await expect.poll(async () => (await api.get<any[]>("/finance/expenses")).find((x) => x.description === "Diesel for the van").status).toBe("posted");
  await page.goto("/finance/reports/pnl");
  await expect(page.getByRole("row", { name: /Total expenses/ })).toContainText(`$${money(expensesBefore + 35)}`);
  expect(await expensesNow()).toBeCloseTo(expensesBefore + 35, 2);

  // --- start a bank reconciliation
  await page.goto("/finance/bank");
  await page.getByRole("button", { name: "Start reconciliation" }).first().click();
  await drawer(page).getByRole("combobox", { name: /Account/ }).click();
  // only places money is kept can be checked against a statement
  await expect(page.getByRole("listbox").getByRole("option", { name: /1020 · Bank/ })).toBeVisible();
  for (const other of [/Accounts receivable/, /Inventory/, /VAT input/]) await expect(page.getByRole("listbox").getByRole("option", { name: other })).toHaveCount(0);
  await page.getByRole("listbox").getByRole("option", { name: /1020 · Bank/ }).click();
  await drawer(page).getByLabel(lbl("Statement balance")).fill("1000");
  await drawer(page).getByRole("button", { name: "Start", exact: true }).click();
  await page.waitForURL(/\/finance\/bank\/[0-9a-f-]+$/);
  await expect(page.getByText("Statement of")).toBeVisible();
  await checkAccessibility(page, "reconciliation");

  // --- a report name that does not exist is said so, not quietly replaced by another report
  await page.goto("/finance/reports/nonsense");
  await expect(page.getByText("This report does not exist")).toBeVisible();
  await page.getByRole("link", { name: "Go to the reports" }).click();
  await expect(page.getByRole("tab", { name: "Profit and loss" })).toBeVisible();
});
