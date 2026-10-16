import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const ALL = ["platform.view", "platform.subscribers", "platform.plans", "platform.billing", "platform.licences", "platform.units", "platform.content", "platform.ai", "platform.settings", "platform.operators"];
const me = (role = "superadmin", permissions = ALL) => ({
  name: "Sam Admin", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp", mfa_off_in_production: false, must_change_password: false, role, permissions,
});
const setup = (done: Record<string, boolean>, risks: unknown[] = []) => ({
  environment: "production", mode: "saas", risks,
  items: ["email", "registration", "ai", "payments", "plans", "website", "licence"].map((key) => ({
    key, done: done[key] ?? false, to: `/operator/${key}`, needs: key === "plans" ? "platform.plans" : "platform.settings", optional: key === "licence", detail: key === "registration" ? "invite" : null, feature: key === "website" ? "website" : null,
  })),
});
const dashboard = () => ({
  generated_at: "2026-10-15T10:00:00Z", period_days: 30,
  mrr: [{ currency: "KES", mrr: "50000.00", arr: "600000.00", subscribers: 5 }, { currency: "USD", mrr: "120.00", arr: "1440.00", subscribers: 2 }],
  new_subscribers: 4, churned: 1, trials: { in_progress: 3, ending_soon: 1, converted: 2, lapsed: 1, conversion_percent: 67 },
  past_due: [{ currency: "KES", invoices: 2, owed: "3000.00" }], by_status: { active: 6, trialing: 3 }, by_plan: { pro: 7 }, by_edition: { retail: 7 }, by_country: { KE: 7 },
  unmanaged: 1, usage_hot_spots: [], upcoming_renewals: [], failed_jobs: [], pending_requests: 2, draft_invoices: 1, mode: "saas",
});
const system = () => ({
  ready: true, problems: 0, queues_known: true, failed_jobs: 0, jobs_due: 0, jobs_oldest_due_seconds: 5, outbox_pending: 0, outbox_stuck: 0, backup_reported: true, backup_age_hours: 3,
  businesses_behind: 0, businesses_unreadable: 0, mail_configured: true, mail_working: true, ai_has_provider: true, ai_cap_usd: "50.00", ai_spend_usd: "12.50", ai_cap_reached: false,
});
const series = (points: string[]) => ({ metric: "revenue", range: "12m", buckets: points.map((_, i) => `2026-${String(i + 1).padStart(2, "0")}-01`), series: [{ currency: "KES", points }] });

let calls: { path: string; search: string }[] = [];
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
    calls.push({ path: url.pathname, search: url.search });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname}{l.search}</p>;
}

