import { describe, expect, it } from "vitest";

import { addDays, clock, dayOf, gridRange, minuteAt, minutesOfDay, offStretches, parseWindows, place, weekdayOf, weekStart, windowsText, workingStretches, zonedIso } from "./lib";

const NAIROBI = "Africa/Nairobi";                        // a fixture zone: +03:00 all year
const PARIS = "Europe/Paris";

describe("times on the company's clock", () => {
  it("reads a moment on the wall clock of the zone, not the browser's", () => {
    expect(minutesOfDay("2026-10-19T06:00:00Z", NAIROBI)).toBe(9 * 60);
    expect(clock("2026-10-19T06:30:00Z", NAIROBI)).toBe("09:30");
    expect(dayOf("2026-10-19T22:30:00Z", NAIROBI)).toBe("2026-10-20");           // 01:30 the next day there
  });
  it("makes the ISO text the API wants, with the zone's offset", () => {
    expect(zonedIso("2026-10-19", "09:00", NAIROBI)).toBe("2026-10-19T09:00:00+03:00");
    expect(zonedIso("2026-07-01", "09:00", PARIS)).toBe("2026-07-01T09:00:00+02:00");
    expect(zonedIso("2026-01-15", "09:00", PARIS)).toBe("2026-01-15T09:00:00+01:00");
    expect(new Date(zonedIso("2026-10-19", "09:00", NAIROBI)).toISOString()).toBe("2026-10-19T06:00:00.000Z");
  });
  it("does days by the calendar", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(weekdayOf("2026-10-19")).toBe(0);                                        // a Monday
    expect(weekStart("2026-10-22")).toBe("2026-10-19");
    expect(weekStart("2026-10-25")).toBe("2026-10-19");
  });
});

describe("the grid", () => {
  const hours = [{ weekday: 0, start_time: "09:00:00", end_time: "17:30:00" }];
  it("shows whole hours around the working day and any appointment outside it", () => {
    expect(gridRange([hours], ["2026-10-19"], [])).toEqual({ start: 9 * 60, end: 18 * 60 });
    expect(gridRange([hours], ["2026-10-19"], [{ start: 7 * 60 + 30, end: 8 * 60 }])).toEqual({ start: 7 * 60, end: 18 * 60 });
    expect(gridRange([], ["2026-10-19"], [])).toEqual({ start: 8 * 60, end: 18 * 60 });
    expect(gridRange([hours], ["2026-10-20"], [])).toEqual({ start: 8 * 60, end: 18 * 60 });      // nobody works on a Tuesday
  });
  it("places a block as a share of the column and snaps a click to the step", () => {
    const range = { start: 9 * 60, end: 17 * 60 };
    expect(place(10 * 60, 11 * 60, range)).toEqual({ top: 12.5, height: 12.5 });
    expect(minuteAt(0.5, range)).toBe(13 * 60);
    expect(minuteAt(0.5 + 7 / 480, range, 15)).toBe(13 * 60);                      // 13:07 snaps down to 13:00
    expect(minuteAt(1.4, range)).toBe(16 * 60 + 45);
  });
  it("finds working stretches and time off on a day", () => {
    expect(workingStretches([...hours, { weekday: 0, start_time: "18:00:00", end_time: "20:00:00" }], "2026-10-19")).toEqual([
      { start: 540, end: 1050 }, { start: 1080, end: 1200 }]);
    const off = [{ starts_at: "2026-10-19T09:00:00+03:00", ends_at: "2026-10-20T12:00:00+03:00" }];
    expect(offStretches(off, "2026-10-19", NAIROBI)).toEqual([{ start: 540, end: 1440 }]);
    expect(offStretches(off, "2026-10-20", NAIROBI)).toEqual([{ start: 0, end: 720 }]);
    expect(offStretches(off, "2026-10-21", NAIROBI)).toEqual([]);
  });
});

describe("working hours text", () => {
  it("reads windows and refuses nonsense", () => {
    expect(parseWindows("09:00-12:00, 13:00-17:30")).toEqual([{ start_time: "09:00", end_time: "12:00" }, { start_time: "13:00", end_time: "17:30" }]);
    expect(parseWindows("")).toEqual([]);
    expect(parseWindows("9:00-17:00")).toEqual([{ start_time: "09:00", end_time: "17:00" }]);
    expect(parseWindows("17:00-09:00")).toBeNull();
    expect(parseWindows("morning")).toBeNull();
    expect(parseWindows("09:00-24:00")).toEqual([{ start_time: "09:00", end_time: "23:59" }]);
  });
  it("writes the windows of a weekday back", () => {
    const rows = [{ weekday: 1, start_time: "09:00:00", end_time: "12:00:00" }, { weekday: 1, start_time: "13:00:00", end_time: "17:00:00" }, { weekday: 2, start_time: "10:00:00", end_time: "11:00:00" }];
    expect(windowsText(rows, 1)).toBe("09:00-12:00, 13:00-17:00");
    expect(windowsText(rows, 4)).toBe("");
  });
});
