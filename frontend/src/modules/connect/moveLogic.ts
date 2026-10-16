/** Pure rules behind the "Move to Ziira Core" screens (tested in moveLogic.test.ts). */
import type { BadgeTone } from "@/sdk";

export type MoveKind = "products" | "customers" | "suppliers" | "opening_stock" | "customer_balances" | "supplier_balances";

/** The order records are brought in: the second group refers to records of the first. */
export const MOVE_KINDS: readonly MoveKind[] = ["products", "customers", "suppliers", "opening_stock", "customer_balances", "supplier_balances"];

/** Which of the other system's counts a kind comes from (the key of `source_counts`). */
export const SOURCE_OF: Record<MoveKind, string> = {
  products: "products", customers: "customers", suppliers: "suppliers", opening_stock: "stock_movements",
  customer_balances: "customer_invoices", supplier_balances: "supplier_invoices",
};

interface KindState { kind: MoveKind; available: boolean; allowed: boolean }

/** What is ticked at first: every kind that can be brought (its unit is on, the person may) and has something to bring. */
export function defaultKinds(kinds: readonly KindState[], counts: Record<string, number>): MoveKind[] {
  return kinds.filter((k) => k.available && k.allowed && (counts[SOURCE_OF[k.kind]] ?? 0) > 0).map((k) => k.kind);
}

/** Products need a unit and a tax class chosen; stock needs a location for every branch that holds some. */
export function needsProductDefaults(chosen: readonly MoveKind[]): boolean {
  return chosen.includes("products");
}

export function ready(chosen: readonly MoveKind[], unit: string, taxCode: string, asOf: string): boolean {
  return chosen.length > 0 && !!asOf && (!needsProductDefaults(chosen) || (!!unit && !!taxCode));
}

interface Counted { create: number; exists: number; skipped: number; selected: boolean }

export function totals(kinds: readonly Counted[]): { create: number; exists: number; skipped: number } {
  return kinds.filter((k) => k.selected).reduce((sum, k) => ({ create: sum.create + k.create, exists: sum.exists + k.exists, skipped: sum.skipped + k.skipped }), { create: 0, exists: 0, skipped: 0 });
}

interface BatchLike { status: string; counts: Record<string, number> }

/** How far a move is: batches finished (or with nothing to do) out of those chosen. */
export function percentDone(batches: readonly BatchLike[]): number {
  if (batches.length === 0) return 0;
  const finished = batches.filter((b) => ["done", "nothing_new", "reverted", "unavailable"].includes(b.status)).length;
  return Math.round((finished / batches.length) * 100);
}

/** The tone of a batch's badge. */
export function batchTone(b: BatchLike): BadgeTone {
  if ((b.counts.failed ?? 0) > 0 || b.status === "unavailable") return "bad";
  if (b.status === "done") return "ok";
  if (b.status === "nothing_new" || b.status === "reverted") return "neutral";
  return "info";
}

/** Whether anything in a finished move can still be taken back. */
export function canUndo(batches: readonly (BatchLike & { reversible: boolean })[]): boolean {
  return batches.some((b) => b.reversible && b.status === "done");
}

/** The units that hold what a move brings over. When none is on there is nothing to move to yet. */
const CORE_UNITS = ["products", "crm", "purchasing", "inventory", "pos"] as const;
export function hasCoreUnits(enabled: ReadonlySet<string>): boolean {
  return CORE_UNITS.some((u) => enabled.has(u));
}
