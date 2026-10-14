/** The company policies the API exposes, grouped for the form, and the conversion between API values and form text. */
import type { Schemas } from "@/sdk";

export type Settings = Schemas["CompanySettingsOut"];
export type SettingKey = keyof Settings;
export type FieldKind = "switch" | "number" | "money" | "integer" | "text" | "choice" | "weekdays";

export interface SettingField {
  key: SettingKey;
  kind: FieldKind;
  choices?: string[];
}

export const GROUPS: { id: string; fields: SettingField[] }[] = [
  { id: "stock", fields: [
    { key: "negative_stock_allowed", kind: "switch" },
    { key: "count_variance_threshold", kind: "money" },
    { key: "late_posting", kind: "choice", choices: ["redirect", "reject"] },
    { key: "bill_match_tolerance_percent", kind: "number" },
  ] },
  { id: "reminders", fields: [
    { key: "reminder_channel", kind: "choice", choices: ["off", "sms", "email"] },
    { key: "reminder_min_days_overdue", kind: "integer" },
    { key: "reminder_repeat_days", kind: "integer" },
  ] },
  { id: "regional", fields: [
    { key: "timezone", kind: "text" },
  ] },
  { id: "alerts", fields: [
    { key: "intel_alert_channel", kind: "choice", choices: ["off", "sms", "email"] },
    { key: "intel_alert_min_severity", kind: "choice", choices: ["low", "medium", "high", "critical"] },
    { key: "intel_action_level", kind: "integer" },
  ] },
  { id: "people", fields: [
    { key: "weekend_days", kind: "weekdays" },
    { key: "payroll_unpaid_day_divisor", kind: "integer" },
    { key: "overtime_multiplier", kind: "number" },
    { key: "overtime_hours_per_month", kind: "number" },
  ] },
  { id: "privacy", fields: [
    { key: "privacy_response_days", kind: "integer" },
    { key: "privacy_erasure_needs_approval", kind: "switch" },
    { key: "retention_notifications_days", kind: "integer" },
    { key: "retention_audit_years", kind: "integer" },
    { key: "retention_employee_records_years", kind: "integer" },
    { key: "retention_inactive_customers_years", kind: "integer" },
  ] },
  { id: "printing", fields: [
    { key: "phone_country_code", kind: "text" },
    { key: "receipt_footer", kind: "text" },
    { key: "invoice_footer", kind: "text" },
  ] },
];

export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type FormValues = Record<SettingKey, string>;

const FIELDS = GROUPS.flatMap((g) => g.fields);

/** Every value as text: booleans "true"/"false", weekdays "sat,sun". */
export function toForm(settings: Settings): FormValues {
  const out = {} as FormValues;
  for (const f of FIELDS) {
    const v = settings[f.key];
    out[f.key] = Array.isArray(v) ? v.join(",") : String(v);
  }
  return out;
}

function parse(field: SettingField, text: string): unknown {
  if (field.kind === "switch") return text === "true";
  if (field.kind === "integer") return Number(text);
  if (field.kind === "weekdays") return text ? text.split(",") : [];
  return text.trim();
}

/** Only the settings that changed, in the types the API expects (it changes only the fields sent). */
export function toPatch(original: FormValues, current: FormValues): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const f of FIELDS) {
    if (original[f.key] !== current[f.key]) patch[f.key] = parse(f, current[f.key]);
  }
  return patch;
}

/** The text a document number will have, for the preview next to a series. */
export function sampleNumber(prefix: string, next: number, padding: number): string {
  return `${prefix}${String(next).padStart(padding, "0")}`;
}
