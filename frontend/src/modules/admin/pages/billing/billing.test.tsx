import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StateBanner } from "./StateBanner";
import { UsageCard } from "./UsageCard";
import type { MyPlan } from "./lib";

afterEach(cleanup);

const base = { usage: { users: { used: 9, limit: 10 }, branches: { used: 3, limit: 2 }, companies: { used: 1, limit: null } }, units_in_plan: null, units_over_plan: ["payroll"] };

describe("UsageCard", () => {
  it("draws a bar for each limit and none for unlimited", () => {
    render(<UsageCard plan={base} />);
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(2);
    expect(bars[0].getAttribute("aria-valuenow")).toBe("90");
    expect(bars[1].getAttribute("aria-valuenow")).toBe("100");
  });
  it("names the modules switched on outside the plan", () => {
    render(<UsageCard plan={base} />);
    expect(screen.getByText("payroll")).toBeTruthy();
  });
});

describe("StateBanner", () => {
  const plan = (over: Partial<MyPlan>) => ({ access: "full", status: "active", message: "", owed: {}, ...over }) as MyPlan;
  it("shows nothing when all is well", () => {
    const { container } = render(<StateBanner plan={plan({})} />);
    expect(container.textContent).toBe("");
  });
  it("shows the server's message when payment is overdue", () => {
    render(<StateBanner plan={plan({ access: "billing_only", status: "suspended", message: "Account suspended." })} />);
    expect(screen.getByRole("alert").textContent).toContain("Account suspended.");
  });
});
