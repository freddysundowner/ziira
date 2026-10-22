import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addressProblem, canSendNumber, type ChatOverview, digits, notReadyKey, steps } from "./logic";

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const connection = (over: Record<string, unknown> = {}) => ({ state: "none", mode: null, message: "", code: "", number: null, display_phone: null, has_request: false, active: false, ...over });
const overview = (over: Partial<Record<string, unknown>> = {}): ChatOverview => ({
  provider: { name: "leadsintel", title: "WhatsApp through Lead Intel", description: "", fields: [{ name: "api_key", label: "Lead Intel platform key", secret: true, required: true, help: "", value: null, is_set: false }] },
  fake: false,
  key: { is_set: false, tested_ok: null, tested_at: null },
  connection: connection(),
  webhook: { url: "https://api.example.com/api/v1/public/chat/inbound/********", problem: null, secret_set: false },
  bot: { enabled: false, can_enable: false, not_ready_because: "key", texts: { welcome: "", handoff: "", off_hours: "", language: "auto", hours_start: "", hours_end: "", hours_timezone: "UTC", profile: { about: "About", description: "Desc", website: "" } } },
  stats: { last: 50, answered: 3, unknown: 1, opted_out: 0, failed: 0, other: 0, open_handoffs: 0 },
  updated_at: null, updated_by: null,
  ...over,
}) as ChatOverview;
const connected = (over: Partial<Record<string, unknown>> = {}) => overview({
  key: { is_set: true, tested_ok: true, tested_at: "2026-10-21T10:00:00Z" },
  connection: connection({ state: "connected", mode: "new", number: "+441234567890", display_phone: "+44 1234 567890", active: true }),
  webhook: { url: "https://api.example.com/api/v1/public/chat/inbound/********", problem: null, secret_set: true },
  bot: { enabled: false, can_enable: true, not_ready_because: null, texts: overview().bot.texts },
  ...over,
});

let calls: { method: string; path: string; body?: unknown }[] = [];
let handlers: Record<string, Handler> = {};
let current: ChatOverview;

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

