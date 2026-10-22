import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import jobs from "../module";
import WaitingApprovalWidget from "./WaitingApprovalWidget";
import WaitingInsurerWidget from "./WaitingInsurerWidget";
import WaitingPartsWidget from "./WaitingPartsWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));
vi.mock("../hooks", () => ({ useJobsCompany: () => ({ companyId: "c1" }) }));

const BOARD = "/api/v1/jobs/jobs/board";
const job = (id: string, waiting_on: string[], over: object = {}) => ({ id, number: `J-${id}`, title: "Service", asset: { id: "a", label: `Car ${id}`, kind: "vehicle" }, waiting_on, overdue: false, days_in_status: 2, status: { kind: "open", role: null }, ...over });
const board = (jobs_: object[], truncated = false) => ({ statuses: [], jobs: jobs_, truncated });

describe("jobs 'waiting on' boxes", () => {
  it("are registered behind jobs.view", () => {
    const labels = (jobs.slots?.["dashboard.widgets"] ?? []).map((w) => [w.label, w.permission]);
    for (const l of ["approvalTitle", "partsTitle", "insurerTitle"]) expect(labels).toContainEqual([`jobs:widget.${l}`, "jobs.view"]);
  });
  it("each counts only the jobs held up by its own reason", async () => {
    fake.routes[BOARD] = () => board([job("1", ["approval"]), job("2", ["parts", "approval"]), job("3", [])]);
    renderWidget(<WaitingApprovalWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
  });
  it("lists the car and how long it has waited in the full box, and flags the late ones", async () => {
    fake.routes[BOARD] = () => board([job("1", ["parts"], { overdue: true, days_in_status: 5 })]);
    renderWidget(<WaitingPartsWidget variant="full" />);
    expect(await screen.findByText("J-1 · Car 1")).toBeTruthy();
    expect(screen.getByText("widget.days")).toBeTruthy();
    expect(screen.getByText("widget.lateOnes")).toBeTruthy();
  });
  it("shows a plus when the board was cut short", async () => {
    fake.routes[BOARD] = () => board([job("1", ["parts"])], true);
    renderWidget(<WaitingPartsWidget variant="stat" />);
    expect(await screen.findByText("1+")).toBeTruthy();
  });
  it("collapses when nothing is held up, and shows errors", async () => {
    fake.routes[BOARD] = () => board([job("1", ["approval"])]);
    const first = renderWidget(<WaitingPartsWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.nothing.parts"));
    first.unmount();
    fake.routes[BOARD] = () => new Error("Offline");
    renderWidget(<WaitingPartsWidget variant="full" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Offline");
  });
  it("leaves the insurer box out altogether when the Claims unit is off, and shows it when it is on", async () => {
    fake.routes[BOARD] = () => board([job("1", ["insurer"])]);
    const off = renderWidget(<WaitingInsurerWidget variant="stat" />);
    await waitFor(() => expect(off.container.textContent).toBe(""));
    off.unmount();
    fake.units = new Set(["claims"]);
    renderWidget(<WaitingInsurerWidget variant="stat" />);
    expect(await screen.findByText("1")).toBeTruthy();
  });
  it("shares one board request between the boxes", async () => {
    fake.routes[BOARD] = () => board([]);
    fake.units = new Set(["claims"]);
    renderWidget(<><WaitingApprovalWidget variant="stat" /><WaitingPartsWidget variant="stat" /><WaitingInsurerWidget variant="stat" /></>);
    await waitFor(() => expect(screen.getAllByText("0").length).toBe(3));
    expect(fake.calls.filter((c) => c.path === BOARD)).toHaveLength(1);
  });
});
