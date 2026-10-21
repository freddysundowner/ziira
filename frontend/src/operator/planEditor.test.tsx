import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const me = (permissions: string[]) => ({
  name: "Sam", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp", mfa_off_in_production: false,
  must_change_password: false, role: "billing", permissions,
});
const unit = (name: string, title: string, over: Record<string, unknown> = {}) => ({
  name, title, kind: "module", category: "", source: "built in", description: `${title} does its job.`, version_on_disk: "1.0.0", version_installed: "1.0.0", installed_at: null,
  status: "installed", requires: [], required_by: [], businesses_enabled: 0, businesses_holding: 0, businesses_behind: 0, ...over,
});
const UNITS = [
  unit("kernel", "Kernel", { kind: "kernel" }), unit("products", "Products", { requires: ["kernel"] }), unit("jobs", "Jobs", { requires: ["kernel", "products"] }),
  unit("inventory", "Stock", { requires: ["kernel", "products"] }), unit("pack_x", "Salon pack", { kind: "plugin", requires: ["kernel"] }),
];
const plan = (over: Record<string, unknown> = {}) => ({
  id: "p1", code: "pro", name: "Pro", description: "", edition: "retail", units: ["jobs"], addon_units: [], max_users: null, max_branches: null, max_companies: null, limits: {}, highlights: [],
  trial_days: 14, intervals: ["month"], sort_order: 100, is_public: true, status: "active", subscribers: 0, updated_at: "2030-01-01T00:00:00Z",
  units_included: ["jobs", "products"], prices: [], current_prices: [], ...over,
});
const sales = (units: Record<string, unknown>[] = []) => ({ currencies: ["KES"], units });

let calls: { method: string; path: string; body?: Record<string, unknown> }[] = [];
let handlers: Record<string, Handler> = {};

beforeEach(() => {
  calls = [];
  handlers = {
    "GET /api/v1/operator/plans/pro": () => json(plan()),
    "GET /api/v1/operator/units": () => json(UNITS),
    "GET /api/v1/operator/unit-sales": () => json(sales([{ unit: "inventory", offered: true, prices: { KES: "3000.00" }, tax_inclusive: false }])),
    "GET /api/v1/editions": () => json([{ id: "retail", title: "Retail", pitch: "", units: ["inventory"], plugin_categories: [], menu_groups: [], landing: "", checklist: [], sample_data: [] }]),
    "PUT /api/v1/operator/unit-sales/pack_x": () => json({ unit: "pack_x", offered: true, prices: { KES: "1500" }, tax_inclusive: false }),
    "PATCH /api/v1/operator/plans/pro": () => json(plan({ name: "Pro" })),
  };
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
    calls.push({ method: input.method, path: url.pathname, body });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(permissions = ["platform.view", "platform.plans"]) {
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json(me(permissions));
  const { default: OperatorApp } = await import("./OperatorApp");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/operator/plans/edit/pro"]}>
        <Routes><Route path="/operator/*" element={<OperatorApp />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.findByRole("heading", { name: "Pro" });
}
const row = (name: string) => document.querySelector(`[data-unit="${name}"]`) as HTMLElement;

describe("the plan editor's one list of units", () => {
  it("ticks what the plan includes, says how the rest is sold, and counts both", async () => {
    await open();
    await screen.findByText("Stock");
    expect(within(row("jobs")).getByRole("checkbox").hasAttribute("checked") || (within(row("jobs")).getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
    expect((within(row("products")).getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
    expect((within(row("inventory")).getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
    expect(within(row("inventory")).getByText(/Sold separately for .*3,000.* once/)).toBeTruthy();
    expect(within(row("pack_x")).getByText("Not for sale")).toBeTruthy();
    expect(within(row("jobs")).getByText("Included")).toBeTruthy();
    expect(screen.getByText(/\d+ included, \d+ for sale/).textContent).toBe("2 included, 1 for sale");
    expect(screen.queryByText("Extra units")).toBeNull();
    expect(screen.queryByText("Units sold as add-ons")).toBeNull();
    expect(screen.queryByLabelText("Edition")).toBeNull();                         // the edition is only a helper under Advanced
    expect(screen.getByRole("heading", { name: /^Modules/ }).textContent).toContain("(3)");
    expect(screen.getByRole("heading", { name: /^Plugins and packs/ }).textContent).toContain("(1)");
  });

  it("locks a unit another ticked unit needs, and explains why", async () => {
    await open();
    await screen.findByText("Stock");
    const products = within(row("products")).getByRole("checkbox") as HTMLInputElement;
    expect(products.disabled).toBe(true);
    expect(within(row("products")).getByText("Included, needed by Jobs")).toBeTruthy();
    fireEvent.click(within(row("jobs")).getByRole("checkbox"));                    // untick Jobs: Products is free again
    expect((within(row("products")).getByRole("checkbox") as HTMLInputElement).disabled).toBe(false);
  });

  it("finds units by search", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.change(screen.getByLabelText("Search modules and plugins"), { target: { value: "salon" } });
    expect(row("pack_x")).toBeTruthy();
    expect(row("jobs")).toBeNull();
  });
});

describe("selling a unit that is not ticked", () => {
  it("offers it for sale with a one-time price and saves only the price list", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.click(within(row("pack_x")).getByRole("button", { name: "Offer for sale" }));
    fireEvent.click(screen.getByRole("switch", { name: "Offer Salon pack for sale" }));
    fireEvent.change(screen.getByLabelText("Salon pack KES"), { target: { value: "1500" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe("/api/v1/operator/unit-sales/pack_x");
    expect(put.body).toEqual({ offered: true, prices: { KES: "1500" }, tax_inclusive: false });
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);                    // the plan itself did not change
  });

  it("will not save an offer with no price", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.click(within(row("pack_x")).getByRole("button", { name: "Offer for sale" }));
    fireEvent.click(screen.getByRole("switch", { name: "Offer Salon pack for sale" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Set a price, or switch off Offer for sale.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PUT" || c.method === "PATCH")).toBe(false);
  });

  it("saves the plan with every needed unit, no add-on list and no edition when a unit is ticked", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.click(within(row("inventory")).getByRole("checkbox"));
    expect(within(row("inventory")).getByText("Included")).toBeTruthy();
    expect(screen.getByText(/\d+ included, \d+ for sale/).textContent).toBe("3 included, 0 for sale");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toMatchObject({ units: ["inventory", "jobs", "products"], addon_units: [], edition: null });
  });

  it("pre-ticks an edition's units from Advanced", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.change(screen.getByLabelText("Start from an edition"), { target: { value: "retail" } });
    fireEvent.click(screen.getByRole("button", { name: "Tick its units" }));
    expect((within(row("inventory")).getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });

  it("refuses a plan with nothing ticked", async () => {
    await open();
    await screen.findByText("Stock");
    fireEvent.click(within(row("jobs")).getByRole("checkbox"));                    // Products came only with Jobs, so nothing is left
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Tick at least one module or plugin.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("is read-only for a role that cannot change plans", async () => {
    await open(["platform.view"]);
    await screen.findByText("Stock");
    expect((within(row("inventory")).getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(within(row("pack_x")).queryByRole("button", { name: "Offer for sale" })).toBeNull();
  });
});
