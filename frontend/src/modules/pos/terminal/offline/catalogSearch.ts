/** Searching the copy of the catalog kept on the device: the same matching the server does (name, SKU, or a scanned code). */
import type { CatalogItem } from "./types";

/** The product with exactly this code (a barcode or the SKU), when it is unambiguous. Case matters for barcodes; SKUs ignore case. */
export function findByCode(items: readonly CatalogItem[], code: string): CatalogItem | undefined {
  const wanted = code.trim();
  if (!wanted) return undefined;
  const byBarcode = items.filter((i) => (i.barcodes ?? []).includes(wanted));
  if (byBarcode.length === 1) return byBarcode[0];
  if (byBarcode.length > 1) return undefined;
  const bySku = items.filter((i) => i.sku.toLowerCase() === wanted.toLowerCase());
  return bySku.length === 1 ? bySku[0] : undefined;
}

/** Products whose name or SKU contains the text, or that have exactly that barcode; by name, at most `limit`. */
export function searchLocal(items: readonly CatalogItem[], text: string, limit: number): CatalogItem[] {
  const q = text.trim().toLowerCase();
  const sorted = [...items].sort((a, b) => a.name.localeCompare(b.name) || a.sku.localeCompare(b.sku));
  const found = q
    ? sorted.filter((i) => i.name.toLowerCase().includes(q) || i.sku.toLowerCase().includes(q) || (i.barcodes ?? []).includes(text.trim()))
    : sorted;
  return found.slice(0, limit);
}

/** The items with the stock of sales not yet at the server taken off, so the screen keeps counting them. */
export function withReserved(items: readonly CatalogItem[], reserved: ReadonlyMap<string, number>): CatalogItem[] {
  if (reserved.size === 0) return [...items];
  return items.map((i) => {
    const used = reserved.get(i.product_id);
    if (!used || i.stock === null || i.stock === undefined) return i;
    return { ...i, stock: String(Math.round((Number(i.stock) - used) * 10_000) / 10_000) };
  });
}
