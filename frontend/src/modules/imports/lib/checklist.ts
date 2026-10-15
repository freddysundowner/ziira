import type { Schemas } from "@/sdk";

type Batch = Schemas["BatchOut"];

/** The steps of moving a business onto Ziira, in the order that works. `kind` is the import to do; a step without one is a screen to visit. */
export const OPENING_STEPS = [
  { id: "setup", kind: null, link: "/products-setup" },
  { id: "accounts", kind: "accounts", link: null },
  { id: "products", kind: "products", link: null },
  { id: "customers", kind: "customers", link: null },
  { id: "suppliers", kind: "suppliers", link: null },
  { id: "opening_stock", kind: "opening_stock", link: null },
  { id: "customer_balances", kind: "customer_balances", link: null },
  { id: "supplier_balances", kind: "supplier_balances", link: null },
  { id: "opening_trial_balance", kind: "opening_trial_balance", link: null },
] as const;

export type OpeningStep = (typeof OPENING_STEPS)[number];
export type StepState = "done" | "ready" | "unavailable";

/**
 * Where each import stands: `done` when a finished (not reversed) import of that kind exists, `unavailable` when the kind is not offered
 * to this user (the unit is off or they lack the permission), otherwise `ready`. Steps without an import are always `ready`.
 */
export function stepStates(available: readonly string[], batches: readonly Pick<Batch, "kind" | "status">[]): Record<string, StepState> {
  const finished = new Set(batches.filter((b) => b.status === "done").map((b) => b.kind));
  const states: Record<string, StepState> = {};
  for (const step of OPENING_STEPS) {
    if (step.kind === null) states[step.id] = "ready";
    else if (finished.has(step.kind)) states[step.id] = "done";
    else states[step.id] = available.includes(step.kind) ? "ready" : "unavailable";
  }
  return states;
}
