import { describe, expect, it } from "vitest";

import { leaveGrid, monthBounds, shiftMonth } from "./calendar";
import type { Leave } from "./types";

const leave = (employee_id: string, start_date: string, end_date: string, status = "approved") => ({ id: `${employee_id}${start_date}`, employee_id, start_date, end_date, status }) as Leave;

describe("calendar", () => {
  it("knows month bounds, including leap February", () => {
    expect(monthBounds("2028-02")).toEqual({ from: "2028-02-01", to: "2028-02-29" });
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
  it("marks the days of leave inside the month, clipping a request that spans months", () => {
    const rows = leaveGrid([leave("a", "2026-05-28", "2026-06-02"), leave("b", "2026-06-10", "2026-06-10")], "2026-06");
    expect([...rows.find((r) => r.employeeId === "a")!.days.keys()]).toEqual([1, 2]);
    expect([...rows.find((r) => r.employeeId === "b")!.days.keys()]).toEqual([10]);
  });
  it("leaves out rejected, cancelled and other months", () => {
    expect(leaveGrid([leave("a", "2026-06-01", "2026-06-03", "rejected"), leave("b", "2026-07-01", "2026-07-02")], "2026-06")).toEqual([]);
  });
});
