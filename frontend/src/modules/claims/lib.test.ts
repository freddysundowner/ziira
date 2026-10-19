import { describe, expect, it } from "vitest";

import { answerProblem, blankRow, canAnswer, cents, daysSince, lineTotal, rowProblems, rowsTotal, statusTone, sumAmounts, toAnswers, toLineBody, type EditorRow } from "./lib";
import type { EstimateLine } from "./types";

const row = (over: Partial<EditorRow>): EditorRow => ({ ...blankRow("parts"), description: "Bumper", unitPrice: "100", ...over });

describe("amounts", () => {
  it("add in cents without float error", () => {
    expect(sumAmounts(["0.10", "0.20"])).toBe("0.30");
    expect(sumAmounts(["600.00", "12000.00", "4500.00", "8000.00", "350.00"])).toBe("25450.00");
    expect(cents("19.995")).toBe(2000);
  });
  it("price a line to the cent", () => {
    expect(lineTotal("4", "150")).toBe("600.00");
    expect(lineTotal("2.5", "10.10")).toBe("25.25");
    expect(lineTotal("0", "10")).toBe("0.00");
    expect(lineTotal("x", "10")).toBe("0.00");
  });
});

describe("estimate rows", () => {
  it("need a description, a quantity above zero and a price (labour and paint may use the payer's rate)", () => {
    expect(rowProblems(row({}))).toEqual([]);
    expect(rowProblems(row({ description: " " }))).toEqual(["description"]);
    expect(rowProblems(row({ quantity: "0" }))).toEqual(["quantity"]);
    expect(rowProblems(row({ unitPrice: "" }))).toEqual(["price"]);
    expect(rowProblems(row({ kind: "labour", unitPrice: "" }))).toEqual([]);
    expect(rowProblems(row({ kind: "paint", unitPrice: "" }))).toEqual([]);
    expect(rowProblems(row({ unitPrice: "-1" }))).toEqual(["price"]);
  });
  it("send only the rows that can still change, keeping an existing row's id", () => {
    const body = toLineBody([row({ id: "a", locked: true }), row({ id: "b", kind: "labour", workType: "body", unitPrice: "" }), row({ partClass: "genuine" })]);
    expect(body).toHaveLength(2);
    expect(body[0]).toMatchObject({ line_id: "b", kind: "labour", unit_price: null, work_type: "body", part_class: null });
    expect(body[1]).toMatchObject({ line_id: null, kind: "parts", unit_price: "100", work_type: null, part_class: "genuine" });
  });
  it("total settled lines and new ones together", () => {
    const settled = [{ asked_total: "600.00" }] as EstimateLine[];
    expect(rowsTotal([row({ quantity: "2", unitPrice: "50" }), row({ locked: true })], settled)).toBe("700.00");
  });
});

describe("answers", () => {
  it("check a counter is below what was asked and a rejection has a reason", () => {
    expect(answerProblem({ lineId: "1", state: "", amount: "", reason: "" }, "100")).toBe("state");
    expect(answerProblem({ lineId: "1", state: "countered", amount: "", reason: "" }, "100")).toBe("amount");
    expect(answerProblem({ lineId: "1", state: "countered", amount: "100", reason: "" }, "100")).toBe("amount");
    expect(answerProblem({ lineId: "1", state: "countered", amount: "60", reason: "" }, "100")).toBeNull();
    expect(answerProblem({ lineId: "1", state: "rejected", amount: "", reason: " " }, "100")).toBe("reason");
    expect(answerProblem({ lineId: "1", state: "approved", amount: "", reason: "" }, "100")).toBeNull();
  });
  it("send only answered rows", () => {
    expect(toAnswers([{ lineId: "1", state: "approved", amount: "5", reason: "" }, { lineId: "2", state: "", amount: "", reason: "" }, { lineId: "3", state: "countered", amount: "60", reason: "old" }]))
      .toEqual([{ line_id: "1", state: "approved", amount: null, reason: null }, { line_id: "3", state: "countered", amount: "60", reason: "old" }]);
  });
  it("know which lines can be answered", () => {
    const l = (over: Partial<EstimateLine>) => ({ locked: false, payer_state: "pending", ...over }) as EstimateLine;
    expect(canAnswer(l({}))).toBe(true);
    expect(canAnswer(l({ payer_state: "needs_information" }))).toBe(true);
    expect(canAnswer(l({ payer_state: "approved" }))).toBe(false);
    expect(canAnswer(l({ locked: true }))).toBe(false);
  });
});

describe("small things", () => {
  it("count whole days", () => {
    expect(daysSince("2026-10-10T08:00:00Z", new Date("2026-10-14T07:00:00Z"))).toBe(3);
    expect(daysSince(null)).toBeNull();
  });
  it("tone a status", () => {
    expect(statusTone("settled")).toBe("ok");
    expect(statusTone("open")).toBe("warn");
  });
});
