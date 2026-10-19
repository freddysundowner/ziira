import { describe, it, expect } from "vitest";
import { pack, BANNED, MAX_WORDS, MIN_WORDS, words, safe } from "../src/lib/knowledgePack";

const para = (n: number, w = "word") => Array.from({ length: n }, (_, i) => `${w}${i}`).join(" ") + ".";

describe("assistant knowledge packing (the built file is audited by scripts/lib/rules.mjs: assistant-knowledge)", () => {
  it("cuts text into chunks of 150 to 300 words and never above 300", () => {
    const chunks = pack([para(120), para(100), para(90), para(400), para(60)]);
    for (const c of chunks) expect(words(c)).toBeLessThanOrEqual(MAX_WORDS);
    expect(chunks.filter((c) => words(c) >= MIN_WORDS).length).toBeGreaterThanOrEqual(chunks.length - 1);
    expect(words(chunks.join(" "))).toBe(120 + 100 + 90 + 400 + 60);
  });
  it("drops a sentence with a country, a country-specific service or invented proof, and keeps the rest", () => {
    expect(safe("It works in Kenya. Plans start small. Trusted by thousands.")).toBe("Plans start small.");
    for (const bad of ["M-Pesa", "eTIMS", "Nairobi", "Safaricom", "award-winning award", "99.9% uptime", "certified", "benchmark"]) expect(BANNED.test(bad), bad).toBe(true);
    expect(BANNED.test("Certifications are not claimed. Ziira never moves money.")).toBe(false);
  });
});
