import { describe, expect, it } from "vitest";

import {
  asRetention, countBySource, dueState, erasureOf, exportFileName, exportsOf, type Found, groupBySource, hasSearched, recordIdsFor,
  reasonIsEnough, rulesForSources, selectedRecords, subjectMatches, daysUntil,
} from "./model";

const f = (id: string, source: string, match: "exact" | "possible", label = id): Found => ({ source, kind: "customer", record_id: id, label, match, company_id: null });
const found = [f("a", "people", "exact"), f("b", "crm", "possible", "Jane"), f("c", "crm", "exact", "Jane Doe"), f("d", "crm", "exact", "Abe")];

describe("found records", () => {
  it("groups by unit with exact matches first", () => {
    const groups = groupBySource(found);
    expect(groups.map((g) => g.source)).toEqual(["crm", "people"]);
    expect(groups[0].records.map((r) => r.record_id)).toEqual(["d", "c", "b"]);
    expect(groups[0]).toMatchObject({ exact: 2, possible: 1 });
  });
  it("covers exact matches plus confirmed possible ones", () => {
    expect(selectedRecords(found, new Set()).map((r) => r.record_id)).toEqual(["a", "c", "d"]);
    expect(selectedRecords(found, new Set(["b"])).map((r) => r.record_id)).toEqual(["a", "b", "c", "d"]);
    expect(recordIdsFor([f("b", "crm", "possible")], new Set())).toBeUndefined();
    expect(recordIdsFor(found, new Set(["b"]))).toEqual(["a", "b", "c", "d"]);
  });
  it("counts per unit", () => {
    expect(countBySource(selectedRecords(found, new Set(["b"])))).toEqual([{ source: "crm", count: 3 }, { source: "people", count: 1 }]);
  });
  it("lists the retention rules of the involved units only", () => {
    const rules = asRetention({ rules: [{ unit: "crm" }, { unit: "pos" }] }).rules;
    expect(rulesForSources(rules, ["crm"]).map((r) => r.unit)).toEqual(["crm"]);
  });
});

describe("confirming the subject", () => {
  it("ignores spacing and case like the server", () => {
    expect(subjectMatches("  Jane   DOE ", "jane doe")).toBe(true);
    expect(subjectMatches("jane", "jane doe")).toBe(false);
    expect(subjectMatches("", "")).toBe(false);
  });
  it("wants a few words of reason", () => {
    expect(reasonIsEnough("  ok ")).toBe(false);
    expect(reasonIsEnough("Asked by email")).toBe(true);
  });
});

describe("due dates", () => {
  it("counts days across months", () => {
    expect(daysUntil("2026-03-02", "2026-02-28")).toBe(2);
    expect(daysUntil("2026-02-27", "2026-02-28")).toBe(-1);
  });
  it("marks overdue, soon, later and done", () => {
    const base = { status: "open", overdue: false, due_date: "2026-03-10" };
    expect(dueState(base, "2026-03-01")).toBe("later");
    expect(dueState(base, "2026-03-05")).toBe("soon");
    expect(dueState({ ...base, due_date: "2026-03-01" }, "2026-03-05")).toBe("overdue");
    expect(dueState({ ...base, overdue: true }, "2026-03-01")).toBe("overdue");
    expect(dueState({ ...base, status: "completed", overdue: true }, "2026-03-05")).toBe("done");
  });
  it("knows when the search has run", () => {
    expect(hasSearched({ status: "open", found: [] })).toBe(false);
    expect(hasSearched({ status: "in_progress", found: [] })).toBe(true);
  });
});

describe("outcome", () => {
  it("reads an erasure outcome and ignores a missing one", () => {
    expect(erasureOf(null)).toBeNull();
    const done = erasureOf({ erasure: { at: "t", reason: "r", approved_by: "u2", results: [{ source: "crm", kind: "customer", status: "partial", changed: ["name"], kept: [{ what: "tax id", why: "kept 7 years" }], message: "" }] } });
    expect(done?.approvedBy).toBe("u2");
    expect(done?.results[0]).toMatchObject({ status: "partial", changed: ["name"], kept: [{ what: "tax id", why: "kept 7 years" }] });
  });
  it("lists exports and names the file safely", () => {
    expect(exportsOf({ exports: [{ at: "t", by: "u", records: 3 }] })).toEqual([{ at: "t", by: "u", records: 3 }]);
    expect(exportsOf(null)).toEqual([]);
    expect(exportFileName("DSR/2026 1")).toBe("DSR_2026_1-export.json");
  });
});
