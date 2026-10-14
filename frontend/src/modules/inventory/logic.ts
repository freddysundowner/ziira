/** Pure rules of the stock screens (no React, no requests), kept apart so they can be tested. */

/** A line being typed into a form: a product, a quantity and, for some documents, a direction, cost, batch and expiry. */
export interface DraftLine {
  key: string;
  productId: string;
  productLabel: string;
  qty: string;
  /** Adjustments only: take stock out instead of adding it. */
  remove: boolean;
  unitCost: string;
  batchNo: string;
  expiry: string;
}

export function newLine(): DraftLine {
  return { key: crypto.randomUUID(), productId: "", productLabel: "", qty: "", remove: false, unitCost: "", batchNo: "", expiry: "" };
}

/** A line is ready when it names a product and a quantity above zero. */
export function isFilled(line: DraftLine): boolean {
  return !!line.productId && Number(line.qty) > 0;
}

/** The signed quantity text the API expects for an adjustment line: "-3" removes stock, "3" adds it. */
export function signedQty(line: DraftLine): string {
  return line.remove ? `-${line.qty}` : line.qty;
}

/** Lines the person actually filled in, so a spare empty row never blocks saving. */
export function filledLines(lines: DraftLine[]): DraftLine[] {
  return lines.filter(isFilled);
}

/** The same product picked on more than one line (usually a slip), by product id. */
export function duplicateProducts(lines: DraftLine[]): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const l of filledLines(lines)) (seen.has(l.productId) ? dup : seen).add(l.productId);
  return [...dup];
}

export interface StockProduct {
  id: string;
  sku: string;
  name: string;
  product_type: string;
  reorder_level: string | null;
  is_active: boolean;
}

export interface StockBalance {
  product_id: string;
  quantity: string;
}

export interface LowStockRow {
  product: StockProduct;
  onHand: string;
  reorderLevel: string;
  /** How far under the reorder level the product is (display only). */
  short: string;
}

/**
 * Stock products whose total on hand (all locations) is at or below their reorder level, most short first.
 * Quantities are compared as numbers: this is a warning list, not accounting.
 */
export function lowStockRows(products: StockProduct[], balances: StockBalance[]): LowStockRow[] {
  const onHand = new Map<string, number>();
  for (const b of balances) onHand.set(b.product_id, (onHand.get(b.product_id) ?? 0) + Number(b.quantity));
  const rows: { row: LowStockRow; gap: number }[] = [];
  for (const product of products) {
    if (!product.is_active || product.product_type !== "stock" || product.reorder_level === null) continue;
    const level = Number(product.reorder_level);
    const have = onHand.get(product.id) ?? 0;
    if (!(level > 0) || have > level) continue;
    rows.push({ row: { product, onHand: String(have), reorderLevel: product.reorder_level, short: String(level - have) }, gap: level - have });
  }
  return rows.sort((a, b) => b.gap - a.gap || a.row.product.name.localeCompare(b.row.product.name)).map((r) => r.row);
}

export interface CountLineLike {
  id: string;
  counted_qty: string | null;
}

/** Entries to send: only lines whose typed value differs from what the server already holds. */
export function changedCounts<L extends CountLineLike>(lines: L[], typed: Record<string, string>): { line: L; value: string }[] {
  const out: { line: L; value: string }[] = [];
  for (const line of lines) {
    const value = typed[line.id];
    if (value === undefined || value === "") continue;
    if (line.counted_qty === null || Number(line.counted_qty) !== Number(value)) out.push({ line, value });
  }
  return out;
}

/** True when a received quantity differs from what was sent (then a reason is needed). */
export function differs(sent: string, received: string): boolean {
  return received !== "" && Number(received) !== Number(sent);
}

/** Page through a list the server limits to 500 rows, up to a few pages (the screens that total a whole list need all of it). */
export async function fetchAll<T>(page: (limit: number, offset: number) => Promise<T[]>, size = 500, maxPages = 10): Promise<T[]> {
  const out: T[] = [];
  for (let i = 0; i < maxPages; i++) {
    const rows = await page(size, i * size);
    out.push(...rows);
    if (rows.length < size) break;
  }
  return out;
}
