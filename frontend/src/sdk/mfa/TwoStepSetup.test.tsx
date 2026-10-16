import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("../api", async (original) => ({ ...(await original<typeof import("../api")>()), api: { POST: (...args: unknown[]) => post(...args) } }));
vi.mock("qrcode", () => ({ toDataURL: () => Promise.resolve("data:image/png;base64,AAAA") }));

import { TwoStepSetup } from "./TwoStepSetup";

afterEach(() => { cleanup(); post.mockReset(); });

const answer = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });

function show() {
  const client = new QueryClient();
  return render(
    <StrictMode>
      <QueryClientProvider client={client}><TwoStepSetup onFinished={() => undefined} /></QueryClientProvider>
    </StrictMode>,
  );
}

describe("TwoStepSetup", () => {
  it("shows the secret once the server answers, even when effects run twice (development)", async () => {
    post.mockImplementation(() => answer({ secret: "ABCDEFGHIJKLMNOP", otpauth_uri: "otpauth://totp/x?secret=ABCDEFGHIJKLMNOP" }));
    show();
    await waitFor(() => expect(screen.getByText(/ABCD/)).toBeTruthy());
    expect(post).toHaveBeenCalledTimes(1);          // asking twice would replace the secret being scanned
  });
  it("offers a retry when the server refuses", async () => {
    post.mockImplementation(() => Promise.resolve({ data: undefined, error: { detail: "No" }, response: { ok: false, status: 500 } }));
    show();
    await waitFor(() => expect(screen.getByRole("button", { name: /retry|try/i })).toBeTruthy());
  });
});
