/** Pure rules for the findings screens: the status filter, which actions a person has, and tuning a check's limits. */
import type { Schemas } from "@/sdk";

export type Finding = Schemas["FindingOut"];
export type Check = Schemas["CheckOut"];

export const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;
export const STATUSES = ["new", "sent", "acknowledged", "explained", "resolved", "dismissed"] as const;
export const AREAS = ["cash_sales", "customers", "suppliers", "stock", "cash_planning", "books", "people", "controls", "general"] as const;
type Status = (typeof STATUSES)[number];

export const OPEN_STATUSES: readonly string[] = ["new", "sent", "acknowledged", "explained"];
export const isOpen = (status: string): boolean => OPEN_STATUSES.includes(status);

/** What the status filter asks the server for. `undefined` means the server's default: open findings only. */
export type StatusFilter = "open" | "closed" | "all" | Status;
export function statusesFor(filter: StatusFilter): Status[] | undefined {
  if (filter === "open") return undefined;
  if (filter === "all") return [...STATUSES];
  if (filter === "closed") return ["resolved", "dismissed"];
  return [filter];
}

export interface ActionRights {
  acknowledge: boolean;
  explain: boolean;
  resolve: boolean;
  dismiss: boolean;
  assign: boolean;
  ask: boolean;
}

/**
 * The actions to offer for a finding. Managers may do everything on an open finding; someone who can only respond may
 * acknowledge and explain a finding assigned to them. The server checks scope again.
 */
export function actionsFor(finding: Pick<Finding, "status" | "owner_user_id">, can: { manage: boolean; respond: boolean }, userId: string | null): ActionRights {
  const none: ActionRights = { acknowledge: false, explain: false, resolve: false, dismiss: false, assign: false, ask: false };
  if (!isOpen(finding.status)) return none;
  const mine = can.respond && !!userId && finding.owner_user_id === userId;
  const answers = can.manage || mine;
  return {
    acknowledge: answers && finding.status !== "acknowledged",
    explain: answers && finding.status !== "explained",
    resolve: can.manage,
    dismiss: can.manage,
    assign: can.manage,
    ask: can.manage,
  };
}

/** Whole days since a moment, never negative. */
export function ageInDays(since: string, now: Date = new Date()): number {
  const ms = now.getTime() - new Date(since).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 86_400_000)) : 0;
}

// ---- tuning a check's limits

export type ParamKind = "boolean" | "number" | "text";
export function paramKind(value: unknown): ParamKind {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return "number";
  return "text";
}

/** Limits as text, for the inputs. */
export const paramsToDraft = (params: Record<string, unknown>): Record<string, string> =>
  Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]));

/** Only the limits whose text differs from the saved ones, ready to send (booleans stay booleans). */
export function draftChanges(check: Pick<Check, "params" | "defaults">, draft: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, saved] of Object.entries(check.params)) {
    const text = draft[name];
    if (text === undefined || text === String(saved)) continue;
    out[name] = paramKind(check.defaults[name]) === "boolean" ? text === "true" : text.trim();
  }
  return out;
}

/** True when every limit is at its default. */
export const atDefaults = (check: Pick<Check, "params" | "defaults">): boolean =>
  Object.keys(check.defaults).every((k) => String(check.params[k]) === String(check.defaults[k]));

/** The limits that differ from their defaults, set back to the defaults. */
export function resetChanges(check: Pick<Check, "params" | "defaults">): Record<string, unknown> {
  return Object.fromEntries(Object.entries(check.defaults).filter(([k, d]) => String(check.params[k]) !== String(d)));
}

/** Checks grouped by area, known areas first in their usual order. */
export function groupChecks(checks: readonly Check[]): { area: string; checks: Check[] }[] {
  const known: readonly string[] = AREAS;
  const rank = (a: string) => { const i = known.indexOf(a); return i < 0 ? known.length : i; };
  const byArea = new Map<string, Check[]>();
  for (const c of checks) byArea.set(c.area, [...(byArea.get(c.area) ?? []), c]);
  return [...byArea.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])).map(([area, list]) => ({ area, checks: list }));
}
