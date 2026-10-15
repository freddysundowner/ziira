import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/** Every request that fails shows its message once: the app's mutation cache toasts automatically, so a mutation that toasts the
 *  error itself must say `meta: { silent: true }` (otherwise the person sees two toasts for one error). */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : sources(path);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

/** The text of each `useMutation({ ... })` call, found by matching braces. */
function mutations(code: string): string[] {
  const found: string[] = [];
  for (const m of code.matchAll(/useMutation\(\{/g)) {
    let depth = 1;
    let i = (m.index ?? 0) + m[0].length;
    while (depth > 0 && i < code.length) {
      if (code[i] === "{") depth++;
      else if (code[i] === "}") depth--;
      i++;
    }
    found.push(code.slice(m.index, i));
  }
  return found;
}

describe("error toasts", () => {
  it("are shown once: a mutation that toasts its own error is silent for the mutation cache", () => {
    const offenders: string[] = [];
    for (const file of sources(join(__dirname, ".."))) {
      for (const call of mutations(readFileSync(file, "utf8"))) {
        const handler = call.indexOf("onError");
        if (handler >= 0 && call.slice(handler).includes("toast(") && !call.includes("silent")) offenders.push(file.replace(/.*\/src\//, "src/"));
      }
    }
    expect(offenders).toEqual([]);
  });
});
