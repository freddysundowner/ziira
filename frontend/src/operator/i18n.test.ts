import { describe, expect, it } from "vitest";

import { ACTION_PERMISSION, FLAGS } from "./helpers/subscribers";
import { EXTRA_PAGES, NAV_GROUPS } from "./nav";
import { EXTRA_LIMITS } from "./helpers/plan";
import { INTERVALS, SUBSCRIPTION_STATUSES } from "./helpers/format";
import en from "./i18n/en.json";
import enPlatform from "./i18n/en.platform.json";
import enAi from "./i18n/en.ai.json";
import swAi from "./i18n/sw.ai.json";
import enWebsite from "./i18n/en.website.json";
import sw from "./i18n/sw.json";
import swPlatform from "./i18n/sw.platform.json";
import swWebsite from "./i18n/sw.website.json";
import enShell from "./i18n/en.shell.json";
import swShell from "./i18n/sw.shell.json";
import enChat from "./i18n/en.chat.json";
import swChat from "./i18n/sw.chat.json";

type Tree = { [key: string]: Tree | string };

function keys(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object") return Object.entries(value).flatMap(([k, v]) => keys(v, `${prefix}${k}.`));
  return [prefix.slice(0, -1)];
}

function merge(...trees: Tree[]): Tree {
  const out: Tree = {};
  for (const tree of trees) {
    for (const [k, v] of Object.entries(tree)) {
      const have = out[k];
      out[k] = typeof v === "object" && typeof have === "object" ? merge(have, v) : v;
    }
  }
  return out;
}

const merged = { en: merge(en, enPlatform, enAi, enWebsite, enShell, enChat), sw: merge(sw, swPlatform, swAi, swWebsite, swShell, swChat) };

describe("operator console translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("leave no empty text", () => {
    for (const k of keys(en)) expect(k).not.toBe("");
  });
  it("have the same keys in the shell's files", () => {
    expect(keys(swShell).sort()).toEqual(keys(enShell).sort());
  });
  it("have the same keys in the WhatsApp bot page's files", () => {
    expect(keys(swChat).sort()).toEqual(keys(enChat).sort());
  });
  it("have the same keys in the platform screens' files", () => {
    expect(keys(swPlatform).sort()).toEqual(keys(enPlatform).sort());
  });
  it("have the same keys once every file is put together", () => {
    expect(keys(merged.sw).sort()).toEqual(keys(merged.en).sort());
  });
});

