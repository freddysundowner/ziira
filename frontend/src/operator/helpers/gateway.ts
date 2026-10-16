import type { Schemas } from "@/sdk";

export type Gateway = Schemas["GatewayOut"];
export type GatewayField = Gateway["fields"][number];

export interface GatewayDraft {
  enabled: boolean;
  /** Plain settings by field name. */
  values: Record<string, string>;
  /** Secrets typed this time (empty: keep what is stored). */
  secrets: Record<string, string>;
  /** Secrets the operator chose to remove. */
  cleared: string[];
  defaultFor: string;
}

export function gatewayDraft(g: Gateway): GatewayDraft {
  return {
    enabled: g.enabled,
    values: Object.fromEntries(g.fields.filter((f) => !f.secret).map((f) => [f.name, f.value ?? ""])),
    secrets: {},
    cleared: [],
    defaultFor: g.default_for.join(", "),
  };
}

/** "KES, ke" -> ["KES", "KE"] */
export function parseCodes(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean))];
}

/** Only what changed is sent; a secret field left empty is not sent at all (the stored one stays). */
export function gatewayBody(g: Gateway, d: GatewayDraft): Schemas["GatewayIn"] {
  const before = gatewayDraft(g);
  const config = Object.fromEntries(Object.entries(d.values).filter(([k, v]) => v !== before.values[k]));
  const secrets = Object.fromEntries(Object.entries(d.secrets).filter(([, v]) => v.trim() !== ""));
  const codes = parseCodes(d.defaultFor);
  return {
    ...(d.enabled !== g.enabled ? { enabled: d.enabled } : {}),
    ...(Object.keys(config).length ? { config } : {}),
    ...(Object.keys(secrets).length ? { secrets } : {}),
    ...(d.cleared.length ? { clear_secrets: d.cleared } : {}),
    ...(codes.join(",") !== g.default_for.join(",") ? { default_for: codes } : {}),
  };
}

export const gatewayDirty = (g: Gateway, d: GatewayDraft): boolean => Object.keys(gatewayBody(g, d)).length > 0;

/** Attempt states: open ones are neutral, a credit is good, a mismatch needs a person. */
export const ATTEMPT_TONES: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  initiated: "neutral", pending: "info", completed: "ok", failed: "bad", expired: "neutral", mismatch: "warn",
};

/** Whether "Mark as paid manually" makes sense: anything not already credited. */
export const canMarkPaid = (status: string): boolean => status !== "completed";
