import { describe, expect, it } from "vitest";

import { fromLocalInput, hoursText, shortTime, toLocalInput } from "./time";

describe("time helpers", () => {
  it("round-trips a local date and time through ISO", () => {
    const local = "2026-03-04T08:30";
    expect(toLocalInput(fromLocalInput(local))).toBe(local);
  });
  it("treats empty as nothing", () => {
    expect(fromLocalInput("")).toBeNull();
    expect(toLocalInput(null)).toBe("");
  });
  it("shortens times and hours", () => {
    expect(shortTime("08:30:00")).toBe("08:30");
    expect(hoursText("7.50")).toBe("7.5");
    expect(hoursText(null)).toBe("—");
  });
});
