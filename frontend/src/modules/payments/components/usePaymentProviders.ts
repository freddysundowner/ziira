import { api, type Schemas, unwrap, useQuery } from "@/sdk";

export type ProviderInfo = Schemas["ProviderOut"];
export type ProviderField = Schemas["FormFieldOut"];

/** The payment providers and statement formats switched on for this business, each described as data (its forms, its limits). */
export function usePaymentProviders(enabled = true) {
  return useQuery({
    enabled, queryKey: ["payment-providers"], staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/payments/providers")),
  });
}

/** The providers worth offering for a new account: the real ones first, development-only ones last. */
export function offeredProviders(providers: readonly ProviderInfo[]): ProviderInfo[] {
  return [...providers].sort((a, b) => Number(a.development_only) - Number(b.development_only) || a.title.localeCompare(b.title));
}

/** What to send for a form of provider fields: only the fields that have a value (blank ones are left out). */
export function fieldValues(fields: readonly ProviderField[], values: Readonly<Record<string, string>>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of fields) {
    const value = (values[f.key] ?? f.default ?? "").trim();
    if (value) out[f.key] = value;
  }
  return out;
}

/** The first required field the person left empty, if any. */
export function missingRequired(fields: readonly ProviderField[], values: Readonly<Record<string, string>>): ProviderField | undefined {
  return fields.find((f) => f.required && !(values[f.key] ?? f.default ?? "").trim());
}
