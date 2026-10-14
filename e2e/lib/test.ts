import { AxeBuilder } from "@axe-core/playwright";
import { test as base, expect, type Page } from "@playwright/test";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";

import { Api, type Account } from "./api";

export { expect };

export interface Shared {
  owner: Account;
  second: Account;
  business: string;
}
export const shared = (): Shared => JSON.parse(readFileSync(".state/shared.json", "utf8"));

/** Console errors and server failures are test failures: every journey also checks "nothing broke quietly". */
const IGNORED_CONSOLE = [/Failed to load resource/];   // 4xx answers are expected in places (wrong password); 5xx are caught below

/** Watch a page for the things every journey must not see. Returns the live list (and the refused 4xx answers, for the failure report). */
export function guard(page: Page, problems: string[], refused: string[]) {
  page.on("pageerror", (e) => problems.push(`uncaught: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORED_CONSOLE.some((r) => r.test(m.text()))) problems.push(`console.error: ${m.text()} @ ${page.url()}`);
  });
  page.on("response", async (r) => {
    if (r.url().includes("/api/")) {
      const body = r.request().method() === "GET" && r.status() === 200 ? await r.text().catch(() => "") : "";
      refused.push(`.. ${Date.now() % 100000} ${r.status()} ${r.request().method()} ${r.url().replace(/^https?:\/\/[^/]+\/api\/v1/, "")}${body ? ` (${body.length} bytes)` : ""}`);
    }
    if (r.status() >= 400 && r.status() < 500 && r.url().includes("/api/")) refused.push(`${r.status()} ${r.request().method()} ${r.url().replace(/^https?:\/\/[^/]+/, "")} ${(await r.text().catch(() => "")).slice(0, 200)}`);
    if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.request().method()} ${r.url()}`);
  });
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText ?? "";
    if (!/ABORTED|cancel/i.test(why)) problems.push(`request failed: ${r.url()} ${why}`);
  });
}

export const test = base.extend<{ problems: string[]; refused: string[]; second: (account: Account) => Promise<Page> }>({
  refused: async ({}, use) => { await use([]); },
  problems: [async ({ page, refused }, use, info) => {
    const problems: string[] = [];
    guard(page, problems, refused);
    await use(problems);
    if (info.status !== info.expectedStatus && refused.length) console.log(`4xx answers during "${info.title}":\n  ${refused.slice(-25).join("\n  ")}`);
    mkdirSync("screenshots", { recursive: true });
    const name = info.file.split("/").pop()?.replace(".spec.ts", "") ?? "journey";
    if (!page.isClosed()) await page.screenshot({ path: `screenshots/${name}.png`, fullPage: false }).catch(() => undefined);
    expect(problems, "console errors, uncaught exceptions or 5xx answers during the journey").toEqual([]);
  }, { auto: true }],
  /** A second signed-in person in their own browser window ("someone else" for approvals). */
  second: async ({ browser, problems, refused }, use) => {
    const contexts: { close(): Promise<void> }[] = [];
    await use(async (account) => {
      const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
      contexts.push(context);
      const other = await context.newPage();
      guard(other, problems, refused);
      await signIn(other, account);
      return other;
    });
    for (const c of contexts) await c.close();
  },
});

export async function signIn(page: Page, account: Account) {
  await page.goto("/");
  await page.getByLabel("Email or phone").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

export const signedInApi = (account: Account) => new Api(account).signIn();

/** Serious and critical accessibility violations on the current page are recorded in test-results/a11y.txt and fail the
 *  test unless the rule is on the known list (rules still to fix). */
const KNOWN_A11Y: string[] = [];
export async function checkAccessibility(page: Page, label: string) {
  await page.waitForLoadState("networkidle");
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  mkdirSync("test-results", { recursive: true });
  for (const v of bad) appendFileSync("test-results/a11y.txt", `${label}\t${v.id}\t${v.impact}\t${v.nodes.length} nodes\t${v.nodes[0]?.target.join(" ")}\t${(v.nodes[0]?.any[0]?.message ?? "").slice(0, 160)}\t${(v.nodes[0]?.html ?? "").slice(0, 160)}\n`);
  const fresh = bad.filter((v) => !KNOWN_A11Y.includes(v.id));
  expect(fresh.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes[0]?.target.join(" ")}`), `accessibility on ${label}`).toEqual([]);
}
