import type { Schemas } from "@/sdk";

export type ChatOverview = Schemas["ChatOverviewOut"];
export type ChatConnection = Schemas["ChatConnectionOut"];

/** The states a connection can be in while a number is being connected. */
export const OPEN_STATES = ["pending", "awaiting_code"] as const;

export const isOpen = (state: string): boolean => (OPEN_STATES as readonly string[]).includes(state);

/** Where the walk-through stands: which steps are done, which one is next. */
export type StepId = "key" | "number" | "say" | "try" | "on";

export interface StepStatus {
  id: StepId;
  done: boolean;
  /** The first step that is not done: the one to look at. */
  current: boolean;
}

export function steps(o: ChatOverview): StepStatus[] {
  const done: Record<StepId, boolean> = {
    key: o.key.is_set && o.key.tested_ok === true,
    number: o.connection.state === "connected",
    say: o.connection.state === "connected",
    try: o.connection.state === "connected",
    on: o.bot.enabled,
  };
  const order: StepId[] = ["key", "number", "say", "try", "on"];
  const firstOpen = order.find((id) => !done[id]);
  return order.map((id) => ({ id, done: done[id], current: id === firstOpen }));
}

/** The words to show for a connection state (a key under chat.connect.states). */
export const connectionStateKey = (state: string): string => (["none", "pending", "awaiting_code", "connected", "failed", "cancelled"].includes(state) ? state : "none");

/** The reason the switch cannot go on yet, as a key under chat.bot.notReady. */
export const notReadyKey = (o: ChatOverview): string | null => (o.bot.can_enable ? null : (o.bot.not_ready_because ?? "connect"));

/** The public address warning, as a key under chat.webhook.problems. */
export function addressProblem(o: ChatOverview): "empty" | "notHttps" | null {
  if (o.fake) return null;
  if (!o.webhook.url) return "empty";
  return o.webhook.problem ? "notHttps" : null;
}

/** Digits only (what a person types for a calling code or a number). */
export const digits = (value: string): string => value.replace(/\D/g, "");

/** Whether the "New number" form can be sent. */
export function canSendNumber(mode: "new" | "existing", f: { country: string; phone: string; business: string; display: string }): boolean {
  const country = digits(f.country);
  const phone = digits(f.phone);
  const numberOk = country.length >= 1 && country.length <= 4 && phone.length >= 5 && phone.length <= 14;
  return mode === "existing" ? numberOk : numberOk && f.business.trim() !== "" && f.display.trim() !== "";
}

/** The grand outcome line under "Waiting for a person": counts only. */
export const outcomeKeys = ["answered", "unknown", "opted_out", "failed"] as const;
