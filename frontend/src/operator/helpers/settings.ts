/** Platform settings as the forms hold them (text) and as the API stores them. The server validates and explains. */

/** A box holding a whole number goes as a number; anything else goes as typed so the server can say what is wrong. */
export function numberValue(draft: string): number | string {
  const clean = draft.trim();
  return clean !== "" && Number.isInteger(Number(clean)) ? Number(clean) : clean;
}

/** "-7, 0, 3, 7" as day offsets; anything that is not a whole number is kept as text for the server to refuse. */
export function parseOffsets(text: string): (number | string)[] {
  return text.split(/[\s,;]+/).filter(Boolean).map(numberValue);
}

export interface DunningDraft {
  reminders: string;
  past_due_after_days: string;
  grace_after_days: string;
  suspend_after_days: string;
  expire_after_days: string;
}

export function dunningToDraft(value: Record<string, unknown> | undefined): DunningDraft {
  const v = value ?? {};
  return {
    reminders: Array.isArray(v.reminders) ? v.reminders.join(", ") : "",
    past_due_after_days: String(v.past_due_after_days ?? ""),
    grace_after_days: String(v.grace_after_days ?? ""),
    suspend_after_days: String(v.suspend_after_days ?? ""),
    expire_after_days: String(v.expire_after_days ?? ""),
  };
}

export function dunningFromDraft(draft: DunningDraft) {
  return {
    reminders: parseOffsets(draft.reminders),
    past_due_after_days: numberValue(draft.past_due_after_days),
    grace_after_days: numberValue(draft.grace_after_days),
    suspend_after_days: numberValue(draft.suspend_after_days),
    expire_after_days: numberValue(draft.expire_after_days),
  };
}

export interface TaxLineDraft {
  name: string;
  rate_percent: string;
}

export const taxLinesToDraft = (value: unknown): TaxLineDraft[] =>
  (Array.isArray(value) ? value : []).map((l) => ({ name: String((l as TaxLineDraft).name ?? ""), rate_percent: String((l as TaxLineDraft).rate_percent ?? "") }));

/** Tax lines as sent: blank rows dropped, names trimmed. */
export const taxLinesFromDraft = (lines: TaxLineDraft[]): TaxLineDraft[] =>
  lines.filter((l) => l.name.trim() || l.rate_percent.trim()).map((l) => ({ name: l.name.trim(), rate_percent: l.rate_percent.trim() }));

export interface VendorDraft {
  name: string;
  address: string;
  tax_id: string;
  email: string;
  phone: string;
}

export const VENDOR_FIELDS = ["name", "address", "tax_id", "email", "phone"] as const;

export function vendorToDraft(value: Record<string, unknown> | undefined): VendorDraft {
  const v = value ?? {};
  return { name: String(v.name ?? ""), address: String(v.address ?? ""), tax_id: String(v.tax_id ?? ""), email: String(v.email ?? ""), phone: String(v.phone ?? "") };
}
