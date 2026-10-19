import { describe, expect, it } from "vitest";

import {
  addDays, barWidth, buildRows, dayTotals, elapsedNow, formatClock, formatDuration, formatElapsed, gridMinutesFor, linePreview, looksForgotten, monthStartOf,
  parseDuration, rowKey, rowTotal, snapMinutes, weekDays, weekStartOf, type GridEntry,
} from "./lib";

describe("typing a time", () => {
  it.each([
    ["1.5", 90], ["1,5", 90], ["1:30", 90], [":45", 45], ["0:05", 5], ["90m", 90], ["2h", 120], ["1h 30m", 90], ["2h15", 135], ["8", 480], ["", 0], ["  .25 ", 15], ["24", 1440],
  ])("reads %j as %i minutes", (text, minutes) => expect(parseDuration(text)).toBe(minutes));
  it.each(["abc", "1:75", "25", "1:2:3", "-1", "1h 75m", "1440m1"])("refuses %j", (text) => expect(parseDuration(text)).toBeNull());
});

describe("snapping to the business's step", () => {
  it("rounds to the nearest step, halves up", () => {
    expect(snapMinutes(7, 15)).toBe(15);
    expect(snapMinutes(22, 15)).toBe(15);
    expect(snapMinutes(23, 15)).toBe(30);
    expect(snapMinutes(40, 1)).toBe(40);
  });
  it("never rounds a little time away to nothing, and keeps a day at most 24 hours", () => {
    expect(snapMinutes(2, 15)).toBe(15);
    expect(snapMinutes(0, 15)).toBe(0);
    expect(snapMinutes(1439, 60)).toBe(1440);
  });
});

describe("showing time", () => {
  it("writes hours and minutes in words", () => {
    expect(formatDuration(90)).toBe("1h 30m");
    expect(formatDuration(120)).toBe("2h");
    expect(formatDuration(45)).toBe("45m");
    expect(formatDuration(0)).toBe("0m");
    expect(formatDuration(null)).toBe("—");
  });
  it("writes a clock for edit boxes", () => {
    expect(formatClock(90)).toBe("1:30");
    expect(formatClock(5)).toBe("0:05");
    expect(formatClock(0)).toBe("");
  });
});

describe("weeks", () => {
  it("finds the first day of the week for either start day", () => {
    expect(weekStartOf("2026-10-18", 1)).toBe("2026-10-12");   // a Sunday, week from Monday
    expect(weekStartOf("2026-10-12", 1)).toBe("2026-10-12");
    expect(weekStartOf("2026-10-18", 7)).toBe("2026-10-18");   // week from Sunday
    expect(weekStartOf("2026-10-17", 7)).toBe("2026-10-11");
  });
  it("walks days across month and year ends", () => {
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
    expect(weekDays("2026-10-12")).toHaveLength(7);
    expect(weekDays("2026-10-12")[6]).toBe("2026-10-18");
    expect(monthStartOf("2026-10-18", -1)).toBe("2026-09-01");
    expect(monthStartOf("2026-01-31", -1)).toBe("2025-12-01");
  });
});

const e = (over: Partial<GridEntry>): GridEntry => ({
  project_id: "p1", project_code: "A-1", project_name: "Alpha", task: null, work_date: "2026-10-12", minutes: 60, billable: true, source: "grid", ...over,
});

describe("the week grid", () => {
  const days = weekDays("2026-10-12");
  const rows = buildRows([
    e({ minutes: 90 }), e({ work_date: "2026-10-13", minutes: 60 }), e({ source: "timer", minutes: 30 }),
    e({ task: " Design ", work_date: "2026-10-14", minutes: 120 }), e({ project_id: "p2", project_code: "B-1", billable: false, minutes: 45 }),
  ], [{ project_id: "p3", project_code: "C-1", project_name: "Gamma", task: null, billable: true }]);

  it("makes one row per project, task and billable flag, plus the rows added by hand", () => {
    expect(rows.map((r) => r.key)).toEqual([rowKey("p1", null, true), rowKey("p1", "Design", true), rowKey("p2", null, false), rowKey("p3", null, true)]);
  });
  it("adds up cells, rows and days", () => {
    expect(rows[0]?.cells["2026-10-12"]).toEqual({ total: 120, own: 90 });
    expect(rowTotal(rows[0]!, days)).toBe(180);
    expect(dayTotals(rows, days)).toEqual([165, 60, 120, 0, 0, 0, 0]);
  });
  it("works out what the grid stores when a day's total is typed", () => {
    expect(gridMinutesFor(150, rows[0]?.cells["2026-10-12"])).toBe(120);   // 30 came from the timer
    expect(gridMinutesFor(20, rows[0]?.cells["2026-10-12"])).toBeNull();    // below the timer's 30
    expect(gridMinutesFor(60, undefined)).toBe(60);
  });
});

describe("the timer clock", () => {
  it("counts on while running and stands still when paused", () => {
    expect(elapsedNow({ elapsed_seconds: 100, running: true }, 1_000_000, 1_065_500)).toBe(165);
    expect(elapsedNow({ elapsed_seconds: 100, running: false }, 1_000_000, 1_065_500)).toBe(100);
    expect(elapsedNow({ elapsed_seconds: 100, running: true }, 2_000_000, 1_000_000)).toBe(100);
  });
  it("shows h:mm:ss", () => {
    expect(formatElapsed(0)).toBe("0:00:00");
    expect(formatElapsed(3725)).toBe("1:02:05");
  });
  it("spots a timer left running", () => {
    expect(looksForgotten(11 * 3600)).toBe(false);
    expect(looksForgotten(13 * 3600)).toBe(true);
  });
});

describe("previews", () => {
  it("multiplies hours by the rate to two places", () => {
    expect(linePreview(90, "120")).toBe("180.00");
    expect(linePreview(20, "100")).toBe("33.33");
    expect(linePreview(60, "")).toBeNull();
    expect(linePreview(null, "10")).toBeNull();
  });
  it("keeps a bar inside its box", () => {
    expect(barWidth("120.5")).toBe(100);
    expect(barWidth(-3)).toBe(0);
    expect(barWidth(null)).toBe(0);
    expect(barWidth("42.5")).toBe(42.5);
  });
});

describe("long durations", () => {
  it("accepts a budget over a day only when asked to", () => {
    expect(parseDuration("40")).toBeNull();
    expect(parseDuration("40", 6_000_000)).toBe(2400);
    expect(parseDuration("40:30", 6_000_000)).toBe(2430);
  });
});
