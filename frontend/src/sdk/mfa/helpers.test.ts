import { describe, expect, it } from "vitest";

import {
  classifyVerifyFailure, cleanAuthenticatorCode, formatCountdown, groupSecret, isAnyCode, isAuthenticatorCode, isBackupCodeFormat,
  isSetupRequired, normaliseAnyCode, normaliseBackupCode, retryAfterSeconds, waitMinutes,
} from "./helpers";

describe("groupSecret", () => {
  it("groups in fours and upper-cases", () => {
    expect(groupSecret("jbswy3dpehpk3pxp")).toBe("JBSW Y3DP EHPK 3PXP");
  });
  it("keeps a short last group and ignores spaces", () => {
    expect(groupSecret("ABCD EFGHI")).toBe("ABCD EFGH I");
    expect(groupSecret("")).toBe("");
  });
});

describe("countdown", () => {
  it("formats m:ss", () => {
    expect(formatCountdown(272)).toBe("4:32");
    expect(formatCountdown(59.2)).toBe("1:00");
    expect(formatCountdown(5)).toBe("0:05");
    expect(formatCountdown(-3)).toBe("0:00");
  });
  it("rounds minutes up, minimum one", () => {
    expect(waitMinutes(1)).toBe(1);
    expect(waitMinutes(61)).toBe(2);
    expect(waitMinutes(300)).toBe(5);
  });
});

describe("codes", () => {
  it("cleans a pasted authenticator code", () => {
    expect(cleanAuthenticatorCode(" 123 456 ")).toBe("123456");
    expect(cleanAuthenticatorCode("12345678")).toBe("123456");
    expect(cleanAuthenticatorCode("ab1")).toBe("1");
  });
  it("validates authenticator codes", () => {
    expect(isAuthenticatorCode("123456")).toBe(true);
    expect(isAuthenticatorCode("123 456")).toBe(true);
    expect(isAuthenticatorCode("12345")).toBe(false);
  });
  it("accepts backup codes with or without the dash and any case", () => {
    expect(isBackupCodeFormat("abcde-fghjk")).toBe(true);
    expect(isBackupCodeFormat("ABCDE FGHJK")).toBe(true);
    expect(isBackupCodeFormat("abcdefghjk")).toBe(true);
    expect(normaliseBackupCode("ABCDEFGHJK")).toBe("abcde-fghjk");
    expect(isBackupCodeFormat("abcde-fghj")).toBe(false);
    expect(isBackupCodeFormat("123456")).toBe(false);
  });
  it("accepts either kind where either works", () => {
    expect(isAnyCode("123456")).toBe(true);
    expect(isAnyCode("abcde-fghjk")).toBe(true);
    expect(isAnyCode("nope")).toBe(false);
    expect(normaliseAnyCode("123 456")).toBe("123456");
    expect(normaliseAnyCode("ABCDEFGHJK")).toBe("abcde-fghjk");
  });
});

describe("mapping API errors to screen states", () => {
  it("reads retry_after from the body, then the header, then a default", () => {
    expect(retryAfterSeconds({ retry_after: 240 }, "10")).toBe(240);
    expect(retryAfterSeconds({}, "90")).toBe(90);
    expect(retryAfterSeconds(undefined, null)).toBe(60);
  });
  it("429 is throttled", () => {
    expect(classifyVerifyFailure(429, { error: "too_many_requests", retry_after: 120 })).toEqual({ kind: "throttled", retryAfter: 120 });
  });
  it("a 401 about the token is expired; any other 401 is a wrong code", () => {
    expect(classifyVerifyFailure(401, { message: "Token expired; refresh it or sign in again" })).toEqual({ kind: "expired" });
    expect(classifyVerifyFailure(401, { message: "That is not a sign-in challenge" })).toEqual({ kind: "expired" });
    expect(classifyVerifyFailure(401, { message: "That code is not right" })).toEqual({ kind: "wrong" });
  });
  it("anything else is other", () => {
    expect(classifyVerifyFailure(503, null)).toEqual({ kind: "other" });
  });
  it("recognises the setup-required answer", () => {
    expect(isSetupRequired(403, { error: "mfa_setup_required" })).toBe(true);
    expect(isSetupRequired(403, { error: "forbidden" })).toBe(false);
    expect(isSetupRequired(401, { error: "mfa_setup_required" })).toBe(false);
  });
});