describe("the console's screens only ask for words that exist", () => {
  const sources = import.meta.glob<string>(["./**/*.tsx", "./**/*.ts", "!./**/*.test.*", "!./pages/website/**", "!./i18n/**"], { eager: true, query: "?raw", import: "default" });
  const present = new Set<string>();
  for (const k of keys(merged.en)) {
    present.add(k);
    present.add(k.replace(/_(one|other)$/, ""));
    for (let i = k.indexOf("."); i > 0; i = k.indexOf(".", i + 1)) present.add(k.slice(0, i));       // a group, built up with a variable part
  }
  const topLevel = new Set(Object.keys(merged.en));

  it("finds every fixed key in both languages", () => {
    const missing: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      const words = source.replace(/(settingKey=|v\[|k\()"[^"]+"/g, "");                        // platform setting names are not words
      for (const match of words.matchAll(/"([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_-]+)+)"/g)) {
        const key = match[1] as string;
        if (!topLevel.has(key.split(".")[0] as string) || key.startsWith("platform.")) continue;
        if (!present.has(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

describe("words chosen by a value from the API or a list exist for every value", () => {
  const families: Record<string, readonly string[]> = {
    status: SUBSCRIPTION_STATUSES,
    invoiceStatus: ["draft", "issued", "paid", "void"],
    interval: INTERVALS,
    "subs.flags": FLAGS,
    "subscriber.actions": Object.keys(ACTION_PERMISSION),
    "subscriber.tabs": ["overview", "billing", "timeline", "units", "support", "audit"],
    "subscriber.start.modes": ["trial", "active", "comp"],
    "subscriber.start.modeHints": ["trial", "active", "comp"],
    "subscriber.changePlan.effectives": ["auto", "now", "period_end"],
    "subscriber.changePlan.effectiveHints": ["auto", "now", "period_end"],
    "plans.editor.extra": EXTRA_LIMITS,
    "plans.price.states": ["current", "scheduled", "withdrawn", "superseded"],
    "plans.addons.kinds": ["unit", "users", "branches", "companies"],
    "plans.coupons.durations": ["once", "repeating", "forever"],
    "plans.coupons.durationHints": ["once", "repeating", "forever"],
    "plans.coupons.statuses": ["active", "disabled"],
    "plans.statuses": ["active", "retired"],
    "billing.requests.statuses": ["pending", "approved", "declined", "cancelled"],
    "billing.invoice.kinds": ["first", "renewal", "upgrade", "manual", "licence"],
    "billing.payment.methods": ["bank", "cash", "mobile", "cheque", "card"],
    "billing.run.counts": ["invoices", "cancelled", "reminders", "moved", "deletions"],
    "billing.settings.vendorFields": ["name", "address", "tax_id", "email", "phone"],
    "billing.settings.dunningSteps": ["past_due_after_days", "grace_after_days", "suspend_after_days", "expire_after_days"],
    "billing.invoiceForm.problems": ["target", "currency", "noLines", "badLine"],
    "plans.editor.errors": ["code", "nameRequired", "nameLong", "limit", "trialDays", "sortOrder", "intervals", "highlights"],
    "plans.price.errors": ["currency", "interval", "amount"],
    "plans.coupons.errors": ["code", "percent", "amounts", "duplicate", "periods", "max"],
    "licences.errors": ["customer", "email", "plan", "units", "limit", "validUntil", "grace", "instance"],
    "licences.statuses": ["active", "revoked", "expired"],
    "licences.basisHints": ["plan", "units"],
    "operators.roles": ["superadmin", "billing", "support", "content", "readonly"],
    "operators.roleHints": ["superadmin", "billing", "support", "content", "readonly"],
    "operators.perms": ["platform_view", "platform_subscribers", "platform_plans", "platform_billing", "platform_licences", "platform_units", "platform_content", "platform_operators"],
    "dash.modes": ["saas", "selfhosted"],
    "dash.limitKinds": ["users", "branches", "companies"],
  };
  it.each(Object.entries(families))("%s", (prefix, values) => {
    const have = new Set(keys(merged.en));
    const missing = values.filter((v) => !have.has(`${prefix}.${v}`));
    expect(missing).toEqual([]);
  });
});

describe("the shell's words exist for every alert, risk, checklist step and menu entry the server or the menu can name", () => {
  const have = new Set(keys(merged.en));
  const sw = new Set(keys(merged.sw));
  const need = (keysNeeded: string[]) => keysNeeded.filter((k) => !have.has(k) || !sw.has(k));
  it("alerts (the keys the server's alert list uses)", () => {
    const alerts = ["payments_attention", "suspended", "past_due", "pending_requests", "trials_ending", "failed_jobs", "businesses_behind", "businesses_unreadable", "plugins_refused",
      "licences_expiring", "backup_old", "not_ready", "mail_not_working", "ai_cap_reached"];
    expect(need(alerts.flatMap((a) => [`shell.alerts.items.${a}.title`, `shell.alerts.items.${a}.hint`]))).toEqual([]);
  });
  it("risks and checklist steps", () => {
    expect(need(["mfa_off", "registration_without_email", "mail_not_configured", "no_ai_provider"].flatMap((r) => ["title", "text", "fix"].map((p) => `shell.risks.${r}.${p}`)))).toEqual([]);
    expect(need(["email", "registration", "ai", "payments", "plans", "website", "licence"].flatMap((s) => ["title", "text", "link"].map((p) => `setup.items.${s}.${p}`)))).toEqual([]);
  });
  it("every menu entry, group and search kind", () => {
    const entries = NAV_GROUPS.flatMap((g) => g.items.map((i) => `nav.i.${i.id}`));
    const groups = NAV_GROUPS.map((g) => g.key);
    const extra = EXTRA_PAGES.map((p) => `nav.i.${p.id}`);
    const kinds = ["page", "subscriber", "invoice", "plan", "licence", "operator"].map((k) => `shell.search.kinds.${k}`);
    expect(need([...entries, ...groups, ...extra, ...kinds])).toEqual([]);
  });
  it("environments and chart words", () => {
    expect(need(["production", "development", "test"].map((e) => `shell.env.${e}`))).toEqual([]);
    expect(need(["revenue", "signups", "churn"].flatMap((m) => [`dash.trend.metrics.${m}`, `dash.trend.hint.${m}`]))).toEqual([]);
    expect(need(["12m", "12w"].map((r) => `dash.trend.ranges.${r}`))).toEqual([]);
  });
});
