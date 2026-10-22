import { Api, unique } from "../lib/api";
import { checkAccessibility, expect, signIn, signOut, test } from "../lib/test";

// J1: a new owner registers through the three-step form (need, business, account), lands signed in on Home with the
// "confirm your email" banner, confirms the address with the emailed link, signs out and back in, meets the wrong-password
// message, and resets a forgotten password.
test("J1 register, sign in, wrong password, forgot password", async ({ page }) => {
  const tag = unique("j1");
  const account = { email: `owner@${tag}.test`, password: "first-pass-123", name: "Jo Founder" };

  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "What do you need?" })).toBeVisible();
  await checkAccessibility(page, "register step 1");
  await page.getByRole("button", { name: "Continue" }).click();

  // step 2: the business (country starts on the platform's default; pick another to check the form follows it)
  await page.getByLabel(/Business name/).fill(`J1 ${tag} Stores`);
  await page.getByRole("combobox", { name: /country/i }).click();
  await page.getByRole("textbox", { name: "Search", exact: true }).fill("United Kingdom");
  await page.getByRole("option", { name: /United Kingdom/ }).first().click();
  await expect(page.getByRole("combobox", { name: /country/i })).toContainText("United Kingdom");
  await page.getByRole("button", { name: "Continue" }).click();

  // step 3: the account (the owner's name is taken from the email address)
  await page.getByLabel(/Work email/).fill(account.email);
  await page.getByLabel(/^Password/).fill(account.password);
  await page.getByLabel(/Type the password again/).fill(account.password);
  await page.getByRole("checkbox").check();
  const registered = page.waitForResponse((r) => r.url().endsWith("/api/v1/register") && r.request().method() === "POST");
  await expect(page.getByRole("button", { name: "Create my business" })).toBeEnabled();      // after the server's password check
  await page.getByRole("button", { name: "Create my business" }).click();
  const confirmToken = ((await (await registered).json()) as { dev_confirm_token?: string }).dev_confirm_token;
  expect(confirmToken, "the development confirmation token").toBeTruthy();

  // instant entry: signed in on Home with the "confirm your email" banner, no "check your email" page
  await expect(page.getByRole("button", { name: "Account" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(`J1 ${tag} Stores`).first()).toBeVisible();
  await expect(page.getByText(/Please confirm your email address/)).toBeVisible();
  await checkAccessibility(page, "home after registration");

  // the emailed link confirms the address (it works signed in or not) and the banner goes away
  await page.goto(`/confirm-email?token=${encodeURIComponent(confirmToken!)}`);
  await expect(page.getByRole("heading", { name: "Your email address is confirmed" })).toBeVisible();
  await page.getByRole("link", { name: "Continue to Ziira" }).click();
  await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
  await expect(page.getByText(/Please confirm your email address/)).toBeHidden();

  await signOut(page);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  // wrong password: a clear message, still on the sign-in screen
  await page.getByLabel("Email or phone").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Wrong login or password")).toBeVisible();

  await signIn(page, account);
  await signOut(page);

  // forgot password: the development link carries the reset token
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.getByLabel("Email or phone").fill(account.email);
  await page.getByRole("button", { name: "Send the link" }).click();
  await page.getByRole("link", { name: "Open the reset link" }).click();
  const fresh = "second-pass-456-xyz";
  await page.getByLabel("New password").fill(fresh);
  await page.getByLabel("Type it again").fill("different");
  await expect(page.getByText("The two passwords are different.")).toBeVisible();
  await page.getByLabel("Type it again").fill(fresh);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();

  await page.getByRole("link", { name: "Go to sign in" }).click();
  await page.getByLabel("Email or phone").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Wrong login or password")).toBeVisible();   // the old one no longer works
  await signIn(page, { ...account, password: fresh });
  expect(await new Api({ ...account, password: fresh }).signIn()).toBeTruthy();
});
