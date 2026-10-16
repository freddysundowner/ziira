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
    expect(isValid("about", EMPTY, ctx)).toBe(false);
    expect(isValid("about", { ...EMPTY, name: "Jane Doe", email: "jane@acme.test" }, ctx)).toBe(true);
    expect(isValid("about", { ...EMPTY, name: "Jane Doe", email: "jane@acme.test", phone: "12" }, ctx)).toBe(false);
    expect(isValid("password", { ...filled, confirm: "different" }, ctx)).toBe(false);
    expect(isValid("password", { ...filled, password: "short", confirm: "short" }, ctx)).toBe(false);
    expect(isValid("password", filled, ctx)).toBe(true);
    expect(isValid("business", { ...filled, country: "" }, ctx)).toBe(false);
    expect(isValid("business", filled, ctx)).toBe(true);
    expect(isValid("review", { ...filled, consent: false }, ctx)).toBe(false);
    expect(isValid("review", filled, ctx)).toBe(true);
  });

  it("holds the password step when the server refused the password", () => {
    expect(problemsOf("password", filled, { passwordOk: false }).password?.code).toBe("password.refused");
  });

  it("checks the tax number against the country's pattern only when there is one", () => {
    const withTax = { ...filled, tax: "123456789" };
    expect(isValid("business", withTax, ctx)).toBe(true);
    expect(isValid("business", withTax, { ...ctx, taxPattern: "^[AP]\\d{9}[A-Z]$" })).toBe(false);
  });

  it("finds the first step still to do", () => {
    expect(firstIncomplete(EMPTY, ctx)).toBe("about");
    expect(firstIncomplete({ ...filled, password: "" , confirm: ""}, ctx)).toBe("password");
    expect(firstIncomplete(filled, ctx)).toBe("review");
  });
});

describe("server complaints", () => {
  it("map the server's field names to ours and to the step they belong to, in wizard order", () => {
    const mapped = serverProblems({ business_name: "too short", email: "bad email", owner_role: "nope", unknown_field: "?" });
    expect(mapped.map((m) => [m.field, m.step])).toEqual([["email", "about"], ["role", "about"], ["business", "business"]]);
    expect(stepOf("timezone" as never)).toBe("review");
    expect(serverProblems({ timezone: "x", phone_country_code: "y", tax_id: "z", password: "p" }).map((m) => m.step))
      .toEqual(["password", "business", "business", "business"]);
  });
});

describe("the draft", () => {
  it("restores the answers after a refresh and never the password", () => {
    saveDraft({ ...filled, phone: "0712 345 678", role: "accountant" }, "business");
    const raw = sessionStorage.getItem("ziira.register.draft") ?? "";
    expect(raw).not.toContain("a-good-password-1");
    expect(JSON.parse(raw)).not.toHaveProperty("password");
    expect(JSON.parse(raw)).not.toHaveProperty("confirm");
    const restored = loadDraft();
    expect(restored?.step).toBe("business");
    expect(restored?.values).toMatchObject({ name: "Jane Doe", email: "jane@acme.test", business: "Acme Traders", phone: "0712 345 678", role: "accountant", country: "KE" });
    expect(restored?.values.password).toBe("");
    expect(restored?.values.consent).toBe(false);
  });

  it("copes with nothing saved, damaged data and cleared storage", () => {
    expect(loadDraft()).toBeNull();
    sessionStorage.setItem("ziira.register.draft", "{not json");
    expect(loadDraft()).toBeNull();
    sessionStorage.setItem("ziira.register.draft", JSON.stringify({ step: "nowhere", name: 5 }));
    expect(loadDraft()).toEqual({ values: EMPTY, step: "need" });
    saveDraft(filled, "review");
    clearDraft();
    expect(loadDraft()).toBeNull();
  });
});
