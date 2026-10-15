import { API_URL } from "../lib/api";
import { code, seedCatalogue } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";
import { drawer, lbl } from "../lib/ui";
import { totp } from "../lib/totp";

// J16: the owner gives support access and takes it back; a member of Ziira staff (created by `ziira operator create` in
// run.sh, signing in with a code from its second factor) opens a session while a grant is active, the banner appears, and
// the session stops working when the grant is ended. Then a privacy request: recorded, searched, exported as a JSON file.

async function operatorToken(): Promise<string> {
  const email = process.env.E2E_OPERATOR_EMAIL!, password = process.env.E2E_OPERATOR_PASSWORD!, secret = process.env.E2E_OPERATOR_SECRET!;
  expect(secret, "run.sh creates the operator and passes its secret").toBeTruthy();
  const post = async (path: string, body: unknown, token?: string) => {
    const res = await fetch(`${API_URL}/api/v1/operator${path}`, { method: "POST", headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body) });
    return { status: res.status, body: (await res.json().catch(() => ({}))) as any };
  };
  const first = await post("/sign-in", { email, password });
  expect(first.status).toBe(200);
  const second = await post("/mfa/verify", { challenge: first.body.challenge, code: totp(secret) });
  expect(second.status, JSON.stringify(second.body)).toBe(200);
  return second.body.access_token;
}

test("J16 support access and privacy requests", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await signIn(page, s.owner);

  // --- give support access, then end it
  await page.goto("/admin/support");
  await page.getByRole("button", { name: "Give support access" }).first().click();
  await drawer(page).getByLabel(/^Why does support need access/).fill("Stock count does not add up");
  await drawer(page).getByRole("button", { name: "Give access" }).click();
  await expect(page.getByText("Support access given.")).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: "Stock count does not add up" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Active")).toBeVisible();
  await checkAccessibility(page, "support access");
  await row.getByRole("button", { name: "End access" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End access" }).click();
  await expect(page.getByText("Support access ended.")).toBeVisible();
  await expect(row.getByText("Revoked")).toBeVisible();

  // --- a member of staff cannot open the business without a grant; with one, they can, read-only
  const token = await operatorToken();
  const operator = (path: string, init: RequestInit = {}) => fetch(`${API_URL}/api/v1/operator${path}`, { ...init, headers: { authorization: `Bearer ${token}`, "content-type": "application/json" } });
  const businesses = (await (await operator("/businesses")).json()) as { code: string; name: string }[];
  const mine = businesses.find((b) => b.name === s.business);
  expect(mine, "the shared business is in the operator's list").toBeTruthy();
  expect((await operator(`/businesses/${mine!.code}/support-session`, { method: "POST", body: "{}" })).status).toBe(403);

  await page.getByRole("button", { name: "Give support access" }).first().click();
  await drawer(page).getByLabel(/^Why does support need access/).fill("Look at the till variance");
  await drawer(page).getByRole("button", { name: "4 hours" }).click();
  await drawer(page).getByRole("button", { name: "Give access" }).click();
  await expect(page.getByText("Support access given.")).toBeVisible();

  const opened = await operator(`/businesses/${mine!.code}/support-session`, { method: "POST", body: "{}" });
  expect(opened.status).toBe(201);
  const session = (await opened.json()) as { access_token: string; level: string };
  expect(session.level).toBe("read");
  const asStaff = (path: string, method = "GET") => fetch(`${API_URL}/api/v1${path}`, { method, headers: { authorization: `Bearer ${session.access_token}`, "content-type": "application/json" }, body: method === "GET" ? undefined : "{}" });
  const me = (await (await asStaff("/auth/me")).json()) as any;
  expect(me.support_session?.operator).toContain("E2E Operator");
  expect((await asStaff("/products/products")).status).toBe(200);              // looking is allowed
  expect((await asStaff("/products/uoms", "POST")).status).toBe(403);          // read-only: changing is not

  // --- the business sees it: the banner, the session on the grant, and what the staff member did
  await page.reload();
  const banner = page.getByRole("alert").filter({ hasText: "Ziira support is viewing your business" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("E2E Operator");
  await expect(banner).toContainText("read-only");
  await page.goto("/admin/support");
  await expect(page.getByText(/E2E Operator: \d+ actions/)).toBeVisible();
  await page.getByRole("tab", { name: "What staff did" }).click();
  await expect(page.getByText("Entered your business").first()).toBeVisible();
  await expect(page.getByText("E2E Operator").first()).toBeVisible();
  await checkAccessibility(page, "support log");

  // --- ending the grant ends the session at once and the banner goes
  await page.getByRole("tab", { name: "Access given" }).click();
  await page.getByRole("row").filter({ hasText: "Look at the till variance" }).getByRole("button", { name: "End access" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End access" }).click();
  await expect(page.getByText("Support access ended.")).toBeVisible();
  expect([401, 403]).toContain((await asStaff("/products/products")).status);
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "Ziira support is viewing" })).toHaveCount(0);

  // --- a privacy request: record it, find the person, take the export as a file
  const tag = code(5).toLowerCase();
  const cat = await seedCatalogue(api, []);
  const person = { name: `Wanjiru ${tag}`, email: `wanjiru.${tag}@privacy.test` };
  await api.post("/crm/customers", { company_id: cat.companyId, name: person.name, email: person.email });
  await page.goto("/admin/privacy");
  await page.getByRole("button", { name: "New request" }).first().click();
  const modal = page.getByRole("dialog");
  await modal.getByLabel(lbl("Who it is about")).fill(person.email);
  await modal.getByLabel(/^Notes/).fill("Checked by phone call back");
  await modal.getByRole("button", { name: "Record request" }).click();
  await page.waitForURL(/\/admin\/privacy\/[0-9a-f-]+$/);
  await expect(page.getByText(/^Request .* recorded\.$/)).toBeVisible();
  await page.getByRole("button", { name: "Run the search" }).click();
  await expect(page.getByText(/Search finished: \d+ records found\./)).toBeVisible();
  await expect(page.getByText(person.name).first()).toBeVisible();
  await checkAccessibility(page, "privacy request");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download the data" }).click()]);
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  const { readFile } = await import("node:fs/promises");
  const exported = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(JSON.stringify(exported)).toContain(person.name);
  await expect(page.getByText("Export downloaded.")).toBeVisible();

  // --- and it is in the list
  await page.goto("/admin/privacy");
  await expect(page.getByRole("row").filter({ hasText: /DSR|PRIV|REQ/i }).first()).toBeVisible();
  await checkAccessibility(page, "privacy requests");
});