async function open(path = "/operator/dashboard", role = "superadmin", permissions = ALL) {
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json(me(role, permissions));
  const { default: OperatorApp } = await import("./OperatorApp");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/operator/*" element={<><OperatorApp /><Where /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the search box", () => {
  beforeEach(() => {
    handlers["GET /api/v1/operator/units"] = () => json([]);
  });

  it("opens with Ctrl+K, finds screens on this device and jumps with Enter", async () => {
    await open("/operator/units");
    await screen.findByRole("navigation", { name: "Console areas" });
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const box = await screen.findByRole("combobox", { name: "Search the console" });
    fireEvent.change(box, { target: { value: "audit" } });
    await waitFor(() => expect(screen.getByRole("option", { name: /Audit trail/ })).toBeTruthy());
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/operator/audit"));
    expect(screen.queryByRole("dialog", { name: "Search the console" })).toBeNull();
  });

  it("asks the server only after two characters and lists what it finds, grouped", async () => {
    handlers["GET /api/v1/operator/search"] = () => json([{ kind: "subscriber", id: "shop-a", title: "Shop A", subtitle: "shop-a · active", to: "/operator/subscribers/shop-a" }]);
    await open("/operator/units");
    await screen.findByRole("navigation", { name: "Console areas" });
    fireEvent.keyDown(document, { key: "/" });
    const box = await screen.findByRole("combobox", { name: "Search the console" });
    fireEvent.change(box, { target: { value: "s" } });
    await new Promise((r) => setTimeout(r, 350));
    expect(calls.some((c) => c.path.endsWith("/search"))).toBe(false);
    fireEvent.change(box, { target: { value: "shop" } });
    const hit = await screen.findByRole("option", { name: /Shop A/ }, { timeout: 2000 });
    expect(within(screen.getByRole("group", { name: "Subscribers" })).getByText("Shop A")).toBeTruthy();
    fireEvent.click(hit);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/operator/subscribers/shop-a"));
  });

  it("does not offer screens the role cannot open", async () => {
    await open("/operator/units", "readonly", ["platform.view"]);
    await screen.findByRole("navigation", { name: "Console areas" });
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    fireEvent.change(await screen.findByRole("combobox", { name: "Search the console" }), { target: { value: "audit" } });
    expect(await screen.findByText(/Nothing found for "audit"/)).toBeTruthy();
  });
});

describe("the alerts bell", () => {
  beforeEach(() => {
    handlers["GET /api/v1/operator/units"] = () => json([]);
  });

  it("shows how many things need attention and links each to where it is dealt with", async () => {
    handlers["GET /api/v1/operator/alerts"] = () => json({ total: 2, worst: "bad", items: [
      { key: "payments_attention", severity: "bad", count: 3, to: "/operator/payment-attempts", needs: "platform.billing" },
      { key: "trials_ending", severity: "info", count: 1, to: "/operator/subscribers?flag=trial_ending", needs: "platform.subscribers" },
    ] });
    await open("/operator/units");
    const bell = await screen.findByRole("button", { name: "2 things need attention" });
    fireEvent.click(bell);
    const link = await screen.findByRole("link", { name: /Payments to look at: 3/ });
    expect(link.getAttribute("href")).toBe("/operator/payment-attempts");
    expect(screen.getByRole("link", { name: /Trials ending soon: 1/ })).toBeTruthy();
    fireEvent.click(link);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/operator/payment-attempts"));
  });

  it("says when nothing needs attention, and offers a retry when the read fails", async () => {
    handlers["GET /api/v1/operator/alerts"] = () => json({ total: 0, worst: null, items: [] });
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: "Needs attention" }));
    expect(await screen.findByText("Nothing needs you right now.")).toBeTruthy();
    cleanup();
    handlers["GET /api/v1/operator/alerts"] = () => json({ error: "boom", message: "busy" }, 500);
    vi.resetModules();
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: "Needs attention" }));
    expect(await screen.findByText("The alerts could not be read.")).toBeTruthy();
  });

  it("puts a count beside the menu entry an alert belongs to", async () => {
    handlers["GET /api/v1/operator/alerts"] = () => json({ total: 1, worst: "warn", items: [{ key: "pending_requests", severity: "warn", count: 4, to: "/operator/billing/requests", needs: "platform.billing" }] });
    await open("/operator/units");
    const nav = await screen.findByRole("navigation", { name: "Console areas" });
    await waitFor(() => expect(within(within(nav).getByRole("link", { name: /Plan requests/ })).getByLabelText("4 waiting")).toBeTruthy());
  });
});

describe("the frame", () => {
  beforeEach(() => {
    handlers["GET /api/v1/operator/units"] = () => json([]);
  });

  it("shows the environment, the account menu and a banner for risky settings that can be hidden", async () => {
    handlers["GET /api/v1/operator/setup"] = () => json(setup({}, [{ key: "mail_not_configured", severity: "warn", to: "/operator/email", needs: "platform.settings" }]));
    await open("/operator/units");
    expect(await screen.findByText("Production")).toBeTruthy();
    expect(await screen.findByText("Email is not set up")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide for now" }));
    expect(screen.queryByText("Email is not set up")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    expect(await screen.findByRole("menuitem", { name: "My account" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Change password" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeTruthy();
  });

  it("shows breadcrumbs for the open screen and a record", async () => {
    await open("/operator/units");
    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByText("Platform")).toBeTruthy();
    expect(within(crumbs).getByText("Add-ons & units")).toBeTruthy();
  });

  it("collapses the menu to icons", async () => {
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: "Collapse the menu" }));
    expect(await screen.findByRole("button", { name: "Expand the menu" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add-ons & units" }).getAttribute("title")).toBe("Add-ons & units");
  });

  it("opens the menu as a drawer from the Menu button", async () => {
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: "Menu" }));
    const drawer = await screen.findByRole("dialog", { name: "Console areas" });
    fireEvent.click(within(drawer).getByRole("link", { name: "Health" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/operator/health"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Console areas" })).toBeNull());
  });

  it("keeps the old billing tab addresses working", async () => {
    handlers["GET /api/v1/operator/payment-gateways"] = () => json([]);
    await open("/operator/billing/payment-methods");
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/operator/payment-methods"));
    expect(await screen.findByRole("heading", { name: "Payment methods" })).toBeTruthy();
  });
});

describe("the dashboard", () => {
  beforeEach(() => {
    handlers["GET /api/v1/operator/dashboard"] = () => json(dashboard());
    handlers["GET /api/v1/operator/dashboard/system"] = () => json(system());
    handlers["GET /api/v1/operator/dashboard/series"] = () => json(series(["0", "100.00", "250.50"]));
    handlers["GET /api/v1/operator/dashboard/feed"] = () => json({ payments: [], signups: [] });
    handlers["GET /api/v1/operator/subscribers"] = () => json({ total: 0, items: [] });
    handlers["GET /api/v1/operator/audit"] = () => json({ total: 0, items: [] });
    handlers["GET /api/v1/operator/setup"] = () => json(setup({ email: true, registration: true }));
  });

  it("shows the headline figures per currency, a trend chart with a readable name and the health tiles", async () => {
    await open();
    expect(await screen.findByText(/Monthly recurring \(KES\)/)).toBeTruthy();
    expect(screen.getByText(/Monthly recurring \(USD\)/)).toBeTruthy();
    expect(screen.getByText("Active subscribers")).toBeTruthy();
    expect(await screen.findByRole("img", { name: /^Revenue KES\. / })).toBeTruthy();
    expect(await screen.findByText("API ready")).toBeTruthy();
    expect(screen.getByText("$12.50 / $50.00")).toBeTruthy();
    expect(screen.getByText("No payments yet")).toBeTruthy();
  });

  it("asks the series endpoint for the metric and period chosen", async () => {
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "12 weeks" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/dashboard/series") && c.search.includes("range=12w"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/dashboard/series") && c.search.includes("metric=signups"))).toBe(true));
  });

  it("lists the setup steps from real state, and the first undone one is the start", async () => {
    await open();
    expect(await screen.findByText("3. Add AI provider keys")).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: /Where do I find/ }).getAttribute("aria-valuenow")).toBe("2");
    expect(screen.getByText("2 of 6 done")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Start here/ }).getAttribute("href")).toBe("/operator/ai");
    expect(screen.getByText(/Now: .+\./)).toBeTruthy();
  });

  it("keeps working when one block fails, and the failed block can be retried", async () => {
    handlers["GET /api/v1/operator/dashboard/system"] = () => json({ error: "boom", message: "Health is busy" }, 500);
    await open();
    expect(await screen.findByText("Health is busy")).toBeTruthy();
    expect(screen.getByText(/Monthly recurring \(KES\)/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Try again/ }).length).toBeGreaterThan(0);
  });

  it("hides the setup checklist when everything required is done, and the activity feed from roles without the trail", async () => {
    handlers["GET /api/v1/operator/setup"] = () => json(setup({ email: true, registration: true, ai: true, payments: true, plans: true, website: true }));
    await open("/operator/dashboard", "billing", ["platform.view", "platform.billing", "platform.plans", "platform.subscribers", "platform.licences"]);
    await screen.findByText(/Monthly recurring \(KES\)/);
    expect(screen.queryByText("Where do I find ...? Setup checklist")).toBeNull();
    expect(screen.queryByText("Recent operator activity")).toBeNull();
    expect(screen.getByRole("link", { name: /Create plan/ }).getAttribute("href")).toBe("/operator/plans/new");
    expect(screen.queryByRole("link", { name: /Invite operator/ })).toBeNull();
  });
});
