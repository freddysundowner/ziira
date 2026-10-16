// Reports marketing screenshots that may no longer match the app. A WARNING only (exit code 0), run by `npm run seo:check` and `make site-check`.
// A picture is flagged when it (1) is older than MAX_DAYS (default 45), (2) was captured from an earlier commit and frontend/src has commits since,
// (3) frontend/src has files newer than the capture (uncommitted work), (4) has no manifest row or no file. Fix: `make site-screens`.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.resolve(here, "../src/assets/screens");
const repo = path.resolve(here, "../..");
const MAX_DAYS = Number(process.env.SCREENS_MAX_DAYS ?? 45);
const git = (...a) => { try { return execFileSync("git", a, { cwd: repo, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim(); } catch { return null; } };
function newestMtime(d) {
  let n = 0;
  const walk = (x) => { for (const e of fs.readdirSync(x, { withFileTypes: true })) {
    if (e.name === "node_modules") continue;
    const f = path.join(x, e.name);
    if (e.isDirectory()) walk(f); else n = Math.max(n, fs.statSync(f).mtimeMs);
  } };
  walk(d);
  return n;
}

const warn = [];
const manifestFile = path.join(dir, "manifest.json");
if (!fs.existsSync(manifestFile)) {
  warn.push("no src/assets/screens/manifest.json: run `make site-screens`");
} else {
  const manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"));
  const feNewest = fs.existsSync(path.join(repo, "frontend/src")) ? newestMtime(path.join(repo, "frontend/src")) : 0;
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".webp")).map((f) => f.replace(/\.webp$/, ""));
  for (const key of files) if (!manifest.screens?.[key]) warn.push(`${key}: no manifest row (not captured by the script?)`);
  for (const [key, m] of Object.entries(manifest.screens ?? {})) {
    if (!files.includes(key)) { warn.push(`${key}: in the manifest but the file is missing`); continue; }
    const why = [];
    const captured = Date.parse(m.captured);
    const ageDays = Math.floor((Date.now() - captured) / 86400000);
    if (ageDays > MAX_DAYS) why.push(`${ageDays} days old (limit ${MAX_DAYS})`);
    const commit = String(m.appCommit ?? "").replace(/\+uncommitted$/, "");
    const since = commit && git("rev-parse", "--verify", "-q", commit) ? git("rev-list", "--count", `${commit}..HEAD`, "--", "frontend/src") : null;
    if (since && Number(since) > 0) why.push(`frontend/src changed in ${since} commit(s) since ${commit}`);
    if (feNewest > captured + 60000) why.push(`frontend/src edited after the capture (${new Date(feNewest).toISOString().slice(0, 16)})`);
    if (why.length) warn.push(`${key} (${m.route}): ${why.join("; ")}`);
  }
}
if (warn.length) {
  console.warn(`\nWARNING: ${warn.length} marketing screenshot(s) may be out of date. Re-run \`make site-screens\` with the app running.`);
  for (const w of warn) console.warn("  - " + w);
} else console.log("screens: all marketing screenshots are current");
