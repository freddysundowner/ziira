import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import timebilling from "../module";
import DeadlinesWidget from "./DeadlinesWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));
vi.mock("../hooks", () => ({ useWorkCompany: () => ({ companyId: "c1" }) }));

const TASKS = "/api/v1/timebilling/tasks";
const task = (id: string, overdue: boolean) => ({ id, name: `VAT return ${id}`, client_name: "Acme Ltd", project_name: "Books", due_on: "2026-10-23", overdue, status: "open" });

describe("Deadlines", () => {
  it("is registered behind the work permission", () => {
    expect((timebilling.slots?.["dashboard.widgets"] ?? []).map((w) => w.label)).toContain("timebilling:widget.deadlinesTitle");
  });
  it("asks only for open work due within the next 7 days (late work is included by its date)", async () => {
    fake.routes[TASKS] = () => [task("1", true), task("2", false)];
    renderWidget(<DeadlinesWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText("widget.deadlinesLate")).toBeTruthy();
    const q = fake.calls[0].query as { status: string; due_before: string; company_id: string };
    expect(q).toMatchObject({ status: "open", company_id: "c1" });
    const days = (new Date(`${q.due_before}T00:00:00Z`).getTime() - Date.now()) / 86_400_000;
    expect(days).toBeGreaterThan(5.9);
    expect(days).toBeLessThan(8);
  });
  it("lists the work with 'late' for what is behind and its date otherwise", async () => {
    fake.routes[TASKS] = () => [task("1", true), task("2", false)];
    renderWidget(<DeadlinesWidget variant="full" />);
    const rows = (await screen.findAllByRole("listitem")).map((r) => r.textContent);
    expect(rows[0]).toContain("widget.late");
    expect(rows[1]).not.toContain("widget.late");
    expect(rows[1]).toContain("Acme Ltd");
  });
  it("collapses when nothing is due, and shows errors", async () => {
    fake.routes[TASKS] = () => [];
    const first = renderWidget(<DeadlinesWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.noDeadlines"));
    first.unmount();
    fake.routes[TASKS] = () => new Error("Down");
    renderWidget(<DeadlinesWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});
