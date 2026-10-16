import type { BadgeTone } from "@/sdk";

export type Severity = "bad" | "warn" | "info";

export const SEVERITY_TONE: Record<Severity, BadgeTone> = { bad: "bad", warn: "warn", info: "info" };

/** Alerts of the worst kind first (the server sends them sorted; this keeps a list from the cache honest). */
export function bySeverity<T extends { severity: Severity; key: string }>(items: readonly T[]): T[] {
  const rank: Record<Severity, number> = { bad: 0, warn: 1, info: 2 };
  return [...items].sort((a, b) => rank[a.severity] - rank[b.severity] || a.key.localeCompare(b.key));
}

/** The number on the bell: how many things need attention, "9+" past nine. Nothing at zero. */
export function bellLabel(total: number): string | null {
  if (total <= 0) return null;
  return total > 9 ? "9+" : String(total);
}
