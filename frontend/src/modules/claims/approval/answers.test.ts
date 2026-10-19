import { describe, expect, it } from "vitest";

import type { PublicLine } from "./api";
import { EMPTY_PICK, openLines, pickProblem, signOffProblems, toBody } from "./answers";

const line = (over: Partial<PublicLine>): PublicLine => ({ id: "a", position: 1, kind: "parts", description: "Bumper", quantity: "1", unit_price: "100", total: "100.00", part_class: null, locked: false, state: "pending", amount: null, reason: null, ...over });

describe("the payer's answers", () => {
  it("only ask about lines that are not settled", () => {
    const lines = [line({ id: "1" }), line({ id: "2", locked: true, state: "approved" }), line({ id: "3", state: "needs_information" }), line({ id: "4", state: "rejected" })];
    expect(openLines(lines).map((l) => l.id)).toEqual(["1", "3"]);
  });
  it("check each answer", () => {
    expect(pickProblem(EMPTY_PICK, "100.00")).toBe("state");
    expect(pickProblem({ state: "approved", amount: "", reason: "" }, "100.00")).toBeNull();
    expect(pickProblem({ state: "countered", amount: "", reason: "" }, "100.00")).toBe("amount");
    expect(pickProblem({ state: "countered", amount: "100", reason: "" }, "100.00")).toBe("amount");
    expect(pickProblem({ state: "countered", amount: "99.99", reason: "" }, "100.00")).toBeNull();
    expect(pickProblem({ state: "rejected", amount: "", reason: "" }, "100.00")).toBe("reason");
    expect(pickProblem({ state: "needs_information", amount: "", reason: "" }, "100.00")).toBeNull();
  });
  it("list what stops the sign-off, name included", () => {
    const lines = [line({ id: "1" }), line({ id: "2" })];
    const found = signOffProblems(lines, { "1": { state: "approved", amount: "", reason: "" } }, " ");
    expect(found).toEqual({ lines: { "2": "state" }, name: true });
    expect(signOffProblems(lines, { "1": { state: "approved", amount: "", reason: "" }, "2": { state: "approved", amount: "", reason: "" } }, "Grace")).toEqual({ lines: {}, name: false });
  });
  it("send the answers of the open lines only", () => {
    const lines = [line({ id: "1" }), line({ id: "2", locked: true, state: "approved" })];
    const body = toBody(lines, { "1": { state: "countered", amount: " 60 ", reason: "old part" } }, { name: " Grace ", role: "", note: "", authority: "LPO-1", authorityAmount: "" });
    expect(body).toEqual({ name: "Grace", role: null, note: null, authority_ref: "LPO-1", authority_amount: null, lines: [{ line_id: "1", state: "countered", amount: "60", reason: "old part" }] });
  });
});
