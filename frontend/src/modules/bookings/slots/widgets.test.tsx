import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import bookings from "../module";
import CheckoutsWaitingWidget from "./CheckoutsWaitingWidget";
import ClassFillWidget from "./ClassFillWidget";
import DueAgainWidget from "./DueAgainWidget";
import FreeNowWidget from "./FreeNowWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));

const BOARD = "/api/v1/bookings/front-desk/board";
const brief = (n: string, client: string, service: string) => ({ appointment_id: n, number: n, client_name: client, service, starts_at: "2026-10-21T09:00:00Z", ends_at: "2026-10-21T10:00:00Z", status: "completed", customer_id: null, checked_in_at: null, source: "desk", price: "100", waited_minutes: 12, resource_ids: [] });
const person = (id: string, name: string, state: string, free_for_minutes: number | null = null) => ({ resource_id: id, name, kind: "staff", level: null, colour: null, state, until: null, free_for_minutes, current: null, next: null });
const board = (over: object) => ({ day: "2026-10-21", timezone: "Africa/Nairobi", now: "2026-10-21T09:00:00Z", resources: [], waiting: [], arriving: [], in_service: [], to_bill: [], ...over });

describe("bookings Home boxes are registered for the front desk's permission", () => {
  it("names each box once, behind bookings.view", () => {
    const labels = (bookings.slots?.["dashboard.widgets"] ?? []).map((w) => [w.label, w.permission]);
    for (const l of ["freeNow", "checkoutsWaiting", "dueAgain", "classFill"]) expect(labels).toContainEqual([`bookings:widget.${l}`, "bookings.view"]);
  });
});

