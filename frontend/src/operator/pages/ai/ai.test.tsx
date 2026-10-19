import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const choices = (fast: string, capable: string) => [
  { id: fast, title: fast, tiers: ["best_value"], notes: "", input_per_mtok: "0.10", output_per_mtok: "0.50", price_overridden: false, in_catalog: true, live: null },
  { id: capable, title: capable, tiers: ["higher_quality"], notes: "", input_per_mtok: "2", output_per_mtok: "10", price_overridden: false, in_catalog: true, live: null },
];
const provider = (name: string, title: string, over: Record<string, unknown> = {}) => ({
  name, title, capabilities: [], auth: "header", default_base_url: "https://x.test", base_url: "", terms_url: "", docs_url: "", verified_on: "2026-10-16",
  prices_updated: "2026-10-16", price_source: "", enabled: false, key_set: false, key_last4: "", models: { explain: `${name}-fast`, rank: `${name}-fast`, ask: `${name}-fast` },
  model_choices: choices(`${name}-fast`, `${name}-big`), live_models_at: null, last_tested_at: null, last_test_ok: null, last_test_message: null,
  terms_ack_by: null, terms_ack_at: null, is_default: false, updated_at: null, updated_by: null, ...over,
});
const overview = (over: Record<string, unknown> = {}) => ({
  providers: [provider("anthropic", "Anthropic", { enabled: true, key_set: true, key_last4: "1234", is_default: true }), provider("gemini", "Gemini")],
  default_provider: "anthropic", environment_provider: null, monthly_cap_usd: null, month_spend_usd: "0.00", cap_reached: false, production: false, ...over,
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
vi.setConfig({ testTimeout: 90000 });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function open(ov = overview()) {
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json({
    name: "Sam", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp",
    mfa_off_in_production: false, must_change_password: false, role: "superadmin", permissions: ["platform.view", "platform.ai", "platform.operators"],
  });
  handlers["GET /api/v1/operator/ai"] = () => json(ov);
  handlers["GET /api/v1/operator/ai/default-change"] = () => json({ from_provider: "anthropic", to_provider: "gemini", consents_affected: 0 });
  const { default: OperatorApp } = await import("../../OperatorApp");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/operator/ai"]}>
        <Routes><Route path="/operator/*" element={<OperatorApp />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return await screen.findByRole("combobox", { name: "Provider" }, { timeout: 60000 });
}

describe("the AI providers page", () => {
  it("opens as one form with the saved provider picked, its key masked and Details closed", async () => {
    await open();
    expect(await screen.findByText(/AI is on: Anthropic, model anthropic-fast/)).toBeTruthy();
    expect(screen.getByTestId("key-saved").textContent).toBe("Saved ····1234");
    expect(screen.getByRole("button", { name: /Details/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Use this month")).toBeNull();
    expect(document.body.textContent).not.toMatch(/sk-/);
  });

  it("shows only the picked provider's fields and says the other key is kept", async () => {
    const select = await open();
    fireEvent.change(select, { target: { value: "gemini" } });
    expect(screen.queryByTestId("key-saved")).toBeNull();
    expect(await screen.findByPlaceholderText("No key saved yet")).toBeTruthy();
    expect(screen.getByText("Your Anthropic key is saved; it is not used.")).toBeTruthy();
    fireEvent.change(select, { target: { value: "anthropic" } });
    expect(await screen.findByTestId("key-saved")).toBeTruthy();
  });

  it("never renders a typed key back as text, and Save and use saves then makes the provider the default", async () => {
    handlers["PUT /api/v1/operator/ai/providers/gemini"] = () => json(provider("gemini", "Gemini", { enabled: true, key_set: true, key_last4: "9999" }));
    handlers["PUT /api/v1/operator/ai/active"] = () => json({ default_provider: "gemini", from_provider: "anthropic", consents_affected: 0 });
    const select = await open();
    fireEvent.change(select, { target: { value: "gemini" } });
    const input = (await screen.findByPlaceholderText("No key saved yet")) as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.change(input, { target: { value: "fake-key-for-test-9999" } });
    expect(document.body.textContent).not.toContain("fake-key-for-test-9999");
    fireEvent.click(screen.getByRole("button", { name: "Save and use" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/api/v1/operator/ai/active")).toBe(true));
    const saved = calls.find((c) => c.method === "PUT" && c.path === "/api/v1/operator/ai/providers/gemini");
    expect(saved?.body).toMatchObject({ enabled: true, api_key: "fake-key-for-test-9999" });
    expect(calls.find((c) => c.path === "/api/v1/operator/ai/active")?.body).toEqual({ provider: "gemini" });
  });

  it("tells plainly whether the test worked", async () => {
    handlers["POST /api/v1/operator/ai/providers/anthropic/test"] = () => json({ ok: true, message: "", latency_ms: 420, model: "anthropic-fast", tokens_in: 1, tokens_out: 1, cost_usd: "0.0001" });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText("It works. anthropic-fast answered in 420 ms.")).toBeTruthy();
    handlers["POST /api/v1/operator/ai/providers/anthropic/test"] = () => json({ ok: false, message: "The key was refused", latency_ms: 10, model: "m", tokens_in: 0, tokens_out: 0, cost_usd: "0" });
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText("It did not work: The key was refused")).toBeTruthy();
  });

  it("offers None: AI off, which switches the choice off", async () => {
    handlers["PUT /api/v1/operator/ai/active"] = () => json({ default_provider: null, from_provider: "anthropic", consents_affected: 0 });
    const select = await open();
    fireEvent.change(select, { target: { value: "__none__" } });
    fireEvent.click(await screen.findByRole("button", { name: "Switch AI off" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/operator/ai/active")?.body).toEqual({ provider: null }));
  });
});
