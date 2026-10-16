import { describe, expect, it } from "vitest";

import { NAV_GROUPS } from "../nav";
import { groupHits, matchPages, moveIndex, pageHits } from "./search";

const label = (id: string) => ({ plans: "Plans & pricing", methods: "Payment methods", audit: "Audit trail", settings: "Platform settings", email: "Email", setup: "Setup checklist" }[id] ?? id);
const pages = (permissions: string[], missing: string[] = []) => pageHits(NAV_GROUPS, permissions, missing, label, (k) => k);

describe("searching the console's own screens", () => {
  it("lists only screens the role may open", () => {
    const view = pages(["platform.view"]).map((p) => p.id);
    expect(view).toContain("plans");
    expect(view).not.toContain("audit");
    expect(view).not.toContain("email");
    expect(pages(["platform.view", "platform.operators"]).map((p) => p.id)).toContain("audit");
  });
  it("hides the website screens when the deployment has no website", () => {
    expect(pages(["platform.view", "platform.content"], ["website"]).map((p) => p.id)).not.toContain("sitePages");
    expect(pages(["platform.view", "platform.content"]).map((p) => p.id)).toContain("sitePages");
  });
  it("finds a screen by its name, by a keyword, or by words in any order", () => {
    const all = pages(["platform.view", "platform.settings", "platform.operators"]);
    expect(matchPages(all, "payment").map((p) => p.id)).toEqual(["invoices", "methods", "attempts"]);
    expect(matchPages(all, "registration mode").map((p) => p.id)).toEqual(["settings"]);          // a keyword of Platform settings
    expect(matchPages(all, "TRAIL AUDIT").map((p) => p.id)).toEqual(["audit"]);
    expect(matchPages(all, "where do i find").map((p) => p.id)).toEqual(["setup"]);
  });
  it("finds nothing for fewer than two characters", () => {
    expect(matchPages(pages(["platform.view"]), "p")).toEqual([]);
    expect(matchPages(pages(["platform.view"]), "   ")).toEqual([]);
  });
});

describe("the result list", () => {
  it("groups hits by kind in the order asked and drops empty kinds", () => {
    const hits = [{ kind: "invoice", id: "1" }, { kind: "subscriber", id: "2" }, { kind: "invoice", id: "3" }, { kind: "plan", id: "4" }];
    expect(groupHits(hits, ["page", "subscriber", "invoice", "plan"]).map((g) => [g.kind, g.hits.map((h) => h.id)])).toEqual([["subscriber", ["2"]], ["invoice", ["1", "3"]], ["plan", ["4"]]]);
  });
  it("moves the highlight with the arrow keys and wraps", () => {
    expect([moveIndex(0, 1, 3), moveIndex(2, 1, 3), moveIndex(0, -1, 3), moveIndex(0, 1, 0)]).toEqual([1, 0, 2, 0]);
  });
});
