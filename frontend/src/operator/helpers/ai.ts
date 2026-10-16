import type { Schemas } from "@/sdk";

export type AiProvider = Schemas["AiProviderOut"];
export type AiOverview = Schemas["AiOverviewOut"];
export type ModelChoice = Schemas["AiModelChoice"];
export type AiProviderBody = Schemas["AiProviderIn"];

export const FEATURES = ["explain", "rank", "ask"] as const;
export type Feature = (typeof FEATURES)[number];

export interface ProviderDraft {
  enabled: boolean;
  apiKey: string;
  clearKey: boolean;
  baseUrl: string;
  models: Record<Feature, string>;
  termsAcknowledged: boolean;
}

export function providerDraft(p: AiProvider): ProviderDraft {
  return {
    enabled: p.enabled,
    apiKey: "",
    clearKey: false,
    baseUrl: p.base_url,
    models: { explain: p.models.explain ?? "", rank: p.models.rank ?? "", ask: p.models.ask ?? "" },
    termsAcknowledged: p.terms_ack_at !== null,
  };
}

/** Only what changed is sent; a key left empty is not sent at all (the saved one stays). */
export function providerBody(p: AiProvider, d: ProviderDraft): AiProviderBody {
  const before = providerDraft(p);
  const models = Object.fromEntries(FEATURES.filter((f) => d.models[f] !== before.models[f]).map((f) => [f, d.models[f]]));
  return {
    ...(d.enabled !== before.enabled ? { enabled: d.enabled } : {}),
    ...(d.apiKey.trim() ? { api_key: d.apiKey.trim() } : {}),
    ...(d.clearKey ? { clear_key: true } : {}),
    ...(d.baseUrl.trim() !== before.baseUrl ? { base_url: d.baseUrl.trim() } : {}),
    ...(Object.keys(models).length ? { models } : {}),
    ...(d.termsAcknowledged !== before.termsAcknowledged ? { terms_acknowledged: d.termsAcknowledged } : {}),
  };
}

export const providerDirty = (p: AiProvider, d: ProviderDraft): boolean => Object.keys(providerBody(p, d)).length > 0;

/** "Key saved ending ····1234" is built from the last four characters only. */
export const maskedKey = (last4: string): string => `····${last4}`;

/** USD with enough places for a per-million-token price or a small estimate: 0.1 -> "$0.10", 0.0004 -> "$0.0004". */
export function usd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const places = n !== 0 && Math.abs(n) < 0.01 ? 4 : 2;
  return `$${n.toFixed(places)}`;
}

export const TIER_TONE: Record<string, "ok" | "info" | "neutral"> = { best_value: "ok", higher_quality: "info", cheapest: "neutral" };

/** The width of a day's bar against the busiest day (0-100). */
export function barPercent(cost: string, max: number): number {
  return max > 0 ? Math.max(2, Math.round((Number(cost) / max) * 100)) : 0;
}

/** What the model list says about a choice: unknown price needs the owner's attention. */
export const priceKnown = (m: ModelChoice | undefined): boolean => !!m && m.input_per_mtok !== null;
