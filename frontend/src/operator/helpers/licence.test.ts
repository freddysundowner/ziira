import { describe, expect, it } from "vitest";

import { emptyLicenceForm, licenceProblems, toLicenceIn } from "./licence";

const ok = () => ({ ...emptyLicenceForm(), customer: "Acme Ltd", plan_code: "pro", valid_until: "2027-01-31" });

describe("licence form", () => {
  it("accepts a customer, a plan and an end date", () => {
    expect(licenceProblems(ok())).toEqual({});
  });
  it("needs an end date unless the licence is perpetual", () => {
    expect(licenceProblems({ ...ok(), valid_until: "" }).valid_until).toBe("validUntil");
    expect(licenceProblems({ ...ok(), valid_until: "", perpetual: true })).toEqual({});
  });
  it("needs a plan, or an edition or units", () => {
    expect(licenceProblems({ ...ok(), plan_code: "" }).plan_code).toBe("plan");
    expect(licenceProblems({ ...ok(), basis: "units" }).units).toBe("units");
    expect(licenceProblems({ ...ok(), basis: "units", units: ["pos"] })).toEqual({});
  });
  it("checks the customer, email, limits and grace days", () => {
    expect(licenceProblems({ ...ok(), customer: "A" }).customer).toBe("customer");
    expect(licenceProblems({ ...ok(), contact_email: "nope" }).contact_email).toBe("email");
    expect(licenceProblems({ ...ok(), max_users: "0" }).max_users).toBe("limit");
    expect(licenceProblems({ ...ok(), grace_days: "400" }).grace_days).toBe("grace");
  });
  it("sends the plan or the units, never both, and null for perpetual", () => {
    const byPlan = toLicenceIn({ ...ok(), units: ["pos"], edition: "retail", perpetual: true, max_users: "5" });
    expect(byPlan).toMatchObject({ plan_code: "pro", edition: null, units: [], valid_until: null, max_users: 5, max_branches: null, grace_days: 30 });
    const byUnits = toLicenceIn({ ...ok(), basis: "units", units: ["pos"], edition: "retail" });
    expect(byUnits).toMatchObject({ plan_code: null, edition: "retail", units: ["pos"] });
  });
});
