import { Api, unique } from "../lib/api";
import { checkAccessibility, expect, signIn, signOut, test } from "../lib/test";

// J1: a new owner registers through the two-step form, follows the verification link, signs out and back in,
// meets the wrong-password message, and resets a forgotten password.
test("J1 register, sign in, wrong password, forgot password", async ({ page }) => {
  const tag = unique("j1");
  const account = { email: `owner@${tag}.test`, password: "first-pass-123", name: "Jo Founder" };

  await page.goto("/register");
  await checkAccessibility(page, "register step 1");
  await page.getByLabel("Your name").fill(account.name);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password (at least 8 characters)").fill(account.password);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Business name").fill(`J1 ${tag} Stores`);
  await page.getByLabel("Country").selectOption({ label: "United Kingdom" });
  await expect(page.getByLabel("Currency")).toHaveValue("GBP");
  await expect(page.getByText("calling code +44")).toBeVisible();
  await page.getByRole("button", { name: "Create business" }).click();

  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await page.getByRole("link", { name: "Open the verification link" }).click();
  await expect(page.getByRole("button", { name: "Account" })).toBeVisible();   // landed signed in
  await expect(page.getByText(`J1 ${tag} Stores`).first()).toBeVisible();
  await checkAccessibility(page, "home after registration");

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
