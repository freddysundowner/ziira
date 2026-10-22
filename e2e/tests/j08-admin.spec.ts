import { code } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, test } from "../lib/test";
import { drawer, lbl } from "../lib/ui";

// J8: a user created in the UI with a branch-limited Cashier role sees only what a cashier should; a business setting is
// changed and persists; an API key's secret is shown once and only once.
test("J8 admin: users and roles, settings, API keys", async ({ page, second }) => {
  const s = shared();
  const tag = code(5).toLowerCase();
  const cashier = { email: `cathy@${tag}.test`, password: "cashier-pass-123", name: `Cathy ${tag}` };

  await signIn(page, s.owner);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).first().click();
  await drawer(page).getByLabel(lbl("Full name")).fill(cashier.name);
  await drawer(page).getByLabel(lbl("Email")).fill(cashier.email);
  await drawer(page).getByLabel(lbl("Password")).fill(cashier.password);
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: cashier.name })).toBeVisible();
  await checkAccessibility(page, "users");

  // --- give her the Cashier role for one branch
  await page.getByRole("row").filter({ hasText: cashier.name }).getByRole("button", { name: "Actions" }).click();
  await page.getByRole("menuitem", { name: /Roles/ }).click();
  const roles = drawer(page);
  await roles.getByLabel(lbl("Role")).selectOption({ label: "Cashier" });
  await roles.getByLabel(lbl("Applies to")).selectOption("branch");
  await roles.getByLabel(lbl("Company")).selectOption({ index: 1 });
  await roles.getByLabel(lbl("Branch")).selectOption({ index: 1 });
  await roles.getByRole("button", { name: "Give role" }).click();
  await expect(roles.getByText(/One branch · /)).toBeVisible();

  // --- what she sees: the till, not the books, payroll or administration
  const cathy = await second(cashier);
  const nav = cathy.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Sell", exact: true })).toHaveAttribute("href", "/pos/terminal");      // a cashier's Sell entry is the till itself
  await expect(cathy.getByRole("link", { name: "Point of sale" })).toBeVisible();                              // and Home offers it as a shortcut
  for (const hidden of ["Journal", "Payroll", "Users", "Settings", "Suppliers"]) {
    await expect(nav.getByRole("link", { name: hidden })).toHaveCount(0);
  }
  for (const path of ["/finance/journal", "/admin/users", "/payroll", "/admin/api-keys"]) {
    await cathy.goto(path);
    await expect(cathy.getByText("This page does not exist, or you do not have access to it.")).toBeVisible();
  }
  await checkAccessibility(cathy, "cashier home");

  // --- a business setting: change, save, reload, still there
  await page.goto("/admin/settings");
  const tolerance = page.getByLabel("Supplier bill price tolerance (%)", { exact: true }).last();
  await tolerance.fill("7");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Settings saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Supplier bill price tolerance (%)", { exact: true }).last()).toHaveValue("7");
  await checkAccessibility(page, "settings");

  // --- an API key: the secret appears once
  await page.goto("/admin/api-keys");
  await page.getByRole("button", { name: "New key" }).first().click();
  await drawer(page).getByLabel(lbl("Name")).fill(`Reports ${tag}`);
  await drawer(page).getByRole("checkbox", { name: "reports.view" }).check();          // the first box is "Read-only" (on by default), so pick a right by name
  await drawer(page).getByRole("button", { name: /^Create key/ }).click();
  const secret = page.getByRole("dialog");
  const shown = await secret.getByLabel("Secret key").inputValue();
  expect(shown.length).toBeGreaterThan(20);
  await secret.getByRole("button", { name: "I have saved it" }).click();
  await expect(page.getByRole("cell", { name: `Reports ${tag}`, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(shown)).toHaveCount(0);        // never shown again
  expect(await page.content()).not.toContain(shown);
  await checkAccessibility(page, "api keys");
});
