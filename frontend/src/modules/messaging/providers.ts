/**
 * The gateways the messaging plugin can send through, and the settings each one needs. The API does not list them, so this
 * mirrors the plugin's README. Keys and passwords ("secret") are write-only: the server never returns them.
 */
export type Channel = "sms" | "email";
export interface ProviderField {
  name: string;
  where: "secret" | "config";
  kind: "text" | "password" | "number" | "bool";
  required?: boolean;
  /** The server's default when left empty, shown as the placeholder. */
  placeholder?: string;
}
export interface Provider {
  id: string;
  name: string;
  channel: Channel;
  fields: ProviderField[];
}

const apiKey: ProviderField = { name: "api_key", where: "secret", kind: "password", required: true };
const emailFrom: ProviderField[] = [
  { name: "from_address", where: "config", kind: "text", required: true },
  { name: "from_name", where: "config", kind: "text" },
];

export const PROVIDERS: Provider[] = [
  { id: "smtp", name: "SMTP", channel: "email", fields: [
    { name: "host", where: "secret", kind: "text", required: true },
    { name: "port", where: "secret", kind: "number", placeholder: "587" },
    { name: "username", where: "secret", kind: "text" },
    { name: "password", where: "secret", kind: "password" },
    ...emailFrom,
    { name: "starttls", where: "config", kind: "bool" },
  ] },
  { id: "brevo", name: "Brevo", channel: "email", fields: [apiKey, ...emailFrom] },
  { id: "resend", name: "Resend", channel: "email", fields: [apiKey, ...emailFrom] },
  { id: "sendgrid", name: "SendGrid", channel: "email", fields: [apiKey, ...emailFrom] },
  { id: "blessedtexts", name: "BlessedTexts", channel: "sms", fields: [apiKey, { name: "sender_id", where: "config", kind: "text", required: true }] },
  { id: "africastalking", name: "Africa's Talking", channel: "sms", fields: [
    apiKey,
    { name: "username", where: "config", kind: "text" },
    { name: "sender_id", where: "config", kind: "text" },
    { name: "sandbox", where: "config", kind: "bool" },
  ] },
];

export const providersFor = (channel: Channel): Provider[] => PROVIDERS.filter((p) => p.channel === channel);

/** The body parts the API wants, from what was typed: empty optional fields are left out, numbers and switches get their types. */
export function buildPayload(provider: Provider, values: Record<string, string>): { secret: Record<string, unknown>; config: Record<string, unknown> } {
  const out = { secret: {} as Record<string, unknown>, config: {} as Record<string, unknown> };
  for (const f of provider.fields) {
    const raw = (values[f.name] ?? "").trim();
    if (f.kind === "bool") out[f.where][f.name] = raw === "true";
    else if (raw) out[f.where][f.name] = f.kind === "number" ? Number(raw) : raw;
  }
  return out;
}

/** True when every required field has a value. */
export const isComplete = (provider: Provider, values: Record<string, string>): boolean =>
  provider.fields.every((f) => !f.required || (values[f.name] ?? "").trim() !== "");
