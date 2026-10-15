import { Api, registerBusiness, unique } from "../lib/api";
import { checkAccessibility, expect, guard, test } from "../lib/test";
import { totp } from "../lib/totp";
import { lbl } from "../lib/ui";

// J12: the owner makes two-step verification required of people with powerful roles; a second user is forced to set it up on
// the next sign-in (code made from the secret in the test, as an authenticator app would), signs in with a code, with a backup
// code (which works once), meets the wrong-code message, and is locked out after repeated wrong codes.
test("J12 two-step sign-in", async ({ browser, page, problems, refused }) => {
  const tag = unique("j12");
  const owner = await registerBusiness(`J12 ${tag} Traders`, `owner@${tag}.test`, "owner-pass-123");
  const api = await new Api(owner).signIn();
  const roles = await api.get<{ id: string; name: string }[]>("/roles");
  const ivy = { email: `ivy@${tag}.test`, password: "ivy-pass-12345", name: "Ivy Admin" };
  const made = await api.post("/users", { full_name: ivy.name, email: ivy.email, password: ivy.password });
  await api.post(`/users/${made.id}/roles`, { role_id: roles.find((r) => r.name === "Owner")!.id, scope: "tenant" });

  // --- the owner sets the policy in Settings
  await page.goto("/");
  await page.getByLabel("Email or phone").fill(owner.email);
  await page.getByLabel("Password", { exact: true }).fill(owner.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
  await page.goto("/admin/settings");
  await page.getByRole("tab", { name: "Security" }).click();
  await page.getByLabel("Two-step verification required for").selectOption("privileged");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Security settings saved.")).toBeVisible();
  await checkAccessibility(page, "security settings");

  // --- Ivy signs in and is stopped until she sets it up
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await context.newPage();
  guard(p, problems, refused);
  const passwordStep = async () => {
    await p.goto("/");
    await p.getByLabel("Email or phone").fill(ivy.email);
    await p.getByLabel("Password", { exact: true }).fill(ivy.password);
    await p.getByRole("button", { name: "Sign in" }).click();
  };
  await passwordStep();
  await expect(p.getByRole("heading", { name: "Set up two-step verification" })).toBeVisible();
  await expect(p.getByRole("navigation", { name: "Main" })).toHaveCount(0);            // nothing of the app until it is done
  await checkAccessibility(p, "two-step setup");
  const secret = ((await p.locator("code").first().textContent()) ?? "").replace(/\s+/g, "");
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);

  await p.getByLabel(lbl("6-digit code")).fill("000000");              // a wrong first code is refused and nothing is switched on
  await p.getByRole("button", { name: "Turn on" }).click();
  await expect(p.getByRole("alert").first()).toBeVisible();
  await p.getByLabel(lbl("6-digit code")).fill(totp(secret));
  await p.getByRole("button", { name: "Turn on" }).click();
  const list = p.getByRole("list", { name: "Save your backup codes" });
  await expect(list).toBeVisible();
  const codes = (await list.getByRole("listitem").allTextContents()).map((c) => c.trim());
  expect(codes).toHaveLength(10);
  for (const c of codes) expect(c).toMatch(/^[a-z0-9]{5}-[a-z0-9]{5}$/);
  await checkAccessibility(p, "backup codes");
  await p.getByLabel("I have saved my backup codes").check();
  await p.getByRole("button", { name: "Continue" }).click();
  await expect(p.getByRole("button", { name: "Account" })).toBeVisible();

  const signOut = async () => {
    await p.getByRole("button", { name: "Account" }).click();
    await p.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(p.getByRole("button", { name: "Sign in" })).toBeVisible();
  };
  await signOut();

  // --- a code from the app: the wrong one is refused with a clear message, the right one signs in
  await passwordStep();
  await expect(p.getByRole("heading", { name: "Two-step verification" })).toBeVisible();
  await checkAccessibility(p, "second step");
  await p.getByLabel(lbl("6-digit code")).fill("123456");
  await expect(p.getByText("That code is not right. Check the code in your app and try again.")).toBeVisible();
  // the code for the next 30 seconds: a code works only once and the one used to turn it on is spent
  await p.getByLabel(lbl("6-digit code")).fill(totp(secret, Date.now(), 1));
  await expect(p.getByRole("button", { name: "Account" })).toBeVisible();

  // --- the account page shows it on, with nine backup codes left after... none used yet: ten
  await p.goto("/admin/account");
  await expect(p.getByText("10 backup codes left")).toBeVisible();
  await signOut();

  // --- a backup code works once
  await passwordStep();
  await p.getByRole("button", { name: "Use a backup code instead" }).click();
  await p.getByLabel(lbl("Backup code")).fill(codes[0]);
  await p.getByRole("button", { name: "Verify" }).click();
  await expect(p.getByRole("button", { name: "Account" })).toBeVisible();
  await p.goto("/admin/account");
  await expect(p.getByText("9 backup codes left")).toBeVisible();
  await signOut();
  await passwordStep();
  await p.getByRole("button", { name: "Use a backup code instead" }).click();
  await p.getByLabel(lbl("Backup code")).fill(codes[0]);
  await p.getByRole("button", { name: "Verify" }).click();
  await expect(p.getByText("That backup code is not right, or it was already used.")).toBeVisible();

  // --- repeated wrong codes lock the second step for a while
  await p.getByRole("button", { name: "Use the authenticator app instead" }).click();
  const lockout = p.getByText(/Too many tries\. Please wait about \d+ minutes?\./);
  for (let i = 0; i < 8 && !(await lockout.isVisible()); i++) {
    await p.getByLabel(lbl("6-digit code")).fill(String(111111 + i));
    await expect(p.getByText(/That code is not right|Too many tries/).first()).toBeVisible();
  }
  await expect(lockout).toBeVisible();
  await expect(p.getByText(/You can try again in \d+:\d\d\./)).toBeVisible();
  await expect(p.getByLabel(lbl("6-digit code"))).toBeDisabled();
  await context.close();
});
