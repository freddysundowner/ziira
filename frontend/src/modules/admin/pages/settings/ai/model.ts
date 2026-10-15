/** Pure rules for the AI assistant settings screen. */
import type { Schemas } from "@/sdk";

export type AiSettings = Schemas["AiSettingsOut"];
export type AiCall = Schemas["AiCallOut"];

/** A token count the way people read it: thousands separated, no decimals. */
export function tokens(n: number): string {
  return Math.round(n).toLocaleString("en");
}

/** How much of the monthly limit is used, 0 to 100 (a limit of zero counts as fully used). */
export function usedPercent(used: number, limit: number): number {
  if (limit <= 0) return 100;
  return Math.min(100, Math.max(0, Math.round((used / limit) * 100)));
}

/** The limit the person typed as a whole number of tokens, or null when it is not one. */
export function parseLimit(text: string): number | null {
  const clean = text.replace(/[,\s]/g, "");
  if (!/^\d{1,10}$/.test(clean)) return null;
  const n = Number(clean);
  return n <= 2_000_000_000 ? n : null;
}

/** Why a request log row was not made, or null when it was made: "blocked:budget" -> "budget". */
export function blockedReason(status: string): string | null {
  return status.startsWith("blocked:") ? status.slice("blocked:".length) : null;
}

/** Whether the screen should explain that consent must be given again (the text or the provider changed). */
export function needsFreshConsent(s: Pick<AiSettings, "enabled" | "consent_valid" | "consents">): boolean {
  return !s.enabled && !s.consent_valid && s.consents.some((c) => c.action === "granted");
}
