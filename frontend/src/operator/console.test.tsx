import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const ALL = ["platform.view", "platform.subscribers", "platform.plans", "platform.billing", "platform.licences", "platform.units", "platform.content", "platform.operators"];
const me = (role: string, permissions: string[]) => ({
  name: "Sam", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp", mfa_off_in_production: false, must_change_password: false, role, permissions,
});

const row = (over: Record<string, unknown> = {}) => ({
  id: "t1", code: "shop-a", name: "Shop A", tenant_status: "active", created_at: "2026-01-01T00:00:00Z", edition: "retail", country: "KE", status: "active",
  plan_code: "pro", plan_name: "Pro", interval: "month", currency: "KES", unit_amount: "1000.00", period_end: "2026-11-01T00:00:00Z", trial_end: null,
  cancel_at_period_end: false, is_comp: false, tags: [], users: 3, max_users: 5, branches: 1, max_branches: 2, last_activity: null, outstanding: {}, ...over,
});
const detail = (over: Record<string, unknown> = {}) => ({
  ...row(), owners: [{ name: "Ann", email: "ann@x.test", phone: null }], subscription: {
    id: "s1", plan_code: "pro", plan_name: "Pro", status: "active", interval: "month", currency: "KES", unit_amount: "1000.00", tax_inclusive: false, entitlements: {},
    period_start: "2026-10-01T00:00:00Z", period_end: "2026-11-01T00:00:00Z", trial_end: null, cancel_at_period_end: false, coupon_periods_left: null,
    pending_plan_id: null, pending_interval: null, is_comp: false, notes: "", tags: [], status_reason: null, status_changed_at: "2026-10-01T00:00:00Z", created_at: "2026-01-01T00:00:00Z",
  }, timeline: [], invoices: [], payments: [], requests: [], usage: { users: 3, branches: 1, companies: 1, storage_bytes: 2048, failed_jobs: 0 },
  limits: { users: 5, branches: 2, companies: null }, units: [], grants: [], sessions: [], audit_trail: [], deletion: null, access: "full", message: "", ...over,
});

let calls: { method: string; path: string; search: string; body?: unknown }[] = [];
let handlers: Record<string, Handler> = {};

