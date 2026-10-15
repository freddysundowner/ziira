import { Field, FormGrid, humanise, Input, NumberInput, Select, useTranslation } from "@/sdk";

import { type Draft, type FieldDef, serverMessage, validate } from "./schema";

export interface BranchOption { id: string; name: string }

interface Props {
  fields: readonly FieldDef[];
  draft: Draft;
  onChange: (name: string, value: string) => void;
  /** Show the checks' messages (after a first attempt to save). */
  checked?: boolean;
  /** The server's field messages from a 422. */
  server?: Record<string, string>;
  /** When given, a field named `branch_id` is a branch choice (empty = every branch). */
  branches?: readonly BranchOption[];
  /** Fixed fields are shown as plain text, taken from here. */
  fixed?: Record<string, unknown>;
  disabled?: boolean;
}

/** A form built from a server-described schema: text, whole number, decimal, date, a choice, yes/no, a branch. Fixed fields are read-only. */
export default function SchemaForm({ fields, draft, onChange, checked, server = {}, branches, fixed = {}, disabled }: Props) {
  const { t } = useTranslation("intel");
  const problems = checked ? validate(fields, draft) : {};
  const message = (f: FieldDef): string | null => {
    const p = problems[f.name];
    if (serverMessage(server, f.name)) return serverMessage(server, f.name)!;
    return p ? t(`schemaForm.${p.code}`, { limit: p.limit }) : null;
  };

  return (
    <FormGrid>
      {fields.map((f) => {
        const error = message(f);
        const value = draft[f.name] ?? "";
        const common = { label: f.title, hint: f.description, error, required: f.required };
        if (!f.editable) {
          return <Field key={f.name} label={f.title} hint={f.description}><p className="text-sm">{String(fixed[f.name] ?? "—")}</p></Field>;
        }
        if (f.type === "uuid") {
          if (f.name !== "branch_id" || !branches) return null;
          return (
            <Field key={f.name} {...common}>
              <Select value={value} disabled={disabled} onChange={(e) => onChange(f.name, e.target.value)}>
                <option value="">{t("allBranches")}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            </Field>
          );
        }
        if (f.type === "boolean") {
          return (
            <Field key={f.name} {...common}>
              <Select value={value || "false"} disabled={disabled} onChange={(e) => onChange(f.name, e.target.value)}>
                <option value="true">{t("yes")}</option>
                <option value="false">{t("no")}</option>
              </Select>
            </Field>
          );
        }
        if (f.options) {
          return (
            <Field key={f.name} {...common}>
              <Select value={value} disabled={disabled} onChange={(e) => onChange(f.name, e.target.value)}>
                {!f.required && <option value="">—</option>}
                {f.options.map((o) => <option key={o} value={o}>{humanise(o)}</option>)}
              </Select>
            </Field>
          );
        }
        if (f.type === "integer" || f.type === "number") {
          return <Field key={f.name} {...common}><NumberInput value={value} disabled={disabled} inputMode={f.type === "integer" ? "numeric" : "decimal"} onChange={(v) => onChange(f.name, v)} /></Field>;
        }
        return (
          <Field key={f.name} {...common}>
            <Input value={value} type={f.type === "date" ? "date" : "text"} maxLength={f.maxLength} disabled={disabled} onChange={(e) => onChange(f.name, e.target.value)} />
          </Field>
        );
      })}
    </FormGrid>
  );
}