describe("Free now", () => {
  it("counts the people who are working and free, not the ones who are busy or off", async () => {
    fake.routes[BOARD] = () => board({ resources: [person("a", "Amina", "free", 40), person("b", "Brian", "busy"), person("c", "Cate", "off"), person("d", "Dan", "free")] });
    renderWidget(<FreeNowWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText(/widget.ofWorking/)).toBeTruthy();
  });
  it("lists who is free and for how long in the full box", async () => {
    fake.routes[BOARD] = () => board({ resources: [person("a", "Amina", "free", 40), person("b", "Brian", "busy")] });
    renderWidget(<FreeNowWidget variant="full" />);
    expect(await screen.findByText("Amina")).toBeTruthy();
    expect(screen.getByText("widget.freeFor")).toBeTruthy();
    expect(screen.queryByText("Brian")).toBeNull();
  });
  it("says nobody is free when everyone is busy, and collapses when nobody works now", async () => {
    fake.routes[BOARD] = () => board({ resources: [person("b", "Brian", "busy")] });
    const first = renderWidget(<FreeNowWidget variant="stat" />);
    expect(await screen.findByText("widget.allBusy")).toBeTruthy();
    first.unmount();
    fake.routes[BOARD] = () => board({ resources: [person("c", "Cate", "off")] });
    const { container } = renderWidget(<FreeNowWidget variant="full" />);
    await waitFor(() => expect(container.querySelector("[data-clear]")?.textContent).toBe("widget.nobodyWorking"));
  });
  it("shows the problem when the board cannot be read", async () => {
    fake.routes[BOARD] = () => new Error("The server had a problem.");
    renderWidget(<FreeNowWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("The server had a problem.");
  });
});

describe("Checkouts waiting", () => {
  it("counts visits finished and not billed, with the waiting client's name", async () => {
    fake.routes[BOARD] = () => board({ to_bill: [brief("A1", "Wanjiru", "Braids"), brief("A2", "Otieno", "Trim")] });
    renderWidget(<CheckoutsWaitingWidget variant="full" />);
    expect(await screen.findByText("Wanjiru · Braids")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });
  it("collapses to all clear when everything is billed", async () => {
    fake.routes[BOARD] = () => board({});
    const { container } = renderWidget(<CheckoutsWaitingWidget variant="full" />);
    await waitFor(() => expect(container.querySelector("[data-clear]")?.textContent).toBe("widget.nothingToBill"));
  });
  it("shares one request with Free now", async () => {
    fake.routes[BOARD] = () => board({});
    renderWidget(<><FreeNowWidget variant="stat" /><CheckoutsWaitingWidget variant="stat" /></>);
    await waitFor(() => expect(screen.getAllByText("0").length).toBe(2));
    expect(fake.calls.filter((c) => c.path === BOARD)).toHaveLength(1);
  });
  it("shows the problem when the board cannot be read", async () => {
    fake.routes[BOARD] = () => new Error("No connection.");
    renderWidget(<CheckoutsWaitingWidget variant="full" />);
    expect((await screen.findByRole("alert")).textContent).toContain("No connection.");
  });
});

describe("Due again", () => {
  const recall = (id: string, days: number) => ({ customer_id: id, offer_id: "o", appointment_id: "a", branch_id: "b1", client_name: `Client ${id}`, client_phone: null, service: "Colour", recall_days: 42, visited_on: "2026-08-01", due_on: "2026-09-12", overdue_days: days, last_contacted_at: null, last_outcome: null });
  it("counts the recall list and how many are past their date", async () => {
    fake.routes["/api/v1/bookings/recalls"] = () => [recall("1", 9), recall("2", 0), recall("3", 3)];
    renderWidget(<DueAgainWidget variant="stat" />);
    expect(await screen.findByText("3")).toBeTruthy();
    expect(screen.getByText("widget.overdueCount")).toBeTruthy();
  });
  it("asks for this company's list and shows a plus when the window is full", async () => {
    fake.routes["/api/v1/bookings/recalls"] = () => Array.from({ length: 200 }, (_, i) => recall(String(i), 1));
    renderWidget(<DueAgainWidget variant="stat" />);
    expect(await screen.findByText("200+")).toBeTruthy();
    expect(fake.calls[0].query).toMatchObject({ company_id: "c1", limit: 200 });
  });
  it("collapses when nobody is due, and shows errors", async () => {
    fake.routes["/api/v1/bookings/recalls"] = () => [];
    const { container } = renderWidget(<DueAgainWidget variant="full" />);
    await waitFor(() => expect(container.querySelector("[data-clear]")?.textContent).toBe("widget.nobodyDue"));
  });
  it("shows the problem when the list cannot be read", async () => {
    fake.routes["/api/v1/bookings/recalls"] = () => new Error("Forbidden");
    renderWidget(<DueAgainWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Forbidden");
  });
});

describe("Class fill", () => {
  const SESSIONS = "/api/v1/bookings/sessions";
  const session = (id: string, capacity: number, free: number, over: object = {}) => ({ id, branch_id: "b1", number: id, offer_id: "o", name: `Class ${id}`, status: "scheduled", starts_at: "2099-01-01T06:00:00Z", ends_at: "2099-01-01T07:00:00Z", capacity, booked: capacity - free, held: 0, waiting: 0, free, resource_ids: [], ...over });
  it("works the fill rate out of places taken over places in all, ignoring cancelled classes", async () => {
    fake.routes[SESSIONS] = () => [session("a", 10, 5), session("b", 10, 0), session("c", 10, 10, { status: "cancelled" })];
    renderWidget(<ClassFillWidget variant="stat" />);
    expect(await screen.findByText("75%")).toBeTruthy();       // 15 of 20, the cancelled class is not counted
  });
  it("lists the next classes with their places taken", async () => {
    fake.routes[SESSIONS] = () => [session("a", 12, 3)];
    renderWidget(<ClassFillWidget variant="full" />);
    expect(await screen.findByText("9/12")).toBeTruthy();
  });
  it("asks only for the coming week of this branch", async () => {
    fake.routes[SESSIONS] = () => [];
    renderWidget(<ClassFillWidget variant="stat" />);
    await waitFor(() => expect(fake.calls.length).toBe(1));
    const q = fake.calls[0].query as { branch_id: string; start: string; end: string };
    expect(q.branch_id).toBe("b1");
    expect(new Date(q.end).getTime() - new Date(q.start).getTime()).toBe(7 * 86_400_000);
  });
  it("collapses when no class is coming, and shows errors", async () => {
    fake.routes[SESSIONS] = () => [];
    const first = renderWidget(<ClassFillWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.noClasses"));
    first.unmount();
    fake.routes[SESSIONS] = () => new Error("Down");
    renderWidget(<ClassFillWidget variant="full" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});
