/** Held sales: the copy on this device and the copy at the server, brought together. Pure, so every case is tested. */
import type { Schemas } from "@/sdk";

import type { CartLine, HeldSale } from "../cart";

export type ServerHeld = Schemas["HeldSaleOut"];

/** A held sale in the server's shape, from the terminal's. */
export function toServerBody(h: HeldSale): Schemas["HeldSaleIn"] {
  return {
    local_id: h.id,
    label: h.label.slice(0, 120),
    customer_id: h.customerId || null,
    customer_name: h.customerName,
    customer_phone: h.customerPhone,
    lines: h.lines.map((l) => ({
      product_id: l.productId, sku: l.sku, name: l.name, quantity: l.quantity, list_price: l.listPrice || null,
      price: l.price || null, discount: l.discount || "0", reason_code_id: l.reasonId || null,
    })),
  };
}

export function fromServer(h: ServerHeld): HeldSale {
  const lines: CartLine[] = h.lines.map((l) => ({
    key: crypto.randomUUID(), productId: l.product_id, sku: l.sku, name: l.name, listPrice: l.list_price == null ? "" : String(l.list_price),
    price: l.price == null ? "" : String(l.price), quantity: String(l.quantity), discount: String(l.discount ?? "0"), reasonId: l.reason_code_id ?? "", stock: "", vatRate: "0",
  }));
  return { id: h.local_id, label: h.label, savedAt: h.created_at, lines, customerId: h.customer_id ?? "", customerName: h.customer_name, customerPhone: h.customer_phone, remote: true };
}

export interface Reconciled {
  /** At the server only (this device lost it): add them. */
  add: HeldSale[];
  /** Here only, but the server no longer holds them (resumed or discarded elsewhere): drop them. */
  drop: Set<string>;
  /** Here and at the server: mark them as at the server. */
  remote: Set<string>;
  /** Here only, never sent (held while offline): send them. */
  upload: HeldSale[];
}

/**
 * Compare the held sales on this device with the server's. `gone` are the ids the cashier resumed or discarded here that the
 * server has not been told about yet; they are left out. The result is a set of changes, so it can be applied to the list
 * as it is *now* (a sale held while this was running is not lost).
 */
export function reconcileHeld(local: readonly HeldSale[], server: readonly ServerHeld[], gone: ReadonlySet<string>): Reconciled {
  const onServer = new Set(server.map((s) => s.local_id));
  const result: Reconciled = { add: [], drop: new Set(), remote: new Set(), upload: [] };
  for (const h of local) {
    if (gone.has(h.id)) continue;
    if (onServer.has(h.id)) result.remote.add(h.id);
    else if (h.remote) result.drop.add(h.id);
    else result.upload.push(h);
  }
  const known = new Set(local.map((h) => h.id));
  for (const s of server) if (!known.has(s.local_id) && !gone.has(s.local_id)) result.add.push(fromServer(s));
  return result;
}

export function applyReconciled(current: readonly HeldSale[], r: Reconciled): HeldSale[] {
  const have = new Set(current.map((h) => h.id));
  const kept = current.filter((h) => !r.drop.has(h.id)).map((h) => (r.remote.has(h.id) ? { ...h, remote: true } : h));
  return [...kept, ...r.add.filter((h) => !have.has(h.id))].sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}