beforeEach(() => {
  calls = [];
  handlers = {};
  vi.resetModules();
  sessionStorage.clear();
  const NativeRequest = Request;
  vi.stubGlobal("Request", class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input, init);
    }
  });
  vi.stubGlobal("fetch", async (input: Request) => {
    const url = new URL(input.url);
    const body = input.method === "GET" ? undefined : await input.clone().json().catch(() => undefined);
    calls.push({ method: input.method, path: url.pathname, search: url.search, body });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(path: string, role = "superadmin", permissions = ALL) {
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json(me(role, permissions));
  const { default: OperatorApp } = await import("./OperatorApp");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/operator/*" element={<OperatorApp />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the menu follows the role", () => {
  it("lands on the dashboard and lists the areas the role may open", async () => {
    handlers["GET /api/v1/operator/dashboard"] = () => json(dashboard());
    await open("/operator", "billing", ["platform.view", "platform.billing", "platform.subscribers", "platform.plans", "platform.licences"]);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Console areas" });
    for (const name of ["Dashboard", "Subscribers", "Licences", "Plans", "Billing", "Platform units", "Platform health"]) expect(await within(nav).findByRole("link", { name })).toBeTruthy();
    expect(within(nav).queryByRole("link", { name: "Operators" })).toBeNull();
  });

  it("shows Operators to a super admin", async () => {
    handlers["GET /api/v1/operator/dashboard"] = () => json(dashboard());
    await open("/operator");
    expect(await within(await screen.findByRole("navigation", { name: "Console areas" })).findByRole("link", { name: "Operators" })).toBeTruthy();
  });

  it("keeps the old businesses address working", async () => {
    handlers["GET /api/v1/operator/subscribers/shop-a"] = () => json(detail());
    await open("/operator/businesses/shop-a");
    expect(await screen.findByRole("heading", { name: "Shop A" })).toBeTruthy();
    expect(calls.some((c) => c.path === "/api/v1/operator/subscribers/shop-a")).toBe(true);
  });
});

function dashboard() {
  return {
    generated_at: "2026-10-15T10:00:00Z", period_days: 30,
    mrr: [{ currency: "KES", mrr: "50000.00", arr: "600000.00", subscribers: 5 }, { currency: "USD", mrr: "120.00", arr: "1440.00", subscribers: 2 }],
    new_subscribers: 4, churned: 1, trials: { in_progress: 3, ending_soon: 1, converted: 2, lapsed: 1, conversion_percent: 67 },
    past_due: [{ currency: "KES", invoices: 2, owed: "3000.00" }], by_status: { active: 6, trialing: 3 }, by_plan: { pro: 7 }, by_edition: { retail: 7 }, by_country: { KE: 7 },
    unmanaged: 1, usage_hot_spots: [], upcoming_renewals: [], failed_jobs: [], pending_requests: 2, draft_invoices: 1, mode: "saas",
  };
}

describe("the dashboard", () => {
  it("shows each currency on its own and never adds them", async () => {
    handlers["GET /api/v1/operator/dashboard"] = () => json(dashboard());
    await open("/operator/dashboard");
    expect(await screen.findByText(/Monthly recurring \(KES\)/)).toBeTruthy();
    expect(screen.getByText(/Monthly recurring \(USD\)/)).toBeTruthy();
    expect(screen.getAllByText(/Monthly recurring/)).toHaveLength(2);
    expect(screen.getByText(/Each currency is shown on its own/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Plan requests waiting/ }).getAttribute("href")).toBe("/operator/billing/requests");
  });

  it("says so, with a way to retry, when it cannot be read", async () => {
    handlers["GET /api/v1/operator/dashboard"] = () => json({ error: "boom", message: "The database is busy" }, 500);
    await open("/operator/dashboard");
    expect(await screen.findByText("The database is busy")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Try again/ })).toBeTruthy();
  });
});

describe("subscribers", () => {
  it("lists subscribers and asks the server for the flag a chip stands for", async () => {
    handlers["GET /api/v1/operator/plans"] = () => json([]);
    handlers["GET /api/v1/editions"] = () => json([]);
    handlers["GET /api/v1/operator/subscribers"] = () => json({ total: 1, items: [row({ outstanding: { KES: "500.00" } })] });
    await open("/operator/subscribers");
    expect(await screen.findByText("Shop A")).toBeTruthy();
    expect(screen.getByText(/1 subscriber/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Past due" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/operator/subscribers" && c.search.includes("flag=past_due"))).toBe(true));
  });

  it("suspends only with a reason, and asks for a fresh code when the server wants one", async () => {
    let suspends = 0;
    handlers["GET /api/v1/operator/subscribers/shop-a"] = () => json(detail());
    handlers["POST /api/v1/operator/subscribers/shop-a/suspend"] = () => {
      suspends += 1;
      return suspends === 1 ? json({ error: "mfa_step_up_required", message: "Confirm with a fresh code" }, 403) : json(detail({ status: "suspended" }));
    };
    handlers["POST /api/v1/operator/confirm"] = () => json({ mfa_verified_at: new Date().toISOString(), valid_minutes: 10 });
    await open("/operator/subscribers/shop-a");
    fireEvent.click(await screen.findByRole("button", { name: /Actions/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Suspend" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Suspend" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText(/Why/), { target: { value: "Unpaid for ninety days" } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    fireEvent.change(await screen.findByLabelText("Authenticator code"), { target: { value: "123456" } });
    await waitFor(() => expect(suspends).toBe(2));
    expect(calls.find((c) => c.path.endsWith("/suspend"))?.body).toEqual({ reason: "Unpaid for ninety days" });
  });

  it("offers a business without a subscription only to start one", async () => {
    handlers["GET /api/v1/operator/subscribers/shop-a"] = () => json(detail({ status: "unmanaged", subscription: null, plan_code: null, plan_name: null }));
    await open("/operator/subscribers/shop-a");
    expect(await screen.findByRole("button", { name: "Start subscription" })).toBeTruthy();
    expect(screen.getByText(/has no subscription/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Actions/ }));
    expect(screen.queryByRole("menuitem", { name: "Suspend" })).toBeNull();
  });

  it("hides the actions a support role may not use", async () => {
    handlers["GET /api/v1/operator/subscribers/shop-a"] = () => json(detail());
    await open("/operator/subscribers/shop-a", "support", ["platform.view", "platform.subscribers"]);
    fireEvent.click(await screen.findByRole("button", { name: /Actions/ }));
    expect(await screen.findByRole("menuitem", { name: "Suspend" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Change plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change plan" })).toBeNull();
  });
});

describe("operators", () => {
  const operators = [
    { id: "o1", name: "Sam", email: "sam@x.test", status: "active", role: "superadmin", created_at: "2026-01-01T00:00:00Z", last_sign_in_at: null, mfa_enrolled: true, open_sessions: 1 },
    { id: "o2", name: "Bea", email: "bea@x.test", status: "active", role: "billing", created_at: "2026-01-01T00:00:00Z", last_sign_in_at: null, mfa_enrolled: true, open_sessions: 0 },
  ];

  it("shows roles, offers no actions on your own row, and shows a new secret once", async () => {
    handlers["GET /api/v1/operator/operators"] = () => json(operators);
    handlers["GET /api/v1/operator/actions"] = () => json([]);
    handlers["GET /api/v1/operator/roles"] = () => json({ roles: [], permissions: {} });
    handlers["POST /api/v1/operator/operators/o2/reset-mfa"] = () => json({ id: "o2", mfa_secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/Ziira:bea?secret=JBSWY3DPEHPK3PXP" });
    await open("/operator/operators");
    expect(await screen.findByText("Bea")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Actions for Sam" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Bea" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reset second factor" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Reset second factor" }));
    expect((await screen.findByTestId("mfa-secret")).textContent).toBe("JBSWY3DPEHPK3PXP");
  });

  it("takes an empty password or one of at least 12 characters", async () => {
    handlers["GET /api/v1/operator/operators"] = () => json(operators);
    handlers["GET /api/v1/operator/actions"] = () => json([]);
    handlers["GET /api/v1/operator/roles"] = () => json({ roles: [], permissions: {} });
    await open("/operator/operators");
    fireEvent.click(await screen.findByRole("button", { name: /Add operator/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Full name/), { target: { value: "Cy Dee" } });
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: "cy@x.test" } });
    expect((within(dialog).getByRole("button", { name: "Add operator" }) as HTMLButtonElement).disabled).toBe(false);     // empty: a temporary one is made
    fireEvent.change(within(dialog).getByLabelText(/Password/), { target: { value: "short" } });
    expect((within(dialog).getByRole("button", { name: "Add operator" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText(/Password/), { target: { value: "a-long-enough-pass" } });
    expect((within(dialog).getByRole("button", { name: "Add operator" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("billing settings", () => {
  it("saves one setting on its own and shows the server's message beside it", async () => {
    handlers["GET /api/v1/operator/plans"] = () => json([]);
    handlers["GET /api/v1/operator/platform-settings"] = () => json({
      mode: "saas", providers: [], values: {
        vendor: { name: "", address: "", tax_id: "", email: "", phone: "" }, "billing.tax_lines": [], "billing.payment_instructions": "", "billing.invoice_prefix": "INV-",
        "billing.due_days": 14, "billing.renewal_lead_days": 14, "billing.dunning": { reminders: [-7, 0], past_due_after_days: 1, grace_after_days: 7, suspend_after_days: 21, expire_after_days: 90 },
        "billing.proration": { downgrade: "period_end" }, "billing.default_plan_code": "", "billing.retention_days": 90, "billing.cooling_off_days": 7, "billing.notify_emails": "",
      },
    });
    handlers["PUT /api/v1/operator/platform-settings/billing.due_days"] = () => json({ error: "validation_failed", message: "Days until an invoice is due must be from 0 to 365" }, 422);
    await open("/operator/billing/settings");
    const card = (await screen.findByRole("heading", { name: "Days until due" })).closest("section") as HTMLElement;
    const save = within(card).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(card).getByLabelText("Days"), { target: { value: "999" } });
    fireEvent.click(save);
    expect(await within(card).findByText("Days until an invoice is due must be from 0 to 365")).toBeTruthy();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ value: 999 });
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
  });
});
