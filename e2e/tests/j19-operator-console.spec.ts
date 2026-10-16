import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Api, registerBusiness, unique } from "../lib/api";
import { checkAccessibility, expect, test } from "../lib/test";

// J19: platform staff use the operator console at /operator. They sign in with an email and a password only (a business
// owner's account does nothing there), see the units found on disk, install and uninstall a throwaway plugin that run.sh
// put in an extra folder, switch it on for a business with a reason, meet the "confirm your password" box when the server
// asks for one, change their own password, upgrade the business databases after the plugin gets a new migration, and see why an uninstall is refused while a
// business still holds the plugin's data.

const PLUGIN = "e2escratch";

test("J19 operator console", async ({ page }) => {
  const email = process.env.E2E_OPERATOR_EMAIL!, password = process.env.E2E_OPERATOR_PASSWORD!;
  const extra = process.env.E2E_EXTRA_PLUGINS!;
  expect(email && password && extra, "run.sh creates the operator and the extra plugin folder").toBeTruthy();

  const tag = unique("j19");
  const business = `J19 ${tag} Traders`;
  const owner = await registerBusiness(business, `owner@${tag}.test`, "owner-pass-123");
  const ownerApi = await new Api(owner).signIn();

  // --- not signed in: only the sign-in screen, wherever you go
  await page.goto("/operator/units");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Console areas" })).toHaveCount(0);
  await checkAccessibility(page, "operator sign-in");

  // --- a business owner's password is no way in
  await page.getByLabel("Email").fill(owner.email);
  await page.getByLabel("Password").fill(owner.password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  // --- the operator: the password alone opens the console (there is no code step)
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Enter your code" })).toHaveCount(0);
  const nav = page.getByRole("navigation", { name: "Console areas" });
  await expect(nav).toBeVisible();                                                           // signed in, on the page that was asked for
  await nav.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Subscribers" })).toBeVisible();
  await nav.getByRole("link", { name: "Add-ons & units" }).click();
  await expect(page.getByRole("heading", { name: "Platform units" })).toBeVisible();

  // --- the units: the kernel offers no uninstall, the scratch plugin is available
  const row = (name: string) => page.getByRole("row").filter({ hasText: name });
  await expect(row("Kernel").getByRole("button")).toHaveCount(0);
  await page.getByPlaceholder("Search units").fill(PLUGIN);
  await expect(row("E2E scratch plugin")).toContainText("Available");
  await checkAccessibility(page, "platform units");

  // --- install it; the server first asks to confirm the password (made to happen here), then the same install goes through
  let refusedOnce = false;
  await page.route("**/api/v1/operator/units/*/install", async (route) => {
    if (!refusedOnce) {
      refusedOnce = true;
      return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ error: "mfa_step_up_required", message: "Confirm your password to make this change" }) });
    }
    return route.continue();
  });
  await row("E2E scratch plugin").getByRole("button", { name: /Install/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("This installs one unit");
  await dialog.getByRole("button", { name: "Install", exact: true }).click();
  const passwordBox = page.getByLabel("Your password");
  await expect(passwordBox).toBeVisible();
  await expect(page.getByLabel("Authenticator code")).toHaveCount(0);
  await passwordBox.fill("not-the-password-1");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByText("That password is not right")).toBeVisible();
  await passwordBox.fill(password);
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByText("E2E scratch plugin is installed.")).toBeVisible();
  await expect(row("E2E scratch plugin")).toContainText("Installed");

  // --- a business: switch the plugin on with a reason
  await nav.getByRole("link", { name: "Subscribers" }).click();
  await page.getByPlaceholder("Search by name or code").fill(business);
  await page.getByRole("row").filter({ hasText: business }).click();
  await expect(page.getByRole("heading", { name: business })).toBeVisible();
  await page.getByRole("tab", { name: "Support" }).click();
  await expect(page.getByText("has not given support access")).toBeVisible();             // the console never bypasses consent
  await expect(page.getByRole("button", { name: "Open a support session" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Units" }).click();
  await page.getByPlaceholder("Search units").fill("scratch");
  await page.getByRole("row").filter({ hasText: "E2E scratch plugin" }).getByRole("button", { name: "Switch on" }).click();
  const why = page.getByRole("dialog");
  await expect(why.getByRole("button", { name: "Switch on" })).toBeDisabled();             // a reason is required
  await why.getByLabel(/Why/).fill("Pilot of the scratch plugin");
  await why.getByRole("button", { name: "Switch on" }).click();
  await expect(page.getByRole("row").filter({ hasText: "E2E scratch plugin" })).toContainText("On");
  await checkAccessibility(page, "operator business");
  const units = await ownerApi.get<{ name: string; enabled: boolean }[]>("/units/catalog");      // and the business sees it is on
  expect(units.find((u) => u.name === PLUGIN)?.enabled).toBe(true);

  // --- the plugin gets a new migration: the units list and the health page both show the business is behind
  const folder = join(extra, PLUGIN);
  writeFileSync(join(folder, "migrations", "0002_more.up.sql"), "alter table plg_e2escratch.note add column body text;\n");
  writeFileSync(join(folder, "manifest.toml"), readFileSync(join(folder, "manifest.toml"), "utf8").replace('version = "1.0.0"', 'version = "1.1.0"'));
  await nav.getByRole("link", { name: "Health" }).click();
  await expect(page.getByRole("heading", { name: "Platform health" })).toBeVisible();
  await nav.getByRole("link", { name: "Backups & upgrades" }).click();
  await expect(page.getByRole("heading", { name: "Backups & upgrades" })).toBeVisible();
  await expect(page.getByText(business)).toBeVisible();
  await page.getByRole("button", { name: /Upgrade \d+ business/ }).click();
  const upgrade = page.getByRole("dialog");
  await upgrade.getByRole("button", { name: /^Upgrade \d+$/ }).click();
  await expect(upgrade.getByText("Every business is up to date.")).toBeVisible();
  await expect(upgrade.getByText(/Upgraded: 1 migration/)).toBeVisible();
  await upgrade.getByRole("button", { name: "Done" }).click();
  await checkAccessibility(page, "platform health");

  // --- the unit itself still needs its record upgraded; then it is current
  await nav.getByRole("link", { name: "Add-ons & units" }).click();
  await page.getByPlaceholder("Search units").fill(PLUGIN);
  await expect(row("E2E scratch plugin")).toContainText("Needs upgrade");
  await row("E2E scratch plugin").getByRole("button", { name: /Upgrade/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Upgrade", exact: true }).click();
  await expect(row("E2E scratch plugin")).toContainText("Installed");

  // --- uninstalling is refused while the business holds the plugin, and the dialog says which one
  await row("E2E scratch plugin").getByRole("button", { name: /Uninstall/ }).click();
  const refused = page.getByRole("dialog");
  await expect(refused).toContainText(business);
  await expect(refused.getByRole("button", { name: "Uninstall", exact: true })).toBeDisabled();
  await refused.getByRole("button", { name: "Cancel" }).click();

  // --- the business switches it off and removes its data (its own Apps page logic, here through the API); now it can go
  await nav.getByRole("link", { name: "Subscribers" }).click();
  await page.getByPlaceholder("Search by name or code").fill(business);
  await page.getByRole("row").filter({ hasText: business }).click();
  await page.getByRole("tab", { name: "Units" }).click();
  await page.getByPlaceholder("Search units").fill("scratch");
  await page.getByRole("row").filter({ hasText: "E2E scratch plugin" }).getByRole("button", { name: "Switch off" }).click();
  await page.getByRole("dialog").getByLabel(/Why/).fill("Pilot ended");
  await page.getByRole("dialog").getByRole("button", { name: "Switch off" }).click();
  await expect(page.getByRole("row").filter({ hasText: "E2E scratch plugin" })).toContainText("Off, data kept");
  await ownerApi.post(`/units/${PLUGIN}/remove`, { confirm: PLUGIN });

  await nav.getByRole("link", { name: "Add-ons & units" }).click();
  await page.getByPlaceholder("Search units").fill(PLUGIN);
  await row("E2E scratch plugin").getByRole("button", { name: /Uninstall/ }).click();
  const gone = page.getByRole("dialog");
  const confirmButton = gone.getByRole("button", { name: "Uninstall", exact: true });
  await expect(confirmButton).toBeDisabled();
  await gone.getByRole("textbox").fill(PLUGIN);
  await confirmButton.click();
  await expect(row("E2E scratch plugin")).toContainText("Available");

  // --- operators, with the trail of what was changed
  await nav.getByRole("link", { name: "Operators & roles" }).click();
  await expect(page.getByText("E2E Operator").first()).toBeVisible();
  await expect(page.getByText("unit.install").first()).toBeVisible();
  await expect(page.getByText("business.unit_enable").first()).toBeVisible();
  await checkAccessibility(page, "operators");

  // --- the operator's own account: a wrong current password is refused, then the password is changed and used
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "My account" }).click();
  await expect(page.getByRole("heading", { name: "My account" })).toBeVisible();
  const newPassword = `${password}-changed`;
  await page.getByLabel("Current password").fill("not-the-password-1");
  await page.getByLabel(/^New password(?! again)/).fill(newPassword);
  await page.getByLabel("New password again").fill(newPassword);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("alert")).toContainText("current password is not right");
  await page.getByLabel("Current password").fill(password);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Your password was changed.")).toBeVisible();
  await checkAccessibility(page, "operator account");

  // --- signing out ends it; the old password no longer works and the new one does: the console asks again, and the business app never knew
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/operator/health");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toContainText("Wrong email or password");
  await page.getByLabel("Password").fill(newPassword);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Platform health" })).toBeVisible();

  // --- put the shared operator's password back for the journeys that follow
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "My account" }).click();
  await page.getByLabel("Current password").fill(newPassword);
  await page.getByLabel(/^New password(?! again)/).fill(password);
  await page.getByLabel("New password again").fill(password);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Your password was changed.")).toBeVisible();
});
