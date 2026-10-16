/** Small pure helpers for the webhooks screens. */
import type { Schemas } from "@/sdk";

type Endpoint = Schemas["WebhookOut"];
type Delivery = Schemas["DeliveryOut"];
type Tone = "ok" | "warn" | "bad" | "neutral";

/** "Sales, payments" style summary of the chosen events: first three type names, then "+N". */
export function eventSummary(types: readonly string[]): string {
  if (types.length <= 3) return types.join(", ");
  return `${types.slice(0, 3).join(", ")} +${types.length - 3}`;
}

export function endpointTone(e: Pick<Endpoint, "status" | "consecutive_failures">): Tone {
  if (e.status === "disabled") return "bad";
  if (e.status === "paused") return "neutral";
  return e.consecutive_failures > 0 ? "warn" : "ok";
}

export function deliveryTone(status: string): Tone {
  return status === "delivered" ? "ok" : status === "failed" ? "bad" : status === "pending" ? "warn" : "neutral";
}

/** A delivery can be sent again when it has finished, still has its content, and its endpoint is active. */
export function canRedeliver(d: Pick<Delivery, "status" | "has_body">, endpoint: Pick<Endpoint, "status">): boolean {
  return d.status !== "pending" && d.has_body && endpoint.status === "active";
}

/** Group the catalogue by the unit that publishes each event, for the picker. */
export function groupEvents<T extends { unit: string; type: string }>(events: readonly T[]): { unit: string; events: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const e of events) groups.set(e.unit, [...(groups.get(e.unit) ?? []), e]);
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([unit, list]) => ({ unit, events: list }));
}

/** Toggle one event type in a selection (kept sorted so the form compares cleanly). */
export function toggleEvent(selected: readonly string[], type: string, on: boolean): string[] {
  const rest = selected.filter((t) => t !== type);
  return (on ? [...rest, type] : rest).sort();
}
