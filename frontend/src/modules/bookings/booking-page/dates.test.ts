import { describe, expect, it } from "vitest";

import { addDay, dayLabel, longLabel, timeLabel } from "./dates";

describe("public page dates", () => {
  it("adds days across month ends", () => {
    expect(addDay("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDay("2026-03-01", -1)).toBe("2026-02-28");
  });
  it("shows a time on the business's clock, not the visitor's", () => {
    expect(timeLabel("2026-10-19T06:00:00Z", "Africa/Nairobi", "en")).toMatch(/09:00/);
    expect(timeLabel("2026-10-19T06:00:00Z", "UTC", "en")).toMatch(/06:00/);
  });
  it("names the day in the page's language", () => {
    expect(dayLabel("2026-10-19", "en")).toMatch(/Mon/);
    expect(longLabel("2026-10-19T06:00:00Z", "Africa/Nairobi", "en")).toMatch(/October/);
  });
});
