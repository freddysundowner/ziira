import { describe, expect, it } from "vitest";

import { filterQuery, mappingProblems, problemRows, progressPercent, stepOf, type Column } from "./wizard";

const col = (name: string, required: boolean): Column => ({ name, required, description: "", example: "", total: null });
const counts = { pending: 0, valid: 0, invalid: 0, imported: 0, skipped: 0, failed: 0 };

describe("stepOf", () => {
  it("follows the status the server reports", () => {
    expect(stepOf(undefined)).toBe(0);
    expect(stepOf("uploaded")).toBe(1);
    expect(stepOf("validated")).toBe(2);
    expect(stepOf("committing")).toBe(3);
    expect(stepOf("done")).toBe(3);
  });
});

describe("mappingProblems", () => {
  const columns = [col("sku", true), col("name", true), col("price", false)];
  it("names required fields without a column", () => {
    expect(mappingProblems(columns, { sku: "Code", name: null, price: null })).toEqual({ missing: ["name"], duplicated: [] });
  });
  it("names a column used twice, and ignores empty choices", () => {
    expect(mappingProblems(columns, { sku: "Code", name: "Code", price: null })).toEqual({ missing: [], duplicated: ["Code"] });
  });
  it("accepts a complete mapping", () => {
    expect(mappingProblems(columns, { sku: "A", name: "B", price: "C" })).toEqual({ missing: [], duplicated: [] });
  });
});

describe("progress", () => {
  it("is rows handled over rows handled plus waiting", () => {
    expect(progressPercent({ ...counts, imported: 3, failed: 1, valid: 4 })).toBe(50);
    expect(progressPercent({ ...counts, imported: 1, valid: 2 })).toBe(33);
  });
  it("is complete when nothing waits", () => {
    expect(progressPercent(counts)).toBe(100);
    expect(progressPercent({ ...counts, imported: 5 })).toBe(100);
  });
  it("counts problems as rejected plus failed", () => {
    expect(problemRows({ ...counts, invalid: 2, failed: 1, imported: 9 })).toBe(3);
  });
});

describe("filterQuery", () => {
  it("asks for the right rows", () => {
    expect(filterQuery("all")).toEqual({});
    expect(filterQuery("problems")).toEqual({ only_errors: true });
    expect(filterQuery("valid")).toEqual({ status: "valid" });
    expect(filterQuery("skipped")).toEqual({ status: "skipped" });
  });
});
