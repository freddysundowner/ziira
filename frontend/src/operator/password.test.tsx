import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const me = (over: Record<string, unknown> = {}) => ({
  name: "Sam", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10,
  mfa_mode: "off", mfa_off_in_production: false, must_change_password: false, role: "superadmin", permissions: ["platform.view", "platform.operators", "platform.units"], ...over,
});

let calls: { method: string; path: string; body?: unknown }[] = [];
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
    calls.push({ method: input.method, path: url.pathname, body });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(path: string, signedIn = true) {
  if (signedIn) sessionStorage.setItem("ziira.operator.token", "operator-token");
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

const UNITS = [{ name: "fresh", title: "Fresh plugin", kind: "plugin", version: "1.0.0", status: "available", requires: [], businesses_enabled: 0, businesses_holding: 0, behind: 0, extra: false }];

describe("signing in with a password alone", () => {
  it("opens the console straight after the password, with no code step", async () => {
    handlers["POST /api/v1/operator/sign-in"] = async (r) => {
      expect(await r.json()).toEqual({ email: "sam@x.test", password: "a long enough password" });
      return json({ access_token: "tok", expires_in: 28800, must_change_password: false });
    };
    handlers["GET /api/v1/operator/me"] = () => json(me());
    handlers["GET /api/v1/operator/units"] = () => json([]);
    await open("/operator/units", false);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "sam@x.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a long enough password" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("navigation", { name: "Console areas" })).toBeTruthy();
    expect(screen.queryByText("Enter your code")).toBeNull();
    expect(sessionStorage.getItem("ziira.operator.token")).toBe("tok");
  });

  it("still asks for the code when the platform answers with a challenge", async () => {
    handlers["POST /api/v1/operator/sign-in"] = () => json({ challenge: "c1", must_change_password: false });
    await open("/operator/units", false);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "sam@x.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a long enough password" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Enter your code" })).toBeTruthy();
  });
});

