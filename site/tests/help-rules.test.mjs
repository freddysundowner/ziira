// The SEO audit rules for Help guides (scripts/lib/rules.mjs, "help guides"): each rule is tested by breaking exactly one thing in a known-good guide page.
import { describe, it, expect, afterAll } from "vitest";
import fs from "node:fs";
import { auditSite } from "../scripts/lib/rules.mjs";
import { baseSpec, writeSite, ORIGIN } from "./fixture.mjs";

const PATH = "/help/sell/first-sale/";
const dirs = [];

const steps = (n = 3, img = true) => Array.from({ length: n }, (_, i) => `<li id="step-${i + 1}"><p class="do">Do thing ${i + 1}</p>${img && i === 0 ? '<figure><img src="/og/x.png" alt="The till screen" width="10" height="10"></figure>' : ""}</li>`).join("");
const problems = (n = 3) => Array.from({ length: n }, (_, i) => `<div class="problem"><h3>Problem ${i + 1}</h3><p>Fix ${i + 1}</p></div>`).join("");
const howTo = (n = 3, extra = {}) => ({ "@type": "HowTo", name: "Make your first sale", totalTime: "PT15M", step: Array.from({ length: n }, (_, i) => ({ "@type": "HowToStep", position: i + 1, name: `Do thing ${i + 1}`, text: `Do thing ${i + 1}` })), ...extra });

function guideSpec(o = {}) {
  const ld = o.ld !== undefined ? o.ld : JSON.stringify({
    "@context": "https://schema.org",
    "@graph": [{ "@type": "Organization", name: "Z", url: ORIGIN + "/" }, { "@type": "BreadcrumbList", itemListElement: [] }, ...(o.noHowTo ? [] : [howTo(o.howToSteps ?? 3)])],
  });
  const body = `<article class="help-guide" data-help-guide>
    <section id="before"><h2>Before you start</h2>${o.noNeed ? "" : '<ul class="help-need"><li>A product</li></ul>'}</section>
    <section id="steps"><h2>Steps</h2><ol class="help-steps">${steps(o.steps ?? 3, !o.noImg)}</ol></section>
    <section id="problems"><h2>If something goes wrong</h2>${problems(o.problems ?? 3)}</section>
    <section id="next" class="help-next"><h2>Next steps</h2>${o.noNext ? "" : '<ul><li><a href="/about/">About Ziira</a></li></ul>'}</section>
  </article>`;
  return { lang: "en", title: "Make Your First Sale in Ziira", desc: "Open a till, add a product and take payment for your first sale in about fifteen minutes.", h1: ["Make your first sale"], links: ["/"], crumbs: true, body, ld };
}

const run = (mutate) => {
  const spec = baseSpec();
  spec.pages[PATH] = guideSpec();
  spec.pages["/"].links.push(PATH); // not an orphan
  mutate?.(spec);
  const dir = writeSite(spec);
  dirs.push(dir);
  return auditSite(dir, { noindexAllowed: ["/404/"] }).issues;
};
afterAll(() => dirs.forEach((d) => fs.rmSync(d, { recursive: true, force: true })));
const rules = (issues) => [...new Set(issues.map((i) => i.rule))];

describe("a known-good help guide", () => {
  it("passes every rule", () => expect(run()).toEqual([]));
});

const cases = [
  ["fewer than three numbered steps", "help-steps-missing", { steps: 2, howToSteps: 2 }],
  ["no problems listed", "help-problems-missing", { problems: 0 }],
  ["more than three problems", "help-problems-missing", { problems: 4 }],
  ['no "Next steps" link', "help-next-missing", { noNext: true }],
  ["no HowTo structured data", "help-howto-missing", { noHowTo: true }],
  ["HowTo with a different number of steps than the page", "help-howto-mismatch", { howToSteps: 4 }],
];
describe("each help rule fires", () => {
  for (const [name, rule, opts] of cases) {
    it(`${name} -> ${rule}`, () => {
      const issues = run((s) => { s.pages[PATH] = guideSpec(opts); });
      expect(rules(issues)).toContain(rule);
    });
  }
  it("HowTo steps without text -> help-howto-mismatch", () => {
    const ld = JSON.stringify({ "@context": "https://schema.org", "@graph": [{ "@type": "Organization", name: "Z" }, { "@type": "BreadcrumbList" }, howTo(3, { step: [{ "@type": "HowToStep", name: "a" }, { "@type": "HowToStep", name: "b" }, { "@type": "HowToStep", name: "c" }] })] });
    expect(rules(run((s) => { s.pages[PATH] = guideSpec({ ld }); }))).toContain("help-howto-mismatch");
  });
  it("an unlinked help guide is an orphan", () => {
    const issues = run((s) => { s.pages["/"].links = s.pages["/"].links.filter((l) => l !== PATH); });
    expect(rules(issues)).toContain("orphan-page");
  });
  it("does not apply to pages that are not help guides", () => {
    const issues = run((s) => { s.pages[PATH].body = "<p>plain page</p>"; });
    expect(rules(issues).filter((r) => r.startsWith("help-"))).toEqual([]);
  });
});
