import { describe, expect, it } from "vitest";

import { groupByUnit, toggleScopes } from "./scopes";

const p = (code: string, unit_name: string) => ({ code, unit_name, description: "" });

describe("API key scopes", () => {
  it("groups permissions by unit, units in order", () => {
    const groups = groupByUnit([p("b.view", "b"), p("a.view", "a"), p("b.edit", "b")]);
    expect(groups.map((g) => g.unit)).toEqual(["a", "b"]);
    expect(groups[1]!.permissions.map((x) => x.code)).toEqual(["b.view", "b.edit"]);
  });
  it("adds and removes scopes without duplicates", () => {
    expect(toggleScopes(["a"], ["a", "b"], true).sort()).toEqual(["a", "b"]);
    expect(toggleScopes(["a", "b", "c"], ["a", "b"], false)).toEqual(["c"]);
  });
});
