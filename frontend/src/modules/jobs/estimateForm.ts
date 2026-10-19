/** The estimate editor as plain data: its lines, what is missing, and the request body. */
import type { Schemas } from "@/sdk";

import type { Estimate } from "./types";

export type LineKind = "part" | "labour" | "other";

export interface EditLine {
  kind: LineKind;
  productId: string;
  description: string;
  quantity: string;
  unitPrice: string;
}

export const blankLine = (kind: LineKind = "part"): EditLine => ({ kind, productId: "", description: "", quantity: "1", unitPrice: "" });

export const linesOf = (estimate: Estimate): EditLine[] =>
  estimate.lines.map((l) => ({ kind: l.kind as LineKind, productId: l.product_id ?? "", description: l.description, quantity: l.quantity, unitPrice: l.unit_price }));

/** True when the line can be sent: a quantity, and something to call it (a product names itself; labour has a usual rate). */
export const lineReady = (l: EditLine): boolean => Number(l.quantity) > 0 && (!!l.productId || !!l.description.trim());

export const linesReady = (lines: readonly EditLine[]): boolean => lines.length > 0 && lines.every(lineReady);

export function toLineBodies(lines: readonly EditLine[]): Schemas["EstimateLineBody"][] {
  return lines.map((l) => ({
    kind: l.kind,
    description: l.description.trim() || null,
    quantity: l.quantity,
    unit_price: l.unitPrice === "" ? null : l.unitPrice,
    product_id: l.kind === "part" && l.productId ? l.productId : null,
  }));
}

/** Estimate status codes the server uses, as a badge tone. */
export const estimateTone = (status: string): "neutral" | "info" | "ok" | "bad" | "warn" =>
  ({ draft: "neutral", sent: "info", approved: "ok", declined: "bad", superseded: "warn" } as const)[status as "draft"] ?? "neutral";
