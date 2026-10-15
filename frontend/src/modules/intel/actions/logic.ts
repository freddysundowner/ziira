/** Pure rules for suggested actions and the automatic rules: which are waiting, where created records lead, how events group. */
import type { Schemas } from "@/sdk";

export type Proposal = Schemas["ProposalOut"];
export type ActionType = Schemas["ActionTypeOut"];
export type ActionLogRow = Schemas["ActionLogOut"];
export type Rule = Schemas["ziira__modules__intel__api__schemas__RuleOut"];
export type CreatedRecord = Schemas["RecordOut"];

export const WAITING = ["proposed", "failed"] as const;
export const HISTORY = ["executed", "failed", "rejected", "expired", "cancelled"] as const;
export const LEVELS = [1, 2, 3, 4] as const;

export const isWaiting = (p: Pick<Proposal, "status">): boolean => (WAITING as readonly string[]).includes(p.status);

/** A finding's suggestions: the ones to decide on first, the rest as earlier suggestions (newest first in both). */
export function splitProposals(list: readonly Proposal[]): { waiting: Proposal[]; earlier: Proposal[] } {
  const newestFirst = [...list].sort((a, b) => b.proposed_at.localeCompare(a.proposed_at));
  return { waiting: newestFirst.filter(isWaiting), earlier: newestFirst.filter((p) => !isWaiting(p)) };
}

/** Screens that show a record the server names by type; any other type is shown as plain text. */
const RECORD_ROUTES: Record<string, string> = {
  "purchasing.purchase_request": "/requests/",
  "products.product": "/products/",
  "crm.customer": "/customers/",
};

export function recordLink(record: Pick<CreatedRecord, "type" | "id">): string | null {
  const base = RECORD_ROUTES[record.type];
  return base && record.id ? `${base}${record.id}` : null;
}

/** Only levels 3 and 4 need the Owner's `intel.automation`; any lowering is a plain settings change. */
export const needsAutomationRight = (level: number): boolean => level >= 3;

/** Whether to show the rules a business has as active: on, and not paused by a person. */
export type RuleState = "active" | "paused" | "off";
export const ruleState = (r: Pick<Rule, "enabled" | "paused">): RuleState => (!r.enabled ? "off" : r.paused ? "paused" : "active");
