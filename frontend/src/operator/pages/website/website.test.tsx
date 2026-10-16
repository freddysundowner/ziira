import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The first screens load lazily; on a busy machine that can take longer than the 1 s default.
configure({ asyncUtilTimeout: 6000 });

type Handler = (request: Request) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let calls: { method: string; path: string }[] = [];
let handlers: Record<string, Handler> = {};
let available = true;

const SETTINGS = { fields: [], values: { company_legal_name: "Acme Ltd", support_email: "help@acme.test", locales: ["en", "sw"] }, changed: [] };
const REPORT_BAD = { ok: false, counts: { pages: 0, locales: 2 }, warnings: [{ code: "missing_optional", message: "A logo is not set", where: "logo" }], errors: [
  { code: "legal_missing", message: "The privacy page is not published in 'en'", where: "en/privacy" },
  { code: "legal_missing", message: "The privacy page is not published in 'sw'", where: "sw/privacy" },
  { code: "required", message: "This is needed before the site can be published", where: "support_email" },
] };
const REPORT_OK = { ok: true, counts: { pages: 12, locales: 2 }, warnings: [], errors: [] };

beforeEach(() => {
  calls = [];
  available = true;
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
    calls.push({ method: input.method, path: url.pathname });
    const handler = handlers[`${input.method} ${url.pathname}`];
    return handler ? handler(input) : json({ error: "not_found", message: "no handler" }, 404);
  });
  handlers["GET /api/v1/operator/me"] = () => json({ name: "Sam", email: "s@x.test", mfa_verified_at: new Date().toISOString(), step_up_needed: false, mfa_max_age_minutes: 10, mfa_mode: "totp", mfa_off_in_production: false, must_change_password: false, role: "superadmin", permissions: ["platform.view", "platform.content"] });
  handlers["GET /api/v1/operator/site/availability"] = () => json({ available, can_edit: true, hook_configured: true });
  handlers["GET /api/v1/operator/site/settings"] = () => json(SETTINGS);
  handlers["GET /api/v1/operator/site/status"] = () => json({ live: null, pending: [], hook_configured: true });
  handlers["GET /api/v1/operator/units"] = () => json([]);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(path = "/operator/website") {
  sessionStorage.setItem("ziira.operator.token", "operator-token");
  const { default: OperatorApp } = await import("../../OperatorApp");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/operator/*" element={<OperatorApp />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("company and contact", () => {
  it("marks a bad email at once, keeps Save off, and sends only what changed", async () => {
    let sent: unknown = null;
    handlers["PUT /api/v1/operator/site/settings"] = async (r) => {
      sent = await r.json();
      return json({ ...SETTINGS, values: { ...SETTINGS.values, sales_email: "sales@acme.test" }, changed: ["sales_email"] });
    };
    await open();
    const save = await screen.findByRole("button", { name: "Save changes" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    const sales = await screen.findByLabelText("Sales email");
    fireEvent.change(sales, { target: { value: "not-an-email" } });
    expect(await screen.findByText(/Enter an email address like/)).toBeTruthy();
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(sales, { target: { value: "sales@acme.test" } });
    await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(sent).toEqual({ values: { sales_email: "sales@acme.test" } }));
    await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(true));       // saved: nothing left to save
  });

  it("shows the server's own message beside the field it refused", async () => {
    handlers["PUT /api/v1/operator/site/settings"] = () => json({ error: "validation_failed", message: "Some settings are not valid", fields: { company_trading_name: "At most 120 characters" } }, 422);
    await open();
    fireEvent.change(await screen.findByLabelText("Trading name"), { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("At most 120 characters")).toBeTruthy();
  });

  it("shows how the details will read as they are typed", async () => {
    await open();
    fireEvent.change(await screen.findByLabelText("WhatsApp number"), { target: { value: "+254 700 123 456" } });
    expect(await screen.findByText("https://wa.me/254700123456")).toBeTruthy();
  });

  it("says so when the settings cannot be loaded, with a retry", async () => {
    handlers["GET /api/v1/operator/site/settings"] = () => json({ error: "server_error", message: "Database is down" }, 500);
    await open();
    expect(await screen.findByText("Database is down")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Try again|Retry/i })).toBeTruthy();
  });
});

describe("the Website area itself", () => {
  it("is not there in a self-hosted deployment: the page sends the person away", async () => {
    available = false;
    await open();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/operator/units")).toBe(true));      // landed on the units page
    expect(screen.queryByRole("tab", { name: "Publish" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Website" })).toBeNull();
  });

  it("shows how many saved changes are not public yet", async () => {
    handlers["GET /api/v1/operator/site/status"] = () => json({ live: null, pending: [{ area: "settings", ref: "company", change: "changed" }, { area: "page", ref: "en/terms", change: "added" }], hook_configured: true });
    await open();
    expect(await screen.findByText(/2 change\(s\) are saved but not public yet/)).toBeTruthy();
  });
});

describe("pages", () => {
  const PAGES = [
    { id: "p1", slug: "privacy", locale: "en", kind: "legal", title: "Privacy policy", status: "published", state: "live", version: 3, body_length: 900, updated_by: "Sam", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", seo_title: null, seo_description: null },
    { id: "p2", slug: "terms", locale: "en", kind: "legal", title: "Terms of service", status: "draft", state: "draft", version: 1, body_length: 100, updated_by: "Sam", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", seo_title: null, seo_description: null },
  ];

  it("lists pages with their state, names the legal pages still missing, and warns it is not legal advice", async () => {
    handlers["GET /api/v1/operator/site/pages"] = () => json(PAGES);
    await open("/operator/website?tab=pages");
    expect(await screen.findByText("Privacy policy")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    expect(screen.getByText(/Legal pages still to create/)).toBeTruthy();
    expect(screen.getByText(/not legal advice/)).toBeTruthy();
    expect(screen.getAllByText(/Cookie policy/).length).toBeGreaterThan(0);
  });

  it("shows the empty state with what to do next", async () => {
    handlers["GET /api/v1/operator/site/pages"] = () => json([]);
    await open("/operator/website?tab=pages");
    expect(await screen.findByText("No pages yet")).toBeTruthy();
  });

  it("opens the editor and saves with the version it loaded", async () => {
    handlers["GET /api/v1/operator/site/pages"] = () => json(PAGES);
    handlers["GET /api/v1/operator/site/pages/p2"] = () => json({ ...PAGES[1], body_md: "Hello" });
    handlers["POST /api/v1/operator/site/preview"] = () => json({ html: "<p>Hello</p>" });
    let sent: Record<string, unknown> = {};
    handlers["PUT /api/v1/operator/site/pages/p2"] = async (r) => {
      sent = (await r.json()) as Record<string, unknown>;
      return json({ ...PAGES[1], version: 2, body_md: "Hello world" });
    };
    await open("/operator/website?tab=pages");
    fireEvent.click(await screen.findByRole("button", { name: "Terms of service" }));
    const body = await screen.findByLabelText(/Text \(Markdown\)/);
    fireEvent.change(body, { target: { value: "Hello world" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save changes" })[0]);
    await waitFor(() => expect(sent).toMatchObject({ expected_version: 1, title: "Terms of service", body_md: "Hello world" }));
  });

  it("tells the editor when someone else saved first, and does not overwrite", async () => {
    handlers["GET /api/v1/operator/site/pages"] = () => json(PAGES);
    handlers["GET /api/v1/operator/site/pages/p2"] = () => json({ ...PAGES[1], body_md: "Hello" });
    handlers["POST /api/v1/operator/site/preview"] = () => json({ html: "<p>x</p>" });
    handlers["PUT /api/v1/operator/site/pages/p2"] = () => json({ error: "conflict", message: "Someone saved this page after you opened it", current_version: 2 }, 409);
    await open("/operator/website?tab=pages");
    fireEvent.click(await screen.findByRole("button", { name: "Terms of service" }));
    fireEvent.change(await screen.findByLabelText(/Text \(Markdown\)/), { target: { value: "Mine" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save changes" })[0]);
    expect(await screen.findByText(/Someone saved a newer version/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Save changes" })[0]).toHaveProperty("disabled", true);
  });

  it("shows the preview inside a sandboxed frame", async () => {
    handlers["GET /api/v1/operator/site/pages"] = () => json(PAGES);
    handlers["GET /api/v1/operator/site/pages/p2"] = () => json({ ...PAGES[1], body_md: "Hello" });
    handlers["POST /api/v1/operator/site/preview"] = () => json({ html: "<p>Hello</p>" });
    await open("/operator/website?tab=pages");
    fireEvent.click(await screen.findByRole("button", { name: "Terms of service" }));
    const frame = (await screen.findByTitle("Preview")) as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toContain("<p>Hello</p>");
  });
});

describe("publishing", () => {
  it("lists what blocks a publish, grouped, and keeps the button off", async () => {
    handlers["GET /api/v1/operator/site/validate"] = () => json(REPORT_BAD);
    handlers["GET /api/v1/operator/site/publishes"] = () => json([]);
    await open("/operator/website?tab=publish");
    expect(await screen.findByText(/3 problem\(s\) to fix/)).toBeTruthy();
    expect(screen.getByText("Legal page missing")).toBeTruthy();
    expect(screen.getByText("en/privacy")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Publish" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Nothing published yet")).toBeTruthy();
  });

  it("publishes after a confirmation that lists the changes, with a note", async () => {
    handlers["GET /api/v1/operator/site/status"] = () => json({ live: null, pending: [{ area: "page", ref: "en/privacy", change: "added" }], hook_configured: true });
    handlers["GET /api/v1/operator/site/validate"] = () => json(REPORT_OK);
    handlers["GET /api/v1/operator/site/publishes"] = () => json([]);
    let sent: unknown = null;
    handlers["POST /api/v1/operator/site/publish"] = async (r) => {
      sent = await r.json();
      return json({ id: 1, published_at: "2026-10-15T10:00:00Z", published_by: "Sam", note: "launch", version_hash: "abc", hook_status: "pending", pages: 12, warnings: [] }, 201);
    };
    await open("/operator/website?tab=publish");
    const button = await screen.findByRole("button", { name: "Publish" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Page en\/privacy - new/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Note/), { target: { value: "launch" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(sent).toEqual({ note: "launch" }));
  });

  it("offers to try a failed rebuild again", async () => {
    handlers["GET /api/v1/operator/site/validate"] = () => json(REPORT_OK);
    handlers["GET /api/v1/operator/site/publishes"] = () => json([{ id: 7, published_at: "2026-10-15T10:00:00Z", published_by: "Sam", note: null, version_hash: "abc", pages: 12, hook_status: "failed", hook_attempts: 6, hook_next_at: null, hook_result: "builds.test: answered 503" }]);
    let retried = false;
    handlers["POST /api/v1/operator/site/publishes/7/retry-hook"] = () => { retried = true; return json({ id: 7, hook_status: "ok", hook_attempts: 1, hook_next_at: null, hook_result: "builds.test: answered 200" }); };
    await open("/operator/website?tab=publish");
    expect(await screen.findByText(/builds.test: answered 503/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again now" }));
    await waitFor(() => expect(retried).toBe(true));
  });
});

describe("media and pricing", () => {
  it("refuses a file over the limit before sending it", async () => {
    handlers["GET /api/v1/operator/site/assets"] = () => json([]);
    await open("/operator/website?tab=media");
    expect(await screen.findByText("No pictures yet")).toBeTruthy();
    const input = screen.getByLabelText("Choose a file", { selector: "input" }) as HTMLInputElement;
    const big = new File([new Uint8Array(1_600_000)], "big.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByText(/larger than/)).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/assets"))).toBe(false);
  });

  it("shows the public plans read only, and a Get in touch hint when there are none", async () => {
    handlers["GET /api/v1/operator/site/plans"] = () => json({ plans: [], addons: [], updated_at: null });
    await open("/operator/website?tab=pricing");
    expect(await screen.findByText("No public plans")).toBeTruthy();
  });

  it("lists plans with their prices", async () => {
    handlers["GET /api/v1/operator/site/plans"] = () => json({ plans: [{ code: "growth", name: "Growth", description: "For shops", highlights: ["Three branches"], prices: [{ currency: "USD", interval: "month", amount: "30.00" }] }, { code: "ent", name: "Enterprise", contact_only: true, prices: [] }], addons: [], updated_at: null });
    await open("/operator/website?tab=pricing");
    expect(await screen.findByText("Growth")).toBeTruthy();
    expect(screen.getByText("30.00")).toBeTruthy();
    expect(screen.getByText("Contact us")).toBeTruthy();
  });
});
