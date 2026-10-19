import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";

const read = (p: string) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
const launcher = read("public/assistant.js");
const chat = read("public/assistant-chat.js");
const base = read("src/layouts/Base.astro");

describe("Ask Ziira is always there", () => {
  it("the launcher does not read `enabled` to decide whether to show the button", () => {
    const init = /function init\(\)\s*\{([^}]*)\}/.exec(launcher)?.[1] ?? "";
    expect(init.trim()).toBe("start();");
    expect(init).not.toMatch(/enabled|getConfig/);
    // the only place `enabled` appears is when the answer is cached: a usable answer, never a gate on the button
    for (const line of launcher.split("\n").filter((l) => /\.enabled/.test(l))) expect(line).not.toMatch(/start\(\)/);
    expect(launcher).not.toMatch(/if\s*\(\s*c\.enabled\s*\)\s*start/);
  });
  it("the launcher stays tiny and the chat is loaded lazily", () => {
    expect(Buffer.byteLength(launcher)).toBeLessThan(7000);
    expect(launcher).toContain("assistant-chat.js");
    expect(launcher).toMatch(/requestIdleCallback/);
  });
  it("the button is on every page except the 404 page and /get-started/", () => {
    expect(base).toContain('path !== "/404/" && !path.startsWith("/get-started") && <Assistant />');
  });
  it("the chat opens in limited mode when the API cannot answer, with links and no invented answers", () => {
    expect(chat).toContain("I can't answer live right now");
    expect(chat).toMatch(/cfg\.enabled !== true/);
    for (const label of ["Pricing", "Who it is for", "Security", "Get started or contact us"]) expect(chat).toContain(label);
    // nothing is answered client-side: the only reply text sources are the API's events and the fixed notices
    expect(chat).not.toMatch(/answers?\s*=\s*\{/);
  });
});

import vm from "node:vm";

/** Run the launcher in a bare sandbox and return the rule function it exposes (no DOM needed to test the rules). */
function rules(): { autoMode: (path: string, narrow: boolean, seen: boolean) => string } {
  const win: Record<string, unknown> = { addEventListener() {}, requestIdleCallback: (f: () => void) => f() };
  const doc = { currentScript: { dataset: { api: "http://x" }, src: "http://x/assistant.js" }, readyState: "loading", addEventListener() {} };
  win.window = win; win.document = doc;
  vm.runInNewContext(launcher, { ...win, window: win, document: doc });
  return win.ZiiraLauncher as never;
}

describe("the invitation: the window opens by itself once per session, never as a full-screen sheet", () => {
  const { autoMode } = rules();
  it("opens the phone-style window on the home page and the main pages (tablet and desktop widths)", () => {
    for (const p of ["/", "/ai/", "/ai", "/pricing/", "/solutions/garages-and-body-shops/", "/solutions/every-business/"]) expect(autoMode(p, false, false), p).toBe("window");
  });
  it("not on the get-started, legal, help, 404 or other pages", () => {
    for (const p of ["/get-started/", "/get-started", "/privacy-policy/", "/terms/", "/help/", "/help/first-sale/", "/404/", "/guides/x/", "/security-and-privacy/", "/about/"]) expect(autoMode(p, false, false), p).toBe("none");
  });
  it("only once per browser session: after it was shown, opened or closed, never again", () => {
    expect(autoMode("/", false, true)).toBe("none");
    expect(autoMode("/", true, true)).toBe("none");
    expect(launcher).toMatch(/function open\(from, auto\) \{\s*seen\(\);/);
    expect(launcher).toMatch(/seen\(\);\s*if \(mode === "nudge"\)/);
  });
  it("on phone widths (below 521px) it is only a greeting bubble over the button, never the full-screen sheet", () => {
    expect(autoMode("/", true, false)).toBe("nudge");
    expect(autoMode("/pricing/", true, false)).toBe("nudge");
    expect(launcher).toContain("(max-width: 520px)");
    expect(launcher).toContain("Hi, ask me anything about Ziira");
    expect(launcher).toMatch(/setTimeout\(function \(\) \{ dismiss\(\); \}, 8000\)/);
    expect(launcher).toMatch(/addEventListener\("scroll", dismiss/);
    expect(chat).toMatch(/opts\.auto === true && !\(window\.matchMedia && matchMedia\("\(max-width: 520px\)"\)\.matches\)/);
  });
  it("opens about 2.5 seconds after load", () => { expect(launcher).toMatch(/2500 - /); });
  it("an auto-opened window steals no focus, has no overlay, inert page or scroll lock, and respects reduced motion", () => {
    const passive = chat.slice(chat.indexOf("if (auto) {\n      // Opened by itself"), chat.indexOf("} else {\n      // keep the page behind"));
    expect(passive).toContain("zr-passive");
    expect(passive).not.toMatch(/inert\s*=\s*true/);
    expect(passive).not.toContain('classList.add("zr-open")');
    expect(chat).toMatch(/if \(!auto\) st\.input\.focus/);
    expect(chat).toMatch(/if \(e\.key !== "Tab" \|\| !st\.engaged\) return;/);
    expect(chat).toMatch(/var wait = reduced \? 0 : 1100/);
    expect(chat).toContain("typing dots for a moment");
  });
});
