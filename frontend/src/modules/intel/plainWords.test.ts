import { describe, expect, it } from "vitest";

import { bandOf, daySummary, factsOf, formatFact, ignoreScopes, limitsOutsideSentence, numericText, presetFor, recordPath, splitSentence, TOPIC_KEYS } from "./plainWords";

const words = { yes: "Yes", no: "No" };

describe("bandOf", () => {
  it("speaks in urgent, soon and worth a look", () => {
    expect(["critical", "high", "medium", "low", "info", "odd"].map(bandOf)).toEqual(["urgent", "urgent", "soon", "look", "look", "look"]);
  });
});

describe("numericText and formatFact", () => {
  it("reads numbers written with thousands commas, and nothing else", () => {
    expect(numericText("12,345.50")).toBe(12345.5);
    expect(numericText("-3")).toBe(-3);
    expect(numericText("KES 1,200.00")).toBeNull();
    expect(numericText("9 of 10")).toBeNull();
  });
  it("shows money with two decimals in the company currency", () => {
    expect(formatFact("64011.6", "money", "KES", words)).toMatch(/64,011\.60/);
    expect(formatFact("12,345.5", "money", "USD", words)).toMatch(/12,345\.50/);
    expect(formatFact("KES 1,200.00", "money", "KES", words)).toBe("KES 1,200.00");
  });
  it("shows counts and days whole, percentages with one decimal, dates like 13 Oct 2026", () => {
    expect(formatFact("67", "days", undefined, words)).toBe("67");
    expect(formatFact("3.0", "count", undefined, words)).toBe("3");
    expect(formatFact("12.34", "percent", undefined, words)).toBe("12.3%");
    expect(formatFact("2026-10-13", "date", undefined, words)).toMatch(/13/);
    expect(formatFact("2026-10-13", "date", undefined, words)).toMatch(/2026/);
  });
  it("shows yes and no in words and anything unexpected as written", () => {
    expect(formatFact("yes", "yesno", undefined, words)).toBe("Yes");
    expect(formatFact("false", "yesno", undefined, words)).toBe("No");
    expect(formatFact("Mary W", "text", undefined, words)).toBe("Mary W");
    expect(formatFact("n/a", "count", undefined, words)).toBe("n/a");
  });
});

describe("factsOf", () => {
  const meta = {
    bills: { label: "Bills", kind: "count" }, oldest_days: { label: "Oldest, in days", kind: "days" }, owed: { label: "Owed", kind: "money" },
    by: { label: "By", kind: "text" }, currency: { label: "Currency", kind: "text" },
  };
  it("puts money first, then counts and days, and keeps the order otherwise", () => {
    expect(factsOf({ by: "Mary", bills: "3", owed: "10", oldest_days: "67" }, meta).map((f) => f.key)).toEqual(["owed", "bills", "oldest_days", "by"]);
  });
  it("leaves out ids, empty values, the currency code and figures nobody has named", () => {
    expect(factsOf({ by: "0c96118a-b769-4091-8415-7633d0d27b06", bills: "", currency: "KES", mystery: "1", owed: "5" }, meta).map((f) => f.key)).toEqual(["owed"]);
  });
  it("shows at most as many as asked for", () => {
    expect(factsOf({ bills: "1", owed: "2", oldest_days: "3" }, meta, 2)).toHaveLength(2);
  });
});

describe("sentences with limits in them", () => {
  const sentence = "Tell me when a customer is more than {min_days_overdue} days late, and {high_days_overdue} is urgent.";
  it("splits a sentence into words and the limits to edit", () => {
    expect(splitSentence(sentence)).toEqual([
      { kind: "text", text: "Tell me when a customer is more than " }, { kind: "param", name: "min_days_overdue" },
      { kind: "text", text: " days late, and " }, { kind: "param", name: "high_days_overdue" }, { kind: "text", text: " is urgent." },
    ]);
    expect(splitSentence("No limits here.")).toEqual([{ kind: "text", text: "No limits here." }]);
    expect(splitSentence("{a}")).toEqual([{ kind: "param", name: "a" }]);
  });
  it("lists the limits the sentence does not name", () => {
    expect(limitsOutsideSentence(sentence, ["min_days_overdue", "days", "high_days_overdue"])).toEqual(["days"]);
    expect(limitsOutsideSentence(null, ["days"])).toEqual(["days"]);
  });
});

describe("what Today says", () => {
  it("says nothing needs you, some do, or all are urgent", () => {
    expect(daySummary(0, 0)).toEqual({ need: 0, urgent: 0, tone: "none" });
    expect(daySummary(3, 2)).toEqual({ need: 3, urgent: 2, tone: "some" });
    expect(daySummary(2, 2).tone).toBe("all");
    expect(daySummary(1, 5)).toEqual({ need: 1, urgent: 1, tone: "all" });
    expect(daySummary(4, 0).tone).toBe("some");
  });
});

describe("presets", () => {
  it("suits the edition and defaults to everything", () => {
    expect(presetFor("retail")).toEqual(["cash", "stock", "customers", "staff"]);
    expect(presetFor("full")).toEqual([...TOPIC_KEYS]);
    expect(presetFor(undefined)).toEqual([...TOPIC_KEYS]);
  });
});

describe("not a problem", () => {
  it("offers the branch and the person only when the thing is about one, and always everywhere", () => {
    expect(ignoreScopes({ branch: { name: "Ruiru" }, subject: { label: "Mary" } })).toEqual(["branch", "person", "everywhere"]);
    expect(ignoreScopes({ branch: null, subject: null })).toEqual(["everywhere"]);
    expect(ignoreScopes({ branch: { name: "Ruiru" }, subject: null })).toEqual(["branch", "everywhere"]);
  });
  it("links records that have their own page", () => {
    expect(recordPath({ type: "pos.sale", id: "abc" })).toBe("/pos/sales/abc");
    expect(recordPath({ type: "kernel.app_user", id: "abc" })).toBeNull();
    expect(recordPath({ type: "pos.sale", id: null })).toBeNull();
  });
});
