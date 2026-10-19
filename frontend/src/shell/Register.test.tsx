import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/sdk";

import { Register } from "./Register";

// openapi-fetch keeps the fetch it finds when the client is created, so the stand-in must exist before the imports run
const net = vi.hoisted(() => {
  const state = { handle: (async () => new Response("{}", { status: 404 })) as (input: Request | string, init?: RequestInit) => Promise<Response> };
  const RealRequest = globalThis.Request;      // the client builds Requests from relative paths, which Node refuses
  globalThis.Request = class extends RealRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) { super(typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input, init); }
  } as typeof Request;
  globalThis.fetch = ((input: Request | string, init?: RequestInit) => state.handle(input, init)) as typeof fetch;
  return state;
});

configure({ asyncUtilTimeout: 5000 });      // the whole suite runs in parallel: be patient
vi.setConfig({ testTimeout: 30000 });

const editions = [
  { id: "retail", title: "Retail", pitch: "Sell", units: [], plugin_categories: [], menu_groups: [], landing: "", checklist: [{ id: "a", title: "Add products", hint: "", page: "", unit: null }], sample_data: [] },
  { id: "full", title: "Everything", pitch: "All", units: [], plugin_categories: [], menu_groups: [], landing: "", checklist: [], sample_data: [] },
];
let registered: Record<string, unknown> | null = null;
let registerReply: () => Response;

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

beforeEach(() => {
  sessionStorage.clear();
  window.scrollTo = vi.fn();
  registered = null;
  registerReply = () => json({ message: "ok", dev_token: "zg_dev" }, 202);
  net.handle = async (input, init) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/editions") return json(editions);
    if (path === "/api/v1/countries") return json({}, 503);
    if (path === "/api/v1/register/trial") return json({ plan_code: "starter", plan_name: "Starter", trial_days: 14 });
    if (path === "/api/v1/auth/password/check") {
      const body = (await request.json()) as { password: string };
      return json(body.password === "password123" ? { ok: false, message: "That password is too easy to guess: choose something less common" } : { ok: true });
    }
    if (path === "/api/v1/register") { registered = (await request.json()) as Record<string, unknown>; return registerReply(); }
    return json({}, 404);
  };
});
afterEach(cleanup);

function open(url = "/register") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><SessionProvider><Register /></SessionProvider></MemoryRouter></QueryClientProvider>,
  );
}
const type = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const next = () => fireEvent.click(screen.getByRole("button", { name: "Continue" }));

async function toPassword() {
  await screen.findByRole("radio", { name: /retail/i });
  next();
  type(/your full name/i, "Jane Doe");
  type(/work email/i, "jane@acme.test");
  next();
  await screen.findByRole("heading", { name: "Create your password" });
}

describe("the sign-up wizard", () => {
  it("preselects the edition from ?edition= and ignores an unknown one", async () => {
    const first = open("/register?edition=retail");
    await waitFor(() => expect((screen.getByRole("radio", { name: /retail/i }) as HTMLInputElement).checked).toBe(true));
    first.unmount();
    sessionStorage.clear();
    open("/register?edition=nonsense");
    await waitFor(() => expect((screen.getByRole("radio", { name: /everything/i }) as HTMLInputElement).checked).toBe(true));
  });

  it("holds Continue back until the step is valid", async () => {
    open();
    await screen.findByRole("radio", { name: /retail/i });
    next();
    const cont = screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement;
    expect(cont.disabled).toBe(true);
    type(/your full name/i, "Jane Doe");
    type(/work email/i, "not-an-email");
    expect(cont.disabled).toBe(true);
    type(/work email/i, "jane@acme.test");
    expect(cont.disabled).toBe(false);
  });

  it("checks the password with the server as the person types and refuses a common one", async () => {
    open();
    await toPassword();
    type(/^password/i, "password123");
    type(/type the password again/i, "password123");
    expect(await screen.findByText(/too easy to guess/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    type(/^password/i, "a-good-password-1");
    type(/type the password again/i, "different");
    await waitFor(() => expect(screen.queryByText(/too easy to guess/)).toBeNull());
    expect(await screen.findByText("The two passwords are different.", {}, { timeout: 2000 })).toBeTruthy();
    type(/type the password again/i, "a-good-password-1");
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("goes through all five steps, sends the answers and shows the check-your-email screen", async () => {
    open("/register?edition=retail&plan=starter");
    await toPassword();
    type(/^password/i, "a-good-password-1");
    type(/type the password again/i, "a-good-password-1");
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false));
    next();
    await screen.findByRole("heading", { name: "Tell us about your business" });
    type(/business name/i, "Acme Traders");
    fireEvent.click(screen.getByRole("combobox", { name: /country/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Kenya" }));
    expect((screen.getByLabelText(/^currency/i) as HTMLSelectElement).value).toBe("KES");
    next();
    await screen.findByRole("heading", { name: "Review and create" });
    const create = screen.getByRole("button", { name: "Create my business" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);                       // the consent comes first
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(create);
    await screen.findByRole("heading", { name: "Check your email" });
    expect(registered).toMatchObject({
      owner_name: "Jane Doe", email: "jane@acme.test", business_name: "Acme Traders", country: "KE", currency: "KES", phone_country_code: "254",
      edition: "retail", plan: "starter",
    });
    expect(sessionStorage.getItem("ziira.register.draft")).toBeNull();
  });

  it("keeps the answers (but not the password) across a refresh", async () => {
    const first = open();
    await toPassword();
    type(/^password/i, "a-good-password-1");
    expect(JSON.stringify(Object.entries(sessionStorage))).not.toContain("a-good-password-1");
    first.unmount();
    open();
    await screen.findByRole("heading", { name: "Create your password" });             // back where they were, not further
    expect((screen.getByLabelText(/^password/i) as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect((await screen.findByLabelText(/work email/i) as HTMLInputElement).value).toBe("jane@acme.test");
  });

  it("sends a 422 from the server back to the step and field it belongs to, and counts down a 429", async () => {
    open();
    await toPassword();
    type(/^password/i, "a-good-password-1");
    type(/type the password again/i, "a-good-password-1");
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false));
    next();
    await screen.findByRole("heading", { name: "Tell us about your business" });
    type(/business name/i, "Acme Traders");
    fireEvent.click(screen.getByRole("combobox", { name: /country/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Kenya" }));
    next();
    await screen.findByRole("heading", { name: "Review and create" });
    fireEvent.click(screen.getByRole("checkbox"));
    registerReply = () => json({ error: "validation_failed", message: "That email address does not look right", field: "email" }, 422);
    fireEvent.click(screen.getByRole("button", { name: "Create my business" }));
    await screen.findByRole("heading", { name: "Tell us about you" });
    expect(screen.getByText("That email address does not look right")).toBeTruthy();
    expect(screen.getByLabelText(/work email/i).getAttribute("aria-invalid")).toBe("true");

    type(/work email/i, "jane2@acme.test");
    next();
    await screen.findByRole("heading", { name: "Create your password" });
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false), { timeout: 2000 });
    next();
    next();
    await screen.findByRole("heading", { name: "Review and create" });
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);          // the consent was kept
    registerReply = () => json({ error: "too_many_requests", message: "Too many", retry_after: 3600 }, 429, { "Retry-After": "3600" });
    fireEvent.click(screen.getByRole("button", { name: "Create my business" }));
    expect(await screen.findByText(/Too many tries/)).toBeTruthy();
    expect(screen.getByText(/You can try again in 60:00/)).toBeTruthy();
  });
});
