import { describe, expect, it } from "vitest";

import { dunningFromDraft, dunningToDraft, numberValue, parseOffsets, taxLinesFromDraft, taxLinesToDraft } from "./settings";

describe("settings drafts", () => {
  it("sends whole numbers as numbers and leaves the rest for the server to refuse", () => {
    expect(numberValue(" 14 ")).toBe(14);
    expect(numberValue("-3")).toBe(-3);
    expect(numberValue("1.5")).toBe("1.5");
    expect(numberValue("")).toBe("");
  });

  it("reads reminder offsets from a comma or space separated list", () => {
    expect(parseOffsets("-7, 0 3;7")).toEqual([-7, 0, 3, 7]);
    expect(parseOffsets("2, soon")).toEqual([2, "soon"]);
    expect(parseOffsets("")).toEqual([]);
  });

  it("round-trips the dunning schedule", () => {
    const stored = { reminders: [-7, 0, 3], past_due_after_days: 1, grace_after_days: 7, suspend_after_days: 21, expire_after_days: 90 };
    expect(dunningFromDraft(dunningToDraft(stored))).toEqual(stored);
  });

  it("drops blank tax rows and trims the rest", () => {
    const draft = taxLinesToDraft([{ name: "Sales tax", rate_percent: "16" }]);
    expect(draft).toEqual([{ name: "Sales tax", rate_percent: "16" }]);
    expect(taxLinesFromDraft([...draft, { name: " ", rate_percent: "" }, { name: " Levy ", rate_percent: " 2 " }])).toEqual([
      { name: "Sales tax", rate_percent: "16" }, { name: "Levy", rate_percent: "2" },
    ]);
  });
});
