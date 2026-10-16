import { describe, expect, it } from "vitest";

import { bellLabel, bySeverity } from "./alerts";
import { auditQuery, exportPath, hasFilters, NO_FILTERS, rangeProblem, actionLabel } from "./audit";
import { canAct, nextStep, setupProgress, visibleSteps } from "./setup";

const step = (key: string, done: boolean, optional = false, feature: string | null = null) => ({ key, done, optional, feature, to: "/x", needs: "platform.settings", detail: null });

describe("the setup checklist", () => {
  const items = [step("email", true), step("registration", true), step("ai", false), step("payments", false), step("website", false, false, "website"), step("licence", false, true)];
  it("counts only the required steps", () => {
    expect(setupProgress(items)).toEqual({ done: 2, total: 5, complete: false });
    expect(setupProgress([step("a", true), step("b", false, true)])).toEqual({ done: 1, total: 1, complete: true });
  });
  it("leaves out the website step when the deployment has no website", () => {
    expect(visibleSteps(items, ["website"]).map((i) => i.key)).toEqual(["email", "registration", "ai", "payments", "licence"]);
    expect(setupProgress(visibleSteps(items, ["website"]))).toEqual({ done: 2, total: 4, complete: false });
  });
  it("points at the first required step still to do", () => {
    expect(nextStep(items)?.key).toBe("ai");
    expect(nextStep([step("a", true), step("b", false, true)])).toBeNull();
  });
  it("lets a role act only where it holds the permission", () => {
    expect(canAct({ needs: "platform.settings" }, ["platform.view", "platform.settings"])).toBe(true);
    expect(canAct({ needs: "platform.settings" }, ["platform.view"])).toBe(false);
  });
});

describe("alerts", () => {
  it("orders the worst first, then by name", () => {
    const sorted = bySeverity([{ key: "b", severity: "info" as const }, { key: "z", severity: "bad" as const }, { key: "a", severity: "warn" as const }, { key: "c", severity: "bad" as const }]);
    expect(sorted.map((a) => a.key)).toEqual(["c", "z", "a", "b"]);
  });
  it("shows nothing on the bell at zero and 9+ above nine", () => {
    expect([0, 1, 9, 10, 40].map(bellLabel)).toEqual([null, "1", "9", "9+", "9+"]);
  });
});

describe("audit filters", () => {
  it("sends only the filters with a value, under the API's names", () => {
    expect(auditQuery({ ...NO_FILTERS, operator: " ann ", from: "2030-05-01", outcome: "refused" })).toEqual({ operator: "ann", outcome: "refused", date_from: "2030-05-01" });
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, target: "x" })).toBe(true);
  });
  it("spots an end before a start, and builds the download address with the same filters", () => {
    expect(rangeProblem({ ...NO_FILTERS, from: "2030-05-02", to: "2030-05-01" })).toBe(true);
    expect(rangeProblem({ ...NO_FILTERS, from: "2030-05-01", to: "2030-05-01" })).toBe(false);
    expect(exportPath(NO_FILTERS)).toBe("/api/v1/operator/audit/export");
    expect(exportPath({ ...NO_FILTERS, action: "plan.", to: "2030-05-31" })).toBe("/api/v1/operator/audit/export?action=plan.&date_to=2030-05-31");
  });
  it("makes a readable name from an action code", () => {
    expect(actionLabel("plan.update")).toBe("Plan update");
    expect(actionLabel("auth.sign_in")).toBe("Auth sign in");
  });
});
