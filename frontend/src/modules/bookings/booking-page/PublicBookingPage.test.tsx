import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addModuleTranslations, setLanguage } from "@/sdk";

import bookings from "../module";
import PublicBookingPage from "./PublicBookingPage";

configure({ asyncUtilTimeout: 5000 });
vi.setConfig({ testTimeout: 30000 });
addModuleTranslations([bookings]);

const page = {
  business: "Mama Salon", note: "Karibu!", currency: "KES", timezone: "Africa/Nairobi", consent_text: "I agree to be contacted about my booking.", max_days_ahead: 30,
  services: [{ id: "s1", name: "Haircut", description: null, duration_minutes: 45, price: "500.00", mode: "any", resource_ids: [] }], resources: [],
};
const slots = [{ start: "2026-10-20T09:00:00+03:00", end: "2026-10-20T09:45:00+03:00" }, { start: "2026-10-20T09:15:00+03:00", end: "2026-10-20T10:00:00+03:00" }];

let posted: { body: Record<string, unknown>; key: string | null }[];
let slotsReply: () => Response;
let bookReply: () => Response;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function renderPage(slug = "mama-salon") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/book/${slug}`]}>
        <Routes><Route path="/book/:slug" element={<PublicBookingPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setLanguage("en");
  posted = [];
  slotsReply = () => json(slots);
  bookReply = () => json({ status: "requested", number: "APT-1", starts_at: slots[0]?.start, service: "Haircut" }, 201);
  vi.stubGlobal("fetch", async (input: string, init?: RequestInit) => {
    if (input.includes("/slots")) return slotsReply();
    if (input.endsWith("/appointments")) {
      posted.push({ body: JSON.parse(String(init?.body)) as Record<string, unknown>, key: new Headers(init?.headers).get("Idempotency-Key") });
      return bookReply();
    }
    return input.includes("unknown") ? json({ message: "Online booking is not available here" }, 404) : json(page);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("the public booking page", () => {
  it("says so plainly when the address is not a booking page", async () => {
    renderPage("unknown");
    expect(await screen.findByText("Online booking is not available here")).toBeTruthy();
  });

  it("takes a visitor from service to day to time to details to a done screen, without signing in", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Haircut/ }));
    expect(await screen.findByRole("heading", { name: "Which day?" })).toBeTruthy();
    fireEvent.click((await screen.findAllByRole("button", { name: /\d/ }))[1] as HTMLElement);
    expect(await screen.findByRole("heading", { name: "What time?" })).toBeTruthy();
    const times = await screen.findAllByRole("button", { name: /09:/ });
    expect(times.length).toBe(2);
    fireEvent.click(times[0] as HTMLElement);
    expect(await screen.findByRole("heading", { name: "Your details" })).toBeTruthy();

    const book = screen.getByRole("button", { name: "Book now" }) as HTMLButtonElement;
    expect(book.disabled).toBe(true);                                        // needs a name, a way to reach them and the agreement
    fireEvent.change(screen.getByLabelText(/Your name/), { target: { value: "Neema" } });
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "0722000111" } });
    expect(book.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(book.disabled).toBe(false);
    fireEvent.click(book);

    expect(await screen.findByRole("heading", { name: "We have your request" })).toBeTruthy();
    expect(posted).toHaveLength(1);
    expect(posted[0]?.body).toMatchObject({ service_id: "s1", name: "Neema", phone: "0722000111", consent: true, website: "" });
    expect(posted[0]?.key).toBeTruthy();
  });

  it("shows the server's reason when a time was just taken, and keeps the details", async () => {
    bookReply = () => json({ message: "Sorry, that time was just taken. Please pick another time." }, 409);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Haircut/ }));
    fireEvent.click((await screen.findAllByRole("button", { name: /\d/ }))[1] as HTMLElement);
    fireEvent.click((await screen.findAllByRole("button", { name: /09:/ }))[0] as HTMLElement);
    fireEvent.change(await screen.findByLabelText(/Your name/), { target: { value: "Neema" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "neema@example.test" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Book now" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("just taken"));
    expect((screen.getByLabelText(/Your name/) as HTMLInputElement).value).toBe("Neema");
  });

  it("is in Kiswahili when asked", async () => {
    setLanguage("sw");
    renderPage();
    expect(await screen.findByText("Unataka nini?")).toBeTruthy();
  });
});
