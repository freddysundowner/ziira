import { afterEach, describe, expect, it } from "vitest";

import { clearDraft, EMPTY, firstIncomplete, isValid, loadDraft, problemsOf, saveDraft, serverProblems, stepOf, type Values } from "./state";

const ctx = { passwordOk: null as boolean | null };
const filled: Values = {
  ...EMPTY, name: "Jane Doe", email: "jane@acme.test", password: "a-good-password-1", confirm: "a-good-password-1", business: "Acme Traders",
  country: "KE", currency: "KES", zone: "Africa/Nairobi", calling: "254", consent: true,
};

afterEach(() => { clearDraft(); });

describe("step gating", () => {
  it("lets the first step through at once", () => {
    expect(isValid("need", EMPTY, ctx)).toBe(true);
  });

  it("holds each step until its required answers are valid", () => {
    expect(isValid("business", { ...filled, country: "" }, ctx)).toBe(false);
    expect(isValid("business", { ...filled, business: "" }, ctx)).toBe(false);
    expect(isValid("business", filled, ctx)).toBe(true);
    expect(isValid("account", { ...filled, email: "" }, ctx)).toBe(false);
    expect(isValid("account", { ...filled, confirm: "different" }, ctx)).toBe(false);
    expect(isValid("account", { ...filled, password: "short", confirm: "short" }, ctx)).toBe(false);
    expect(isValid("account", { ...filled, consent: false }, ctx)).toBe(false);
    expect(isValid("account", filled, ctx)).toBe(true);
  });

  it("holds the account step when the server refused the password", () => {
    expect(problemsOf("account", filled, { passwordOk: false }).password?.code).toBe("password.refused");
  });

  it("finds the first step still to do", () => {
    expect(firstIncomplete(EMPTY, ctx)).toBe("business");
    expect(firstIncomplete({ ...filled, business: "" }, ctx)).toBe("business");
    expect(firstIncomplete(filled, ctx)).toBe("account");
  });
});

describe("server complaints", () => {
  it("map the server's field names to ours and to the step they belong to, in wizard order", () => {
    const mapped = serverProblems({ business_name: "too short", email: "bad email", unknown_field: "?" });
    expect(mapped.map((m) => [m.field, m.step])).toEqual([["business", "business"], ["email", "account"]]);
    expect(stepOf("timezone" as never)).toBe("account");
    expect(serverProblems({ timezone: "x", phone_country_code: "y", password: "p" }).map((m) => m.step))
      .toEqual(["business", "business", "account"]);
  });
});

describe("the draft", () => {
  it("restores the answers after a refresh and never the password", () => {
    saveDraft({ ...filled }, "business");
    const raw = sessionStorage.getItem("ziira.register.draft") ?? "";
    expect(raw).not.toContain("a-good-password-1");
    expect(JSON.parse(raw)).not.toHaveProperty("password");
    expect(JSON.parse(raw)).not.toHaveProperty("confirm");
    const restored = loadDraft();
    expect(restored?.step).toBe("business");
    expect(restored?.values).toMatchObject({ email: "jane@acme.test", business: "Acme Traders", country: "KE" });
    expect(restored?.values.password).toBe("");
    expect(restored?.values.consent).toBe(false);
  });

  it("copes with nothing saved, damaged data and cleared storage", () => {
    expect(loadDraft()).toBeNull();
    sessionStorage.setItem("ziira.register.draft", "{not json");
    expect(loadDraft()).toBeNull();
    sessionStorage.setItem("ziira.register.draft", JSON.stringify({ step: "nowhere", name: 5 }));
    expect(loadDraft()).toEqual({ values: EMPTY, step: "need" });
    saveDraft(filled, "account");
    clearDraft();
    expect(loadDraft()).toBeNull();
  });
});
