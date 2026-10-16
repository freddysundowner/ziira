import { afterEach, describe, expect, it } from "vitest";

import { formatDate, setDisplayTimeZone, today } from "./format";

afterEach(() => setDisplayTimeZone(undefined));

describe("times are on the company's clock", () => {
  // 21:30 UTC on 4 March is already 5 March at midnight-thirty in Nairobi (UTC+3) and still 4 March at 16:30 in New York.
  const moment = "2026-03-04T21:30:00Z";
  it("shows the same moment differently only because the company's zone says so", () => {
    setDisplayTimeZone("Africa/Nairobi");
    expect(formatDate(moment, true)).toContain("12:30");
    expect(formatDate(moment)).toContain("5");
    setDisplayTimeZone("America/New_York");
    expect(formatDate(moment, true)).toContain("4:30");
  });
  it("gives a list and a receipt the same time because both use this one helper", () => {
    setDisplayTimeZone("Africa/Nairobi");
    expect(formatDate(moment, true)).toBe(formatDate(new Date(moment), true));
  });
  it("never moves a plain calendar date to another day", () => {
    setDisplayTimeZone("America/New_York");
    expect(formatDate("2026-03-05")).toContain("5");
    expect(formatDate("2026-03-05")).not.toContain("4,");
  });
  it("ignores a zone name it does not know", () => {
    setDisplayTimeZone("Africa/Nairobi");
    setDisplayTimeZone("Not/AZone");
    expect(formatDate(moment, true)).toContain("12:30");
  });
  it("gives today's date as YYYY-MM-DD", () => {
    setDisplayTimeZone("Pacific/Kiritimati");
    expect(today()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
