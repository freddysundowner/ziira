import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { writeStored } from "@/sdk/storage";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const unit = (over: Record<string, unknown>) => ({
  name: "x", title: "X", kind: "module", category: "", source: "built in", description: "", version_on_disk: "1.0.0", version_installed: "1.0.0",
  installed_at: null, status: "installed", requires: [], required_by: [], businesses_enabled: 0, businesses_holding: 0, businesses_behind: 0, ...over,
});
const UNITS = [
  unit({ name: "kernel", title: "Kernel", kind: "kernel" }),
  unit({ name: "products", title: "Products", businesses_enabled: 2, businesses_holding: 2, required_by: ["pos"] }),
  unit({ name: "fresh", title: "Fresh plugin", kind: "plugin", status: "available", version_installed: null }),
];

let calls: { method: string; path: string }[] = [];
let handlers: Record<string, Handler> = {};

beforeEach(() => {
  calls = [];
  handlers = {};
  vi.resetModules();
  sessionStorage.clear();
  // The browser resolves "/api/..." against the page; Node's Request needs the full address.
  const NativeRequest = Request;
  vi.stubGlobal("Request", class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input, init);
    }
  });
  vi.stubGlobal("fetch", async (input: Request) => {
    const url = new URL(input.url);
    calls.push({ method: input.method, path: url.pathname });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(path = "/operator/units", signedIn = true) {
  if (signedIn) sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json({ name: "Sam", email: "s@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp", mfa_off_in_production: false, must_change_password: false });
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

describe("the operator console's guard", () => {
  it("shows only the sign-in screen when nobody is signed in, and asks the API for nothing", async () => {
    await open("/operator/units", false);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(calls).toEqual([]);
  });

  it("does not use a business session: a business token in storage opens nothing", async () => {
    writeStored("ziira.refresh", "business-refresh-token");
    await open("/operator/health", false);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(calls).toEqual([]);
    writeStored("ziira.refresh", null);
  });

  it("goes to sign-in when the API ends the session", async () => {
    handlers["GET /api/v1/operator/units"] = () => json({ error: "unauthorized", message: "Session is no longer valid; sign in again" }, 401);
    await open();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(sessionStorage.getItem("ziira.operator.token")).toBeNull();
  });
});

describe("platform units", () => {
  beforeEach(() => {
    handlers["GET /api/v1/operator/units"] = () => json(UNITS);
  });

  it("lists units with the actions their state allows, and no business menu", async () => {
    await open();
    expect(await screen.findByText("Fresh plugin")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    const row = (name: string) => rows.find((r) => r.textContent?.includes(name)) as HTMLElement;
    expect(within(row("Fresh plugin")).getByRole("button", { name: /Install/ })).toBeTruthy();
    expect(within(row("Products")).getByRole("button", { name: /Uninstall/ })).toBeTruthy();
    expect(within(row("Kernel")).queryByRole("button")).toBeNull();                      // the kernel offers nothing
    expect(screen.getByRole("navigation", { name: "Console areas" })).toBeTruthy();
    expect(screen.queryByText("Sales")).toBeNull();
  });

  it("explains why an uninstall is refused and keeps the button off", async () => {
    handlers["GET /api/v1/operator/units/products/plan"] = () => json({
      action: "uninstall", unit: "products", title: "Products", will_install: [], upgrades: [],
      holders: [{ code: "shop-a", name: "Shop A", enabled: true }], dependants: ["pos"],
      blocked: ["Installed units need it: pos.", "These businesses still have it, so it cannot go: Shop A."],
    });
    await open();
    fireEvent.click(await screen.findByRole("button", { name: /Uninstall Products/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Installed units need it: pos/)).toBeTruthy();
    expect(within(dialog).getByText("Shop A")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "Uninstall" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("asks for the unit's name before an uninstall that is allowed", async () => {
    handlers["GET /api/v1/operator/units/products/plan"] = () => json({
      action: "uninstall", unit: "products", title: "Products", will_install: [], upgrades: [], holders: [], dependants: [], blocked: [],
    });
    handlers["POST /api/v1/operator/units/products/uninstall"] = async (r) => {
      expect(await r.json()).toEqual({ confirm: "products" });
      return json({ installed: [], upgraded: [], uninstalled: "products" });
    };
    await open();
    fireEvent.click(await screen.findByRole("button", { name: /Uninstall Products/ }));
    const dialog = await screen.findByRole("dialog");
    const button = await within(dialog).findByRole("button", { name: "Uninstall" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "products" } });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/products/uninstall"))).toBe(true));
  });

  it("asks for a fresh code when the server says the last one is too old, then repeats the change", async () => {
    handlers["GET /api/v1/operator/units/fresh/plan"] = () => json({
      action: "install", unit: "fresh", title: "Fresh plugin", will_install: [{ name: "fresh", title: "Fresh plugin", kind: "plugin", version: "1.0.0" }],
      upgrades: [], holders: [], dependants: [], blocked: [],
    });
    let installs = 0;
    handlers["POST /api/v1/operator/units/fresh/install"] = () => {
      installs += 1;
      return installs === 1 ? json({ error: "mfa_step_up_required", message: "Confirm with a fresh code" }, 403) : json({ installed: ["fresh"], upgraded: [], uninstalled: null });
    };
    handlers["POST /api/v1/operator/confirm"] = async (r) => {
      expect(await r.json()).toEqual({ code: "123456" });
      return json({ mfa_verified_at: new Date().toISOString(), valid_minutes: 10 });
    };
    await open();
    fireEvent.click(await screen.findByRole("button", { name: /Install Fresh plugin/ }));
    const confirmInstall = await screen.findByRole("dialog");
    fireEvent.click(await within(confirmInstall).findByRole("button", { name: "Install" }));
    const codeBox = await screen.findByLabelText("Authenticator code");
    fireEvent.change(codeBox, { target: { value: "123456" } });
    await waitFor(() => expect(installs).toBe(2));
    expect(calls.filter((c) => c.path.endsWith("/confirm"))).toHaveLength(1);
  });
});
