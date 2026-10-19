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

/** The dropdown's value for "a model name I type". */
export const OTHER_MODEL = "__other__";
export const NO_PROVIDER = "__none__";

export interface ModelOptions {
  /** The "fast and cheap" recommendation (the provider's best-value model). */
  fast: ModelChoice | undefined;
  /** The "more capable" model. */
  capable: ModelChoice | undefined;
}

/** Two plain choices first (Fast and cheap, More capable); the rest of the catalogue is only reachable as "Other". */
export function modelOptions(p: AiProvider): ModelOptions {
  const fast = p.model_choices.find((m) => m.tiers.includes("best_value")) ?? p.model_choices[0];
  const capable = p.model_choices.find((m) => m.tiers.includes("higher_quality") && m.id !== fast?.id);
  return { fast, capable };
}

/** What the model dropdown shows for the model in use: a listed option, or "Other". */
export function modelSelectValue(p: AiProvider, current: string, typingOther: boolean): string {
  const o = modelOptions(p);
  if (typingOther) return OTHER_MODEL;
  if (o.fast && current === o.fast.id) return o.fast.id;
  if (o.capable && current === o.capable.id) return o.capable.id;
  return OTHER_MODEL;
}

/** One model for every feature (the simple form); per-feature choices live under Details. */
export function withModel(d: ProviderDraft, id: string): ProviderDraft {
  return { ...d, models: { explain: id, rank: id, ask: id } };
}

/** Saving to use a provider: switched on, and nothing else sent that did not change. */
export function bodyToUse(p: AiProvider, d: ProviderDraft): AiProviderBody {
  return providerBody(p, { ...d, enabled: true });
}

/** Is there a key to use: one saved (and not being removed) or one typed. */
export const hasKey = (p: AiProvider, d: ProviderDraft): boolean => d.apiKey.trim().length > 0 || (p.key_set && !d.clearKey);

/** The plain status line at the top, from what is saved (not from the dropdown). */
export function statusOf(o: AiOverview): { on: boolean; provider: string | null; model: string | null } {
  const p = o.providers.find((x) => x.name === o.default_provider);
  if (p) return { on: true, provider: p.title, model: p.models.ask ?? null };
  return { on: false, provider: null, model: null };
}
