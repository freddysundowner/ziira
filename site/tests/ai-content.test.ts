import { describe, it, expect } from "vitest";
import { does, safety, strip, aiCta, pageFaq, pageHero, counts } from "../src/content/ai";
import { aiEn, solutionsFirst, solutionsMore } from "../src/content/pages/ai.en";
import { home } from "../src/content/home";
import { totals } from "../src/lib/catalog";

const everything = JSON.stringify([does, safety, strip, aiCta, pageFaq, pageHero, aiEn, solutionsFirst, solutionsMore, home]).toLowerCase();

describe("Ziira AI content tells only what is true", () => {
  it("counts come from the generated catalogue, never typed by hand", () => {
    expect(counts.checks).toBe(totals.checks);
    expect(does.lines.join(" ")).toContain(`${totals.checks} checks`);
    expect(does.lines.join(" ")).toContain(`${totals.ziira} on Ziira's own data and ${totals.connected} on a system`);
    expect(pageHero.glance[0]).toContain(String(totals.checks));
  });
  it("no invented proof: logos, awards, rankings, user counts, uptime, benchmarks, live-testing or certification", () => {
    for (const bad of ["trusted by", "award", "ranked", "#1", "number one", "best-in-class", "uptime", "99.9", "customers worldwide", "live-tested", "certified", "benchmark", "% more accurate", "million users"]) {
      expect(everything, bad).not.toContain(bad);
    }
  });
  it("no country or country-specific service in the positioning copy", () => {
    for (const bad of ["kenya", "m-pesa", "mpesa", "etims", "nairobi", "safaricom"]) expect(everything, bad).not.toContain(bad);
    expect(everything).not.toMatch(/\b(ksh|kes)\b/);
  });
  it("the page is short: five plain lines and a short list of rules, with the button that opens the assistant", () => {
    expect(does.lines.length).toBe(5);
    expect(safety.items.length).toBeLessThanOrEqual(6);
    expect(aiCta.button).toBe("Ask Ziira anything");
    expect(strip.button).toBe("Ask Ziira anything");
  });
  it("the safety rules the page states are the ones the product has", () => {
    const text = JSON.stringify([safety, pageFaq]).toLowerCase();
    for (const must of ["never moves money", "off until", "only what", "monthly", "labels"]) expect(text, must).toContain(must);
    expect(JSON.stringify(pageFaq)).toContain("Anthropic");
    expect(JSON.stringify(pageFaq)).toContain("Google Gemini");
    expect(JSON.stringify(pageFaq)).toContain("OpenAI");
  });
});