describe("confirming with the password before a change", () => {
  it("opens a password box when a change is refused as too old, then repeats the change", async () => {
    handlers["GET /api/v1/operator/me"] = () => json(me());
    handlers["GET /api/v1/operator/units"] = () => json(UNITS);
    handlers["GET /api/v1/operator/units/fresh/plan"] = () => json({
      action: "install", unit: "fresh", title: "Fresh plugin", will_install: [{ name: "fresh", title: "Fresh plugin", kind: "plugin", version: "1.0.0" }],
      upgrades: [], holders: [], dependants: [], blocked: [],
    });
    let installs = 0;
    handlers["POST /api/v1/operator/units/fresh/install"] = () => {
      installs += 1;
      return installs === 1 ? json({ error: "mfa_step_up_required", message: "Confirm your password to make this change" }, 403) : json({ installed: ["fresh"], upgraded: [], uninstalled: null });
    };
    handlers["POST /api/v1/operator/confirm"] = async (r) => {
      expect(await r.json()).toEqual({ password: "my password here" });
      return json({ mfa_verified_at: new Date().toISOString(), valid_minutes: 10 });
    };
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: /Install Fresh plugin/ }));
    fireEvent.click(await within(await screen.findByRole("dialog")).findByRole("button", { name: "Install" }));
    const box = await screen.findByLabelText("Your password");
    expect(screen.queryByLabelText("Authenticator code")).toBeNull();
    fireEvent.change(box, { target: { value: "my password here" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(installs).toBe(2));
  });

  it("shows a wrong password in the box and does not repeat the change", async () => {
    handlers["GET /api/v1/operator/me"] = () => json(me());
    handlers["GET /api/v1/operator/units"] = () => json(UNITS);
    handlers["GET /api/v1/operator/units/fresh/plan"] = () => json({ action: "install", unit: "fresh", title: "Fresh plugin", will_install: [], upgrades: [], holders: [], dependants: [], blocked: [] });
    handlers["POST /api/v1/operator/units/fresh/install"] = () => json({ error: "mfa_step_up_required", message: "Confirm your password to make this change" }, 403);
    handlers["POST /api/v1/operator/confirm"] = () => json({ error: "unauthorized", message: "That password is not right" }, 401);
    await open("/operator/units");
    fireEvent.click(await screen.findByRole("button", { name: /Install Fresh plugin/ }));
    fireEvent.click(await within(await screen.findByRole("dialog")).findByRole("button", { name: "Install" }));
    fireEvent.change(await screen.findByLabelText("Your password"), { target: { value: "wrong one" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("That password is not right")).toBeTruthy();
    expect(sessionStorage.getItem("ziira.operator.token")).toBe("operator-token");                // a typo does not sign out
    expect(calls.filter((c) => c.path.endsWith("/units/fresh/install"))).toHaveLength(1);
  });
});

describe("a temporary password", () => {
  it("shows only the change-password screen until a new password is saved", async () => {
    let mustChange = true;
    handlers["GET /api/v1/operator/me"] = () => json(me({ must_change_password: mustChange }));
    handlers["GET /api/v1/operator/units"] = () => json([]);
    handlers["POST /api/v1/operator/password"] = async (r) => {
      expect(await r.json()).toEqual({ current_password: "the temporary one", new_password: "my own long password" });
      mustChange = false;
      return new Response(null, { status: 204 });
    };
    await open("/operator/units");
    expect(await screen.findByRole("heading", { name: "Choose a new password" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(calls.some((c) => c.path.endsWith("/units"))).toBe(false);
    const save = screen.getByRole("button", { name: "Change password" }) as HTMLButtonElement;
    const newPassword = () => screen.getAllByLabelText(/New password/)[0];             // the first of "New password" and "New password again"
    const repeat = () => screen.getAllByLabelText(/New password/)[1];
    fireEvent.change(screen.getByLabelText(/Current password/), { target: { value: "the temporary one" } });
    fireEvent.change(newPassword(), { target: { value: "short" } });
    expect(await screen.findByText("At least 8 characters.")).toBeTruthy();
    expect(save.disabled).toBe(true);
    fireEvent.change(newPassword(), { target: { value: "my own long password" } });
    fireEvent.change(repeat(), { target: { value: "my own long passwor" } });
    expect(await screen.findByText("The two passwords are not the same.")).toBeTruthy();
    fireEvent.change(repeat(), { target: { value: "my own long password" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(await screen.findByRole("navigation", { name: "Console areas" })).toBeTruthy();
  });
});

describe("the warning when production has no second factor", () => {
  it("shows once per browser session and can be dismissed", async () => {
    handlers["GET /api/v1/operator/me"] = () => json(me({ mfa_off_in_production: true }));
    handlers["GET /api/v1/operator/units"] = () => json([]);
    await open("/operator/units");
    expect(await screen.findByText("Staff sign in with a password alone")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide for now" }));
    expect(screen.queryByText("Staff sign in with a password alone")).toBeNull();
    expect(sessionStorage.getItem("ziira.operator.risk.mfa_off")).toBe("1");
  });

  it("is not shown when it does not apply", async () => {
    handlers["GET /api/v1/operator/me"] = () => json(me());
    handlers["GET /api/v1/operator/units"] = () => json([]);
    await open("/operator/units");
    await screen.findByRole("navigation", { name: "Console areas" });
    expect(screen.queryByText("Staff sign in with a password alone")).toBeNull();
  });
});

describe("the operators page without a second factor", () => {
  const operators = [
    { id: "o1", name: "Sam", email: "sam@x.test", status: "active", role: "superadmin", created_at: "2026-01-01T00:00:00Z", last_sign_in_at: null, mfa_enrolled: false, must_change_password: false, open_sessions: 1 },
    { id: "o2", name: "Bea", email: "bea@x.test", status: "active", role: "billing", created_at: "2026-01-01T00:00:00Z", last_sign_in_at: null, mfa_enrolled: false, must_change_password: true, open_sessions: 0 },
  ];
  beforeEach(() => {
    handlers["GET /api/v1/operator/me"] = () => json(me());
    handlers["GET /api/v1/operator/operators"] = () => json(operators);
    handlers["GET /api/v1/operator/actions"] = () => json([]);
    handlers["GET /api/v1/operator/roles"] = () => json({ roles: [], permissions: {} });
  });

  it("says the second factor is off, hides its column and action, and resets a password", async () => {
    handlers["POST /api/v1/operator/operators/o2/reset-password"] = () => json({ temporary_password: "Tmp-pass-123456" });
    await open("/operator/operators");
    expect(await screen.findByText("Bea")).toBeTruthy();
    expect(screen.getByTestId("second-factor-state").textContent).toContain("Second factor: off");
    expect(screen.queryByRole("columnheader", { name: "Second factor" })).toBeNull();
    expect(screen.getByText("Must change password")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Bea" }));
    expect(screen.queryByRole("menuitem", { name: "Reset second factor" })).toBeNull();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reset password" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Reset password" }));
    expect((await screen.findByTestId("temp-password")).textContent).toBe("Tmp-pass-123456");
  });

  it("shows the temporary password of a new operator once, when none was typed", async () => {
    handlers["POST /api/v1/operator/operators"] = async (r) => {
      expect(await r.json()).toEqual({ name: "Cy Dee", email: "cy@x.test", password: null, role: "readonly" });
      return json({ id: "o3", temporary_password: "Tmp-new-987654", mfa_secret: null, otpauth_uri: null }, 201);
    };
    await open("/operator/operators");
    fireEvent.click(await screen.findByRole("button", { name: /Add operator/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Full name/), { target: { value: "Cy Dee" } });
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: "cy@x.test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add operator" }));
    expect((await screen.findByTestId("temp-password")).textContent).toBe("Tmp-new-987654");
  });
});
