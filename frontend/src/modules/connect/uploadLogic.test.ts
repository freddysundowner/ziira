import { describe, expect, it } from "vitest";

import { compactMoney, dateReadings, hintsFor, issuesCsv, refuseFile, sampleColumns, splitFields } from "./uploadLogic";

const field = (name: string, column: string | null, simple = true) => ({ name, label: name, required: false, column, examples: [], simple });

describe("upload logic", () => {
  it("accepts statements as PDF, Excel, CSV or a photo, and refuses the rest", () => {
    for (const name of ["a.pdf", "A.XLSX", "b.csv", "c.png", "d.JPG", "e.jpeg"]) expect(refuseFile({ name, size: 100 })).toBeNull();
    expect(refuseFile({ name: "a.docx", size: 100 })).toBe("type");
    expect(refuseFile({ name: "a.xls", size: 100 })).toBe("type");
    expect(refuseFile({ name: "a.pdf", size: 11 * 1024 * 1024 })).toBe("size");
  });
  it("shortens big amounts for the one-line summary", () => {
    expect(compactMoney("1200000", "KES", "en")).toMatch(/1\.2M/);
    expect(compactMoney("900000.50", undefined, "en")).toBe("900K");
    expect(compactMoney(null, "KES", "en")).toBe("—");
  });
  it("writes an ambiguous date both ways in words", () => {
    expect(dateReadings("03/04/2026", "en-GB")).toEqual({ dmy: "3 April 2026", mdy: "4 March 2026" });
    expect(dateReadings("13/04/2026", "en")).toBeNull();
    expect(dateReadings("2026-04-03", "en")).toBeNull();
  });
  it("picks the columns for the 'what we found' table in reading order", () => {
    const cols = sampleColumns([field("balance", "Bal"), field("money_out", "Out"), field("date", "When"), field("money_in", "In"), field("status", "St"), field("description", "Details")]);
    expect(cols.map((c) => c.name)).toEqual(["date", "description", "money_in", "money_out", "balance"]);
    expect(cols[0].header).toBe("When");
  });
  it("separates the fields that matter from the rest", () => {
    const { main, more } = splitFields([field("date", "A"), field("status", "B", false)]);
    expect(main.map((f) => f.name)).toEqual(["date"]);
    expect(more.map((f) => f.name)).toEqual(["status"]);
  });
  it("writes the list of left-out lines as a safe CSV", () => {
    const csv = issuesCsv({ headers: [], issues: [{ row: 3, message: 'amount: "x" is not a number' }], review_rows: [{ row: 3, problem: "", cells: ["=cmd()", "Rent, May"] }] }, { line: "Line", problem: "Problem" });
    expect(csv).toBe('Line,Problem,Line text\r\n3,"amount: ""x"" is not a number","\'=cmd() | Rent, May"\r\n');
  });
  it("chooses the right hints for what was stored", () => {
    expect(hintsFor(["payments"])).toBe("statement");
    expect(hintsFor(["invoices", "parties"])).toBe("invoices");
    expect(hintsFor(["stock_movements"])).toBe("stock");
    expect(hintsFor(["sales"])).toBe("sales");
  });
});
