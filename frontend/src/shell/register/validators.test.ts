import { describe, expect, it } from "vitest";

import { callingProblem, confirmProblem, emailProblem, guessCountry, nameProblem, passwordRules, passwordStrength, phoneProblem, suggestEmail, taxIdProblem } from "./validators";

describe("email", () => {
  it("checks the syntax", () => {
    expect(emailProblem("")?.code).toBe("email.required");
    expect(emailProblem("jane")?.code).toBe("email.invalid");
    expect(emailProblem("jane@x")?.code).toBe("email.invalid");
    expect(emailProblem("jane doe@x.com")?.code).toBe("email.invalid");
    expect(emailProblem(" jane@acme.test ")).toBeNull();
  });

  it("suggests the well-known domain for a typo, and only then", () => {
    expect(suggestEmail("jane@gmial.com")).toBe("jane@gmail.com");
    expect(suggestEmail("Jane@gmail.con")).toBe("jane@gmail.com");
    expect(suggestEmail("jo@hotmial.com")).toBe("jo@hotmail.com");
    expect(suggestEmail("jane@gmail.com")).toBeNull();
    expect(suggestEmail("jane@acme-traders.co.ke")).toBeNull();
    expect(suggestEmail("jane@mail.com")).toBeNull();
    expect(suggestEmail("not an email")).toBeNull();
  });
});

describe("names", () => {
  it("needs two to 120 characters with a letter", () => {
    expect(nameProblem("", "name")?.code).toBe("name.required");
    expect(nameProblem("J", "name")).toEqual({ code: "name.short", params: { min: 2 } });
    expect(nameProblem("x".repeat(121), "business")?.code).toBe("business.long");
    expect(nameProblem("--", "business")?.code).toBe("business.letters");
    expect(nameProblem("  Acme   Traders ", "business")).toBeNull();
    expect(nameProblem("Zuhura Mwangi", "name")).toBeNull();
  });
});

describe("phone", () => {
  it("is optional and counts digits between the bounds, with no country in it", () => {
    expect(phoneProblem("")).toBeNull();
    expect(phoneProblem("0712 345 678")).toBeNull();
    expect(phoneProblem("+44 (0)20 7946 0958")).toBeNull();
    expect(phoneProblem("12345")).toEqual({ code: "phone.short", params: { min: 6 } });
    expect(phoneProblem("1".repeat(16))).toEqual({ code: "phone.long", params: { max: 15 } });
    expect(phoneProblem("call me")?.code).toBe("phone.chars");
    expect(phoneProblem("123456", { min: 9 })?.code).toBe("phone.short");
  });

  it("checks a calling code", () => {
    expect(callingProblem("254")).toBeNull();
    expect(callingProblem("+44")).toBeNull();
    expect(callingProblem("")?.code).toBe("calling.invalid");
    expect(callingProblem("0044")?.code).toBe("calling.invalid");
  });
});

describe("tax number", () => {
  it("is optional, has a general shape, and a country pattern only when given", () => {
    expect(taxIdProblem("")).toBeNull();
    expect(taxIdProblem("ab")?.code).toBe("tax.shape");
    expect(taxIdProblem("GB 123 4567 89")).toBeNull();
    expect(taxIdProblem("123456789", "^[AP]\\d{9}[A-Z]$")?.code).toBe("tax.pattern");
    expect(taxIdProblem("a123456789z", "^[AP]\\d{9}[A-Z]$")).toBeNull();
    expect(taxIdProblem("ABC123", "([unclosed")).toBeNull();           // a pattern we cannot read is ignored
  });
});

describe("password", () => {
  it("reports the rules live: 8 required, 12 recommended, not the email", () => {
    expect(passwordRules("short", "")).toEqual({ length: false, long: false, notEmail: true });
    expect(passwordRules("eightchr", "")).toMatchObject({ length: true, long: false });
    expect(passwordRules("a-longer-passphrase", "")).toMatchObject({ length: true, long: true });
    expect(passwordRules("jane@acme.test", "Jane@acme.test").notEmail).toBe(false);
    expect(passwordRules("janedoe99!", "janedoe99@acme.test").notEmail).toBe(true);
    expect(passwordRules("janedoe99", "janedoe99@acme.test").notEmail).toBe(false);   // the part before the @ counts too
  });

  it("scores length and variety from 0 to 4", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("aaaaaaaa")).toBe(1);
    expect(passwordStrength("abcdefgh")).toBe(2);
    expect(passwordStrength("abcdefgh1234")).toBe(3);
    expect(passwordStrength("Correct-Horse-Battery-9")).toBe(4);
  });

  it("matches the confirmation", () => {
    expect(confirmProblem("abc", "")?.code).toBe("confirm.required");
    expect(confirmProblem("abc", "abd")?.code).toBe("confirm.mismatch");
    expect(confirmProblem("abc", "abc")).toBeNull();
  });
});

describe("guessing the country on this device", () => {
  const list = [{ code: "KE", zone: "Africa/Nairobi" }, { code: "GB", zone: "Europe/London" }, { code: "XX", zone: "UTC" }];
  it("uses the language region, then the time zone, and never a bare UTC", () => {
    expect(guessCountry(list, "en-GB", "Africa/Nairobi")).toBe("GB");
    expect(guessCountry(list, "sw", "Africa/Nairobi")).toBe("KE");
    expect(guessCountry(list, "en-US", "Europe/London")).toBe("GB");   // US is not in the list: fall back to the zone
    expect(guessCountry(list, "en", "UTC")).toBe("");
  });
});
