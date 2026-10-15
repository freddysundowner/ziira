import type { Schemas } from "@/sdk";

export type CatalogItem = Schemas["CatalogItemOut"];
export type SaleOp = Schemas["SaleOp"];

/**
 * Where a sale made without a connection stands:
 * pending -> sending -> done (the server has it), or back to pending after a lost connection (waiting to retry),
 * or failed (the server read it and refused: it stays visible until a person deals with it).
 */
export type EntryState = "pending" | "sending" | "failed" | "done";

/** One sale in the outbox. The outbox is durable (IndexedDB): a reload or a closed browser never loses it. */
export interface OutboxEntry {
  /** The sale's client-made id: the server records a sale with this id once, however often it is sent. */
  localId: string;
  /** Order in which the sales were made on this browser; they are sent in this order. */
  seq: number;
  state: EntryState;
  tillId: string;
  branchId: string;
  userId: string;
  /** Provisional receipt number, e.g. OFFLINE-D1-0007. The server gives the real one. */
  number: string;
  /** The device clock when the sale was made (ms), and how far the server's clock was ahead of it when last known. */
  madeAt: number;
  offsetMs: number;
  total: string;
  currency: string;
  /** Exactly what is sent to the server. */
  op: SaleOp;
  /** What the cashier sees in the queue. */
  lines: { sku: string; name: string; quantity: string; amount: string }[];
  customerName: string;
  /** The receipt printed from local data. */
  receipt: Schemas["PrintOut"];
  attempts: number;
  nextAttemptAt: number;
  lastAttemptAt: number;
  lastError: string;
  warnings: string[];
  serverNumber: string;
  saleId: string;
  doneAt: number;
}

export interface Counts {
  /** Not at the server yet and still being tried (pending or sending). */
  waiting: number;
  sending: number;
  /** The server refused them: a person has to look. */
  attention: number;
  done: number;
}

export type ChipKind = "online" | "offline" | "syncing" | "waiting" | "attention";
