import { describe, expect, it } from "vitest";

import { byArea, changeOf, type Figure, groupFigures, keyFigure, layoutBrief, toTimeInput } from "./logic";

const fig = (over: Partial<Figure>): Figure => ({ metric: "m", label: "L", kind: "money", value: "1", previous: null, branch_id: null, branch_name: null, higher_is_better: true, ...over });

describe("changeOf", () => {
  it("is green when a higher-is-better figure rises and red when it falls", () => {
    expect(changeOf("120", "100", true)).toMatchObject({ direction: "up", tone: "ok", percent: 20 });
    expect(changeOf("80", "100", true)).toMatchObject({ direction: "down", tone: "bad", percent: -20 });
  });
  it("flips the colours when lower is better", () => {
    expect(changeOf("5", "10", false).tone).toBe("ok");
    expect(changeOf("15", "10", false).tone).toBe("bad");
  });
  it("stays neutral when it does not matter, when flat, or when there is no day before", () => {
    expect(changeOf("12", "10", null).tone).toBe("neutral");
    expect(changeOf("100.2", "100", true).direction).toBe("flat");
    expect(changeOf("5", null, true).direction).toBe("none");
  });
  it("has no percent when yesterday was zero", () => {
    expect(changeOf("5", "0", true)).toMatchObject({ direction: "up", percent: null, tone: "ok" });
  });
});

describe("groupFigures", () => {
  it("puts company figures first and branches by name", () => {
    const g = groupFigures([fig({ metric: "a", branch_id: "b2", branch_name: "Juja" }), fig({ metric: "b" }), fig({ metric: "c", branch_id: "b1", branch_name: "Head office" }), fig({ metric: "d", branch_id: "b2", branch_name: "Juja" })]);
    expect(g.company.map((f) => f.metric)).toEqual(["b"]);
    expect(g.branches.map((b) => [b.name, b.figures.length])).toEqual([["Head office", 1], ["Juja", 2]]);
  });
  it("finds the first company-wide money figure", () => {
    expect(keyFigure([fig({ metric: "x", branch_id: "b" }), fig({ metric: "n", kind: "count" }), fig({ metric: "k" })])?.metric).toBe("k");
    expect(keyFigure([])).toBeUndefined();
  });
});

describe("brief text", () => {
  it("trims a time for the input", () => expect(toTimeInput("07:30:00")).toBe("07:30"));
  it("lays out title, headed sections and numbered items", () => {
    const l = layoutBrief("Shop: daily brief, 2026-10-14\n\nYesterday\n- Sales: KES 10 (up 5%)\n- Cash: KES 3\n\nNeeds your attention\n1. [high] Gap. Next: count\n...and 2 more in the Command Center.");
    expect(l.title).toContain("daily brief");
    expect(l.sections[0]).toEqual({ heading: "Yesterday", items: [{ kind: "bullet", text: "Sales: KES 10 (up 5%)" }, { kind: "bullet", text: "Cash: KES 3" }] });
    expect(l.sections[1].heading).toBe("Needs your attention");
    expect(l.sections[1].items.map((i) => i.kind)).toEqual(["numbered", "text"]);
  });
  it("keeps a lone sentence as text", () => {
    expect(layoutBrief("T\n\nNothing needs your attention.").sections).toEqual([{ heading: null, items: [{ kind: "text", text: "Nothing needs your attention." }] }]);
  });
});


describe("byArea", () => {
  const f = (metric: string) => ({ metric, label: metric, kind: "count", value: "1", previous: null, branch_id: null, branch_name: null, higher_is_better: null }) as never;
  it("groups figures by the unit that supplied them, in a fixed order, unknown units last", () => {
    const groups = byArea([f("people.headcount"), f("zzz.thing"), f("pos.sales_total"), f("pos.sales_count"), f("inventory.stock_value")]);
    expect(groups.map((g) => g.area)).toEqual(["pos", "inventory", "people", "zzz"]);
    expect(groups[0]!.figures).toHaveLength(2);
  });
});
