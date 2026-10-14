import { describe, expect, it } from "vitest";

import { allModules } from "./index";

function keys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]);
}

describe("built-in modules", () => {
  it("each mirror a different backend unit", () => {
    const units = allModules.map((m) => m.unit);
    expect(new Set(units).size).toBe(units.length);
  });
  it.each(allModules.filter((m) => m.translations).map((m) => [m.unit, m] as const))(
    "%s has the same English and Swahili keys", (_, m) => {
      expect(keys(m.translations!.sw).sort()).toEqual(keys(m.translations!.en).sort());
    });
  it("give every page a permission", () => {
    expect(allModules.flatMap((m) => m.routes ?? []).filter((r) => !r.permission && !r.anySignedIn)).toEqual([]);
  });
});
