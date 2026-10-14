import { describe, expect, it } from "vitest";

import { bandRanges, buildDefinition, emptyRule, emptySide, illustrate, inForce, percentToRate, problems, rateToPercent, ruleToForm, shiftDecimal } from "./rules";
import type { Rule } from "./types";

describe("percent and rate text", () => {
  it.each([["7.5", "0.075"], ["10", "0.1"], ["100", "1"], ["0.5", "0.005"], ["15.25", "0.1525"], ["0", "0"]])("%s%% is %s", (p, r) => {
    expect(percentToRate(p)).toBe(r);
    expect(rateToPercent(r)).toBe(p);
  });
  it("gives nothing for text that is not a number", () => {
    expect(shiftDecimal("", 2)).toBe("");
    expect(shiftDecimal("abc", 2)).toBe("");
  });
});

const banded = () => {
  const f = emptyRule("2026-01-01");
  f.code = "INCOME_TAX"; f.name = "Income tax"; f.sourceReference = "Notice 1";
  f.employee = { ...emptySide("bands"), credit: "2400", bands: [{ upTo: "24000", rate: "10" }, { upTo: "", rate: "30" }] };
  return f;
};

describe("rule definition", () => {
  it("builds the stored shape with fractions and an open last band", () => {
    expect(buildDefinition(banded())).toMatchObject({
      name: "Income tax", base: "gross", employer: null,
      employee: { method: "bands", credit: "2400", bands: [{ up_to: "24000", rate: "0.1" }, { up_to: null, rate: "0.3" }] },
    });
  });
  it("round-trips through a stored rule", () => {
    const form = banded();
    const rule = { id: "1", code: "INCOME_TAX", effective_from: "2026-01-01", effective_to: null, definition: buildDefinition(form), source_reference: "Notice 1", payable_account_id: null } as unknown as Rule;
    const back = ruleToForm(rule);
    expect(back.employee.bands.map((b) => b.rate)).toEqual(["10", "30"]);
    expect(buildDefinition(back)).toEqual(buildDefinition(form));
  });
  it("only sends the limits that were filled in", () => {
    const f = emptyRule("2026-01-01");
    f.employee = { ...emptySide("rate"), rate: "6", maximum: "1080" };
    expect(buildDefinition(f).employee).toEqual({ method: "rate", rate: "0.06", maximum: "1080" });
  });
});

describe("problems", () => {
  it("flags what is missing", () => {
    expect(problems(emptyRule("2026-01-01"))).toEqual(expect.arrayContaining(["code", "name", "source", "rate"]));
    expect(problems(banded())).toEqual([]);
  });
  it("wants band limits to increase", () => {
    const f = banded();
    f.employee.bands = [{ upTo: "100", rate: "10" }, { upTo: "50", rate: "20" }, { upTo: "", rate: "30" }];
    expect(problems(f)).toContain("bandOrder");
  });
});

describe("illustrate", () => {
  it("applies bands less the credit", () => {
    expect(illustrate(banded().employee, 30000)).toBeCloseTo(24000 * 0.1 + 6000 * 0.3 - 2400);
  });
  it("never goes below zero", () => {
    expect(illustrate(banded().employee, 10000)).toBe(0);
  });
  it("applies a rate with limits", () => {
    const side = { ...emptySide("rate"), rate: "6", maximum: "1080" };
    expect(illustrate(side, 10000)).toBe(600);
    expect(illustrate(side, 50000)).toBe(1080);
  });
});

describe("bandRanges", () => {
  it("lists each band from the end of the last", () => {
    expect(bandRanges(banded().employee.bands)).toEqual([{ from: "0", to: "24000", rate: "10" }, { from: "24000", to: null, rate: "30" }]);
  });
});

describe("inForce", () => {
  const r = (id: string, from: string, to: string | null) => ({ id, code: "A", effective_from: from, effective_to: to }) as Rule;
  it("picks the latest started version", () => {
    expect([...inForce([r("old", "2025-01-01", null), r("new", "2026-01-01", null), r("later", "2027-01-01", null)], "2026-06-01")]).toEqual(["new"]);
  });
});
