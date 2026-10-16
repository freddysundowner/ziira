import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ColumnChart, Donut, LineChart, Sparkline } from "./charts";

afterEach(cleanup);
const labels = ["Jan", "Feb", "Mar"];

describe("LineChart", () => {
  it("is an image with a name that reads the whole series, for a screen reader", () => {
    render(<LineChart labels={labels} values={[10, 0, 30]} format={(n) => `KES ${n}`} label="Revenue" />);
    expect(screen.getByRole("img", { name: "Revenue. Jan: KES 10, Feb: KES 0, Mar: KES 30" })).toBeTruthy();
  });
  it("says there is nothing to show instead of drawing a flat line", () => {
    render(<LineChart labels={labels} values={[0, 0, 0]} format={String} label="Revenue" empty="No payments yet" />);
    expect(screen.getByText("No payments yet")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
  it("shows the value under the keyboard cursor and hides it on Escape", () => {
    render(<LineChart labels={labels} values={[10, 20, 30]} format={(n) => `${n} units`} label="Revenue" />);
    const chart = screen.getByRole("img");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByRole("status").textContent).toContain("Jan");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByRole("status").textContent).toContain("20 units");
    fireEvent.keyDown(chart, { key: "Escape" });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("ColumnChart", () => {
  it("has an accessible name with every value and an empty state", () => {
    const { rerender } = render(<ColumnChart labels={labels} values={[1, 2, 3]} format={String} label="New" />);
    expect(screen.getByRole("img", { name: "New. Jan: 1, Feb: 2, Mar: 3" })).toBeTruthy();
    rerender(<ColumnChart labels={labels} values={[0, 0, 0]} format={String} label="New" empty="None yet" />);
    expect(screen.getByText("None yet")).toBeTruthy();
  });
});

describe("Sparkline", () => {
  it("is decorative unless it has a label, and absent with too little data", () => {
    const { container, rerender } = render(<Sparkline values={[1, 3, 2]} />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    rerender(<Sparkline values={[1, 3, 2]} label="Trend" />);
    expect(screen.getByRole("img", { name: "Trend" })).toBeTruthy();
    rerender(<Sparkline values={[5]} />);
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("Donut", () => {
  it("carries the numbers in a legend as well as in the ring", () => {
    render(<Donut parts={[{ key: "a", label: "Active", value: 3 }, { key: "t", label: "Trial", value: 1 }]} label="By state" empty="none" centre="4" />);
    expect(screen.getByRole("img", { name: "By state. Active: 3, Trial: 1" })).toBeTruthy();
    expect(screen.getByText("Active").parentElement?.textContent).toContain("75%");
    expect(screen.getByText("4")).toBeTruthy();
  });
  it("says so when there is nothing", () => {
    render(<Donut parts={[]} label="By state" empty="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeTruthy();
  });
});
