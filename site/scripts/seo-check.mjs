// npm run seo:check [-- --production] [-- --links-only] [-- --dist=dist]
// Fails (exit 1) on any SEO rule violation in the built site. PUBLIC_SITE_URL unset/placeholder fails only in production mode
// (--production, or ZIIRA_SITE_ENV=production).
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { auditSite, LINK_RULES } from "./lib/rules.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const dist = path.resolve(here, "..", (args.find((a) => a.startsWith("--dist="))?.slice(7)) ?? "dist");
const production = args.includes("--production") || process.env.ZIIRA_SITE_ENV === "production";
const linksOnly = args.includes("--links-only");
if (!fs.existsSync(dist)) { console.error(`No build at ${dist}. Run npm run build first.`); process.exit(2); }
const allow = JSON.parse(fs.readFileSync(path.join(here, "noindex-allowlist.json"), "utf8")).paths;
const { issues, stats } = auditSite(dist, { production, noindexAllowed: allow, only: linksOnly ? LINK_RULES : null });

const byRule = new Map();
for (const i of issues) (byRule.get(i.rule) ?? byRule.set(i.rule, []).get(i.rule)).push(i);
for (const [rule, list] of byRule) {
  console.error(`\n[${rule}] ${list.length}`);
  for (const i of list.slice(0, 15)) console.error(`  ${i.page}: ${i.message}`);
  if (list.length > 15) console.error(`  ... and ${list.length - 15} more`);
}
console.log(`\nChecked ${stats.pages} pages, ${stats.sitemapUrls} sitemap URLs, origin ${stats.siteOrigin || "(none)"}${production ? " [production mode]" : ""}.`);
console.log(`External links (not fetched): ${stats.externalLinks.length}${stats.externalLinks.length ? "\n  " + stats.externalLinks.join("\n  ") : ""}`);
// Stale marketing screenshots are a warning, never a failure (scripts/screens-stale.mjs).
if (!linksOnly) { try { execFileSync(process.execPath, [path.join(here, "screens-stale.mjs")], { stdio: "inherit" }); } catch { /* warning only */ } }
if (issues.length) { console.error(`\nSEO check FAILED: ${issues.length} issue(s) in ${byRule.size} rule(s).`); process.exit(1); }
console.log("SEO check passed.");
