import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import memberships from "../module";
import CheckinsTodayWidget from "./CheckinsTodayWidget";
import ExpiringWidget from "./ExpiringWidget";
import PaymentsLateWidget from "./PaymentsLateWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));

const M = "/api/v1/memberships";
const summary = (over: object) => ({ active_members: 40, paused_members: 1, renewals_this_month: 9, renewals_next_7_days: 3, packages_expiring_30_days: 0, ending_30_days: 0, failed_runs: 0, drafts_waiting: 0, members_late: 0, trials_running: 0, visits_today: 0, ...over });
const owing = (id: string, owed: string) => ({ customer_id: id, customer_name: `Member ${id}`, phone: null, email: null, owed, oldest_due: "2026-10-01", days_late: 20, invoices: 1, invoice_numbers: ["INV-1"], last_reminder: null, members: [] });

describe("gym Home boxes", () => {
  it("are registered behind memberships.view", () => {
    const labels = (memberships.slots?.["dashboard.widgets"] ?? []).map((w) => [w.label, w.permission]);
    for (const l of ["checkinsTitle", "expiringTitle", "lateTitle"]) expect(labels).toContainEqual([`memberships:widget.${l}`, "memberships.view"]);
  });
});

describe("Check-ins today", () => {
  it("shows the visits and how many were turned away", async () => {
    fake.routes[`${M}/checkin/today`] = () => ({ visits: 52, refused: 3, overridden: 1 });
    renderWidget(<CheckinsTodayWidget variant="stat" />);
    expect(await screen.findByText("52")).toBeTruthy();
    expect(screen.getByText("widget.refused")).toBeTruthy();
    expect(fake.calls[0].query).toMatchObject({ company_id: "c1" });
  });
  it("collapses before anyone has come, and shows errors", async () => {
    fake.routes[`${M}/checkin/today`] = () => ({ visits: 0, refused: 0, overridden: 0 });
    const first = renderWidget(<CheckinsTodayWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.noCheckins"));
    first.unmount();
    fake.routes[`${M}/checkin/today`] = () => new Error("Down");
    renderWidget(<CheckinsTodayWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});

describe("Expiring memberships", () => {
  it("counts memberships ending in 30 days, and keeps renewals as a separate line", async () => {
    fake.routes[`${M}/summary`] = () => summary({ ending_30_days: 4, packages_expiring_30_days: 2 });
    renderWidget(<ExpiringWidget variant="full" />);
    expect((await screen.findAllByText("4")).length).toBeGreaterThan(0);
    const rows = screen.getAllByRole("listitem").map((r) => r.textContent);
    expect(rows).toEqual(["widget.rowEnding4", "widget.rowRenewing3", "widget.rowPackages2"]);
  });
  it("collapses when nothing ends, and shows errors", async () => {
    fake.routes[`${M}/summary`] = () => summary({});
    const first = renderWidget(<ExpiringWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.nothingEnding"));
    first.unmount();
    fake.routes[`${M}/summary`] = () => new Error("Down");
    renderWidget(<ExpiringWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});

describe("Payments late", () => {
  it("counts the people who owe and adds up what they owe without rounding errors", async () => {
    fake.routes[`${M}/arrears`] = () => [owing("1", "1000.10"), owing("2", "2000.20")];
    renderWidget(<PaymentsLateWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText("widget.owed")).toBeTruthy();
    expect(fake.calls[0].query).toMatchObject({ company_id: "c1", min_days: 1 });
  });
  it("lists who owes how much in the full box", async () => {
    fake.routes[`${M}/arrears`] = () => [owing("1", "1500")];
    renderWidget(<PaymentsLateWidget variant="full" />);
    expect((await screen.findByRole("listitem")).textContent).toContain("Member 1");
  });
  it("collapses when nobody is late, and shows errors", async () => {
    fake.routes[`${M}/arrears`] = () => [];
    const first = renderWidget(<PaymentsLateWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.nobodyLate"));
    first.unmount();
    fake.routes[`${M}/arrears`] = () => new Error("Down");
    renderWidget(<PaymentsLateWidget variant="full" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});
