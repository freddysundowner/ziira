import { describe, expect, it } from "vitest";

import { emptyPlanForm, highlightLines, planProblems, planToForm, toPlanIn, toPlanPatch } from "./plan";

const valid = () => ({ ...emptyPlanForm(), code: "pro", name: "Pro", units: ["products"] });

describe("plan form validation", () => {
  it("accepts a code, a name and the defaults", () => {
    expect(planProblems(valid(), true)).toEqual({});
  });
  it("needs a well-formed code only when creating", () => {
    expect(planProblems({ ...valid(), code: "Pro Plan" }, true).code).toBe("code");
    expect(planProblems({ ...valid(), code: "x" }, true).code).toBe("code");
    expect(planProblems({ ...valid(), code: "" }, false)).toEqual({});
  });
  it("needs at least one unit ticked", () => {
    expect(planProblems({ ...valid(), units: [] }, true).units).toBe("units");
    expect(planProblems({ ...valid(), units: [], edition: "retail" }, true)).toEqual({});
  });
  it("needs a name", () => {
    expect(planProblems({ ...valid(), name: "  " }, true).name).toBe("nameRequired");
    expect(planProblems({ ...valid(), name: "x".repeat(81) }, true).name).toBe("nameLong");
  });
  it("treats an empty limit as unlimited and refuses zero or text", () => {
    expect(planProblems({ ...valid(), max_users: "" }, true)).toEqual({});
    expect(planProblems({ ...valid(), max_users: "0" }, true).max_users).toBe("limit");
    expect(planProblems({ ...valid(), max_branches: "two" }, true).max_branches).toBe("limit");
    expect(planProblems({ ...valid(), limits: { storage_mb: "-1" } }, true).storage_mb).toBe("limit");
  });
  it("keeps trial days, order, intervals and highlights in range", () => {
    expect(planProblems({ ...valid(), trial_days: "400" }, true).trial_days).toBe("trialDays");
    expect(planProblems({ ...valid(), trial_days: "" }, true).trial_days).toBe("trialDays");
    expect(planProblems({ ...valid(), sort_order: "x" }, true).sort_order).toBe("sortOrder");
    expect(planProblems({ ...valid(), intervals: [] }, true).intervals).toBe("intervals");
    expect(planProblems({ ...valid(), highlights: Array.from({ length: 13 }, (_, i) => `line ${i}`).join("\n") }, true).highlights).toBe("highlights");
  });
});

describe("plan request bodies", () => {
  it("makes a new plan's request with numbers, null for unlimited and clean lists", () => {
    const body = toPlanIn({ ...valid(), code: " pro ", max_users: "10", highlights: "One\n\n Two ", limits: { storage_mb: "500", api_requests_per_day: "" }, edition: "" });
    expect(body).toMatchObject({ code: "pro", name: "Pro", max_users: 10, max_branches: null, edition: null, highlights: ["One", "Two"], limits: { storage_mb: 500 }, trial_days: 0 });
  });
  it("sends an emptied limit as null in a change, and the retired state", () => {
    const patch = toPlanPatch({ ...valid(), max_users: "", status: "retired" });
    expect(patch.max_users).toBeNull();
    expect(patch.status).toBe("retired");
    expect("code" in patch).toBe(false);
  });
  it("loads a stored plan into the form and back", () => {
    const form = planToForm({
      code: "pro", name: "Pro", description: "d", edition: "retail", units: ["pos"], addon_units: [], max_users: 5, max_branches: null, max_companies: null,
      limits: { storage_mb: 100, api_requests_per_day: null }, highlights: ["a", "b"], trial_days: 14, intervals: ["month", "weird"], sort_order: 10, is_public: true, status: "retired",
    });
    expect(form).toMatchObject({ max_users: "5", max_branches: "", limits: { storage_mb: "100" }, highlights: "a\nb", intervals: ["month"], status: "retired" });
    expect(toPlanPatch(form)).toMatchObject({ max_users: 5, limits: { storage_mb: 100 }, edition: "retail", trial_days: 14 });
  });
  it("splits highlights by line", () => {
    expect(highlightLines(" a \n\nb")).toEqual(["a", "b"]);
  });
});
