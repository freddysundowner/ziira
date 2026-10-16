import { describe, expect, it } from "vitest";

import { actionsFor, ageLabel, backupTone, reasonOk } from "./lib";

describe("actionsFor", () => {
  it("offers Install for a unit the platform does not have yet", () => {
    expect(actionsFor({ status: "available", kind: "plugin" })).toEqual(["install"]);
  });
  it("offers Upgrade and Uninstall when a newer version is on disk", () => {
    expect(actionsFor({ status: "needs_upgrade", kind: "module" })).toEqual(["upgrade", "uninstall"]);
  });
  it("never offers to uninstall the kernel", () => {
    expect(actionsFor({ status: "installed", kind: "kernel" })).toEqual([]);
    expect(actionsFor({ status: "needs_upgrade", kind: "kernel" })).toEqual(["upgrade"]);
  });
});

describe("ageLabel", () => {
  it("reads naturally", () => {
    expect(ageLabel(20)).toBe("20 s");
    expect(ageLabel(600)).toBe("10 min");
    expect(ageLabel(7200)).toBe("2 h");
    expect(ageLabel(3 * 86400)).toBe("3 d");
    expect(ageLabel(null)).toBe("-");
  });
});

describe("backupTone", () => {
  it("is fine within a day, worrying after, bad when unknown or old", () => {
    expect(backupTone(5)).toBe("ok");
    expect(backupTone(40)).toBe("warn");
    expect(backupTone(100)).toBe("bad");
    expect(backupTone(null)).toBe("bad");
  });
});

describe("reasonOk", () => {
  it("needs a few real characters", () => {
    expect(reasonOk("  hi ")).toBe(false);
    expect(reasonOk("Pilot of the till")).toBe(true);
  });
});
