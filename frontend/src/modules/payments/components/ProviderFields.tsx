import { Field, Input, Select } from "@/sdk";

import type { ProviderField } from "./usePaymentProviders";

/** A provider's form, drawn from its description: text boxes (hidden for secrets) and choices. Nothing here knows any provider. */
export function ProviderFields({ fields, values, onChange, errors = {} }: {
  fields: readonly ProviderField[]; values: Readonly<Record<string, string>>; onChange: (key: string, value: string) => void; errors?: Record<string, string | undefined>;
}) {
  return (
    <>
      {fields.map((f) => {
        const value = values[f.key] ?? f.default ?? "";
        return (
          <Field key={f.key} label={f.label} hint={f.help || undefined} required={f.required} error={errors[f.key]}>
            {f.kind === "select" ? (
              <Select value={value} onChange={(e) => onChange(f.key, e.target.value)}>
                {!f.required && <option value="" />}
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </Select>
            ) : (
              <Input type={f.secret ? "password" : "text"} value={value} required={f.required} autoComplete={f.secret ? "new-password" : "off"}
                onChange={(e) => onChange(f.key, e.target.value)} />
            )}
          </Field>
        );
      })}
    </>
  );
}
