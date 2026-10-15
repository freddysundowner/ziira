import type { BadgeTone, Schemas } from "@/sdk";

export type Kind = Schemas["ConnectorKindOut"];
export type Connection = Schemas["ConnectionOut"];

export const STATUS_TONE: Record<string, BadgeTone> = { active: "ok", paused: "neutral", error: "bad", disconnected: "neutral" };
const ENTITY_ORDER = ["branches", "parties", "products", "users", "sales", "payments", "stock_movements", "invoices", "expenses", "journal_entries"];

/** Where the web app opens the connection page after the vendor's approval screen (matches the backend's WEB_PATH). */
export const connectionPath = (id: string) => `/connect/connections/${id}`;

/** The catalogue grouped for the picker: ERPs first, then statements and exports. */
export function groupKinds(kinds: readonly Kind[]): { group: string; kinds: Kind[] }[] {
  const groups: { group: string; kinds: Kind[] }[] = [];
  for (const kind of kinds) {
    const found = groups.find((g) => g.group === kind.group);
    if (found) found.kinds.push(kind);
    else groups.push({ group: kind.group, kinds: [kind] });
  }
  return groups.sort((a, b) => Number(a.kinds[0]?.freshness === "on_upload") - Number(b.kinds[0]?.freshness === "on_upload"));
}

/** Sorts entity codes in the order the screens list them. */
export const sortEntities = (entities: readonly string[]) =>
  [...entities].sort((a, b) => (ENTITY_ORDER.indexOf(a) + 1 || 99) - (ENTITY_ORDER.indexOf(b) + 1 || 99));

/** The result the OAuth callback put in the address: `?oauth=success` or `?oauth=failed&reason=<code>`. */
export function oauthResult(search: string): { ok: boolean; reason: string | null } | null {
  const params = new URLSearchParams(search);
  const state = params.get("oauth");
  if (state === "success") return { ok: true, reason: null };
  if (state === "failed") return { ok: false, reason: params.get("reason") };
  return null;
}

/** A read is overdue when nothing succeeded for three times the freshness window. File kinds never go stale. */
export function isStale(c: Pick<Connection, "freshness" | "status" | "last_success_at" | "sync_every_minutes">, now = Date.now()): boolean {
  if (c.freshness === "on_upload" || c.status === "disconnected" || c.status === "paused") return false;
  if (!c.last_success_at) return false;
  return now - new Date(c.last_success_at).getTime() > 3 * c.sync_every_minutes * 60_000;
}

/** Percent of the checks that can run today (0 when there are none). */
export function coveragePercent(areas: readonly { active: number; total: number }[]): number {
  const total = areas.reduce((n, a) => n + a.total, 0);
  return total === 0 ? 0 : Math.round((areas.reduce((n, a) => n + a.active, 0) * 100) / total);
}

/** Minutes as "15 minutes", "6 hours", "1 day" parts for the freshness choice. */
export const FRESHNESS_CHOICES = [15, 60, 360, 1440] as const;
