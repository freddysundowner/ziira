import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/sdk";

import { VerifyRegistration } from "./VerifyRegistration";

// openapi-fetch keeps the fetch it finds when the client is created, so the stand-in must exist before the imports run
const net = vi.hoisted(() => {
  const state = { calls: 0, replies: [] as { status: number; body: unknown }[] };
  const RealRequest = globalThis.Request;      // the client builds Requests from relative paths, which Node refuses
  globalThis.Request = class extends RealRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) { super(typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input, init); }
  } as typeof Request;
  globalThis.fetch = (async (input: Request | string) => {
    const url = input instanceof Request ? input.url : String(input);
    if (!url.includes("/register/verify")) return new Response("{}", { status: 404, headers: { "content-type": "application/json" } });
    state.calls += 1;
    const reply = state.replies.shift() ?? { status: 503, body: {} };
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return state;
});

const down = { status: 503, body: { error: "registration_failed", message: "Your business could not be created right now.", request_id: "req-9" } };

function open(url: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[url]}><SessionProvider><VerifyRegistration /></SessionProvider></MemoryRouter></QueryClientProvider>,
  );
}

beforeEach(() => { net.calls = 0; net.replies = []; vi.useFakeTimers({ shouldAdvanceTime: true }); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("the verification page", () => {
  it("shows the wait, retries a 503 once by itself, then lets the person try again", async () => {
    net.replies = [down, down, { status: 503, body: {} }];
    open("/register/verify?token=zg_abc");
    expect(screen.getByRole("heading", { name: "Creating your business" })).toBeTruthy();
    expect(await screen.findByText(/Trying once more/)).toBeTruthy();
    expect(net.calls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(8100); });
    expect(await screen.findByRole("heading", { name: "We could not create your business yet" })).toBeTruthy();
    expect(net.calls).toBe(2);                                        // one automatic retry, no more
    expect(screen.getByText("Reference: req-9")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Trying once more/)).toBeTruthy();
    expect(net.calls).toBe(3);
  });

  it("says so at once when the link is not valid, with no retry", async () => {
    net.replies = [{ status: 401, body: { error: "unauthorized", message: "This link is not valid or has expired: register again" } }];
    open("/register/verify?token=zg_old");
    expect(await screen.findByText("This link is not valid or has expired: register again")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.getByRole("link", { name: "Register again" })).toBeTruthy();
    expect(net.calls).toBe(1);
  });

  it("names a missing token without calling the server", async () => {
    open("/register/verify");
    expect(await screen.findByText("This link is not valid.")).toBeTruthy();
    expect(net.calls).toBe(0);
  });
});