async function open(ov: ChatOverview, permissions = ["platform.view", "platform.settings"]) {
  current = ov;
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  handlers["GET /api/v1/operator/me"] = () => json({
    name: "Sam", email: "sam@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp",
    mfa_off_in_production: false, must_change_password: false, role: "superadmin", permissions,
  });
  handlers["GET /api/v1/operator/chat"] = () => json(current);
  handlers["GET /api/v1/operator/chat/handoffs"] ??= () => json([]);
  handlers["GET /api/v1/operator/chat/connect/status"] = () => json(current.connection);
  const { default: OperatorApp } = await import("../../OperatorApp");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/operator/chat-bot"]}>
        <Routes><Route path="/operator/*" element={<OperatorApp />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return await screen.findByRole("heading", { name: "WhatsApp bot" }, { timeout: 60000 });
}

describe("what the page works out", () => {
  it("walks the steps in order and points at the first one not done", () => {
    expect(steps(overview()).map((s) => [s.id, s.done, s.current])).toEqual([
      ["key", false, true], ["number", false, false], ["say", false, false], ["try", false, false], ["on", false, false]]);
    const ready = steps(connected());
    expect(ready.find((s) => s.current)?.id).toBe("on");
    expect(steps(connected({ bot: { ...connected().bot, enabled: true } })).every((s) => s.done)).toBe(true);
  });
  it("tells why the switch cannot go on", () => {
    expect(notReadyKey(overview())).toBe("key");
    expect(notReadyKey(connected())).toBeNull();
  });
  it("warns about the public address unless it is practice mode", () => {
    expect(addressProblem(overview({ webhook: { url: null, problem: "x", secret_set: false } }))).toBe("empty");
    expect(addressProblem(overview({ webhook: { url: "http://a/b", problem: "x", secret_set: false } }))).toBe("notHttps");
    expect(addressProblem(overview({ fake: true, webhook: { url: null, problem: "x", secret_set: false } }))).toBeNull();
    expect(addressProblem(overview())).toBeNull();
  });
  it("keeps digits only and checks the number form", () => {
    expect(digits("+44 (0)7700-900 123")).toBe("4407700900123");
    const f = { country: "44", phone: "7700900123", business: "Ziira", display: "Ziira" };
    expect(canSendNumber("new", f)).toBe(true);
    expect(canSendNumber("new", { ...f, display: " " })).toBe(false);
    expect(canSendNumber("existing", { ...f, business: "", display: "" })).toBe(true);
    expect(canSendNumber("existing", { ...f, phone: "12" })).toBe(false);
  });
});

describe("the WhatsApp bot page", () => {
  it("starts with the key: not set, the switch off and the reason why", async () => {
    await open(overview());
    expect(screen.getByText("Not set")).toBeTruthy();
    expect(screen.getByTestId("not-ready").textContent).toMatch(/Paste and test the Lead Intel key first/);
    expect((screen.getByRole("switch", { name: "Bot answers messages" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Save and test" }).hasAttribute("disabled")).toBe(true);
    expect(document.body.textContent).not.toMatch(/last 4|····/);
  });

  it("saves the key and tests it, and never shows it back", async () => {
    handlers["PUT /api/v1/operator/chat/key"] = () => json({ is_set: true, tested_ok: null, tested_at: null });
    handlers["POST /api/v1/operator/chat/key/test"] = () => { current = connected({ connection: connection() }); return json({ ok: true, message: "ok" }); };
    await open(overview());
    const input = document.querySelector("input[type=password]") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "li_secret_key_value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and test" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/operator/chat/key/test")).toBe(true));
    expect(calls.find((c) => c.method === "PUT" && c.path.endsWith("/chat/key"))?.body).toEqual({ api_key: "li_secret_key_value" });
    expect((await screen.findAllByText("Lead Intel accepted the key.")).length).toBeGreaterThan(0);
    expect(input.value).toBe("");
    expect(document.body.textContent).not.toContain("li_secret_key_value");
  });

  it("shows a refused key in plain words", async () => {
    handlers["POST /api/v1/operator/chat/key/test"] = () => json({ ok: false, message: "Lead Intel did not accept the key. Check it and paste it again." });
    await open(overview({ key: { is_set: true, tested_ok: null, tested_at: null } }));
    fireEvent.click(screen.getByRole("button", { name: "Save and test" }));
    expect(await screen.findByText(/did not accept the key/)).toBeTruthy();
  });

  it("sends a new number with the digits cleaned and the names", async () => {
    handlers["POST /api/v1/operator/chat/connect"] = () => { current = overview({ key: { is_set: true, tested_ok: true, tested_at: null }, connection: connection({ state: "pending", mode: "new", message: "" }) }); return json(current.connection); };
    await open(overview({ key: { is_set: true, tested_ok: true, tested_at: null } }));
    const boxes = screen.getAllByRole("textbox");
    const labelled = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement;
    fireEvent.change(labelled(/Country calling code/), { target: { value: "+44" } });
    fireEvent.change(labelled(/^Phone number/), { target: { value: "7700 900123" } });
    fireEvent.change(labelled(/^Business name/), { target: { value: "Ziira Ltd" } });
    fireEvent.change(labelled(/WhatsApp profile name/), { target: { value: "Ziira" } });
    expect(boxes.length).toBeGreaterThan(3);
    fireEvent.click(screen.getByRole("button", { name: "Connect the number" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/operator/chat/connect")?.body).toEqual({
      mode: "new", country_code: "44", phone_number: "7700900123", business_name: "Ziira Ltd", display_name: "Ziira" }));
    expect(await screen.findByTestId("connect-progress")).toBeTruthy();
  });

  it("shows connecting with a cancel button, and waiting for the code for a number already on the provider", async () => {
    handlers["POST /api/v1/operator/chat/connect/cancel"] = () => { current = overview({ connection: connection({ state: "cancelled" }) }); return json(current.connection); };
    await open(overview({ key: { is_set: true, tested_ok: true, tested_at: null }, connection: connection({ state: "pending", mode: "new" }) }));
    expect(screen.getByTestId("connect-progress").textContent).toMatch(/setting the number up/);
    expect(screen.queryByLabelText(/Code sent to the number/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText(/The request was cancelled/)).toBeTruthy();
  });

  it("asks for the code when claiming a number and sends the digits", async () => {
    handlers["POST /api/v1/operator/chat/connect/code"] = () => { current = connected(); return json(current.connection); };
    await open(overview({ key: { is_set: true, tested_ok: true, tested_at: null }, connection: connection({ state: "awaiting_code", mode: "existing", message: "A code was sent." }) }));
    expect(screen.getAllByText("Waiting for the code").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText(/Code sent to the number/), { target: { value: "12 34-56" } });
    fireEvent.click(screen.getByRole("button", { name: "Send the code" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/operator/chat/connect/code")?.body).toEqual({ code: "123456" }));
    expect(await screen.findByTestId("connected-number")).toBeTruthy();
  });

  it("shows Lead Intel's reason when connecting failed", async () => {
    await open(overview({ key: { is_set: true, tested_ok: true, tested_at: null }, connection: connection({ state: "failed", message: "Lead Intel could not connect the number: Meta did not approve the name" }) }));
    expect(screen.getByText(/Meta did not approve the name/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Number already on Lead Intel" })).toBeTruthy();
  });

  it("shows the connected number, the hidden address and a disconnect that needs the number typed", async () => {
    handlers["POST /api/v1/operator/chat/disconnect"] = () => { current = overview(); return json({ disconnected: true }); };
    await open(connected());
    expect(screen.getByTestId("connected-number").textContent).toBe("+44 1234 567890");
    expect(screen.getByTestId("webhook-url").textContent).toMatch(/\/inbound\/\*{8}$/);
    expect(screen.getByText("Secret set")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const dialog = await screen.findByRole("dialog");
    const go = within(dialog).getByRole("button", { name: "Disconnect" }) as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Type the number to confirm"), { target: { value: "+44 1234 567890" } });
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/operator/chat/disconnect")?.body).toEqual({ confirm: "+44 1234 567890" }));
  });

  it("warns when the public address is empty or not https", async () => {
    await open(overview({ webhook: { url: "http://api.example.com/x", problem: "must be https", secret_set: false } }));
    expect(screen.getByText(/must start with https/)).toBeTruthy();
  });

  it("turns the bot on only when it can, and off again", async () => {
    handlers["PUT /api/v1/operator/chat/enabled"] = (r) => r.clone().json().then((b: { enabled: boolean }) => { current = connected({ bot: { ...connected().bot, enabled: b.enabled } }); return json({ enabled: b.enabled }); });
    await open(connected());
    const toggle = screen.getByRole("switch", { name: "Bot answers messages" }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(false);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/operator/chat/enabled")?.body).toEqual({ enabled: true }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Bot answers messages" }).getAttribute("aria-checked")).toBe("true"));
    expect(screen.queryByTestId("not-ready")).toBeNull();
  });

  it("shows the reply as the phone would, with the buttons, and says nothing was sent", async () => {
    handlers["POST /api/v1/operator/chat/try"] = () => json({ text: "Hi, I am Ziira's automated assistant.", buttons: [{ id: "see_prices", title: "See prices" }, { id: "talk_person", title: "Talk to a person" }], outcome: "welcome", lang: "en" });
    await open(connected());
    fireEvent.change(screen.getByLabelText("A question"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Show the reply" }));
    const preview = await screen.findByTestId("preview");
    expect(within(preview).getByText(/automated assistant/)).toBeTruthy();
    expect(within(preview).getByText("Talk to a person")).toBeTruthy();
    expect(within(preview).getByText(/Not sent to anyone/)).toBeTruthy();
  });

  it("lists the people waiting with masked numbers and marks one done; shows counts only", async () => {
    handlers["GET /api/v1/operator/chat/handoffs"] = () => json([{ id: "11111111-1111-1111-1111-111111111111", sender_masked: "+254…222", snippet: "human please call [removed]", status: "open", created_at: "2026-10-21T08:00:00Z", done_at: null, done_by: null }]);
    handlers["POST /api/v1/operator/chat/handoffs/11111111-1111-1111-1111-111111111111/done"] = () => json({ id: "11111111-1111-1111-1111-111111111111", sender_masked: "+254…222", snippet: null, status: "done", created_at: "2026-10-21T08:00:00Z", done_at: "2026-10-21T09:00:00Z", done_by: "Sam" });
    await open(connected({ stats: { last: 50, answered: 7, unknown: 2, opted_out: 1, failed: 0, other: 0, open_handoffs: 1 } }));
    expect(await screen.findByText(/\+254…222/)).toBeTruthy();
    expect(screen.getByText(/human please call \[removed\]/)).toBeTruthy();
    const counters = screen.getByTestId("counters");
    expect(within(counters).getByText("7")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/done"))).toBe(true));
  });

  it("shows an empty waiting list", async () => {
    await open(connected());
    expect(await screen.findByText("Nobody is waiting")).toBeTruthy();
  });

  it("saves the texts it was given", async () => {
    handlers["PUT /api/v1/operator/chat/texts"] = () => json({ ...current.bot.texts, welcome: "Karibu", profile_warning: null });
    await open(connected());
    fireEvent.change(screen.getByLabelText("Welcome message"), { target: { value: "Karibu" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect((calls.find((c) => c.method === "PUT" && c.path.endsWith("/texts"))?.body as { welcome: string }).welcome).toBe("Karibu"));
  });

  it("is read only without the settings permission", async () => {
    await open(connected(), ["platform.view"]);
    expect(screen.getByText(/only a super admin can change it/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
    expect((screen.getByRole("switch", { name: "Bot answers messages" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the practice banner and the practice sender box only in practice mode", async () => {
    await open(connected({ fake: true }));
    expect(screen.getByText(/^Practice mode: no real service/)).toBeTruthy();
    expect(screen.getByText("Practice: send a message to the bot")).toBeTruthy();
  });
});
