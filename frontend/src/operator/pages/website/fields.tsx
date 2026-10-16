import { type ReactNode } from "react";

import { Alert, Button, ErrorState, Field, Input, Select, Skeleton, Switch, Textarea, useTranslation } from "@/sdk";

import { type SettingsEditor } from "./useSettingsEditor";

/** The three states of a settings tab before its form can show: loading, failed, ready. */
export function EditorGate({ editor, children }: { editor: SettingsEditor; children: ReactNode }) {
  if (editor.query.isError) return <ErrorState message={editor.query.error.message} onRetry={() => void editor.query.refetch()} />;
  if (!editor.ready) return <div className="space-y-3"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /><Skeleton className="h-24 w-full" /></div>;
  return <>{children}</>;
}

export function TextSetting({ editor, name, label, hint, type = "text", placeholder, required, multiline }: {
  editor: SettingsEditor; name: string; label: string; hint?: string; type?: string; placeholder?: string; required?: boolean; multiline?: boolean;
}) {
  const value = String(editor.form[name] ?? "");
  const error = editor.errorFor(name);
  return (
    <Field label={label} hint={hint} error={error} required={required}>
      {multiline
        ? <Textarea value={value} rows={3} placeholder={placeholder} onChange={(e) => editor.set(name, e.target.value)} />
        : <Input value={value} type={type} placeholder={placeholder} onChange={(e) => editor.set(name, e.target.value)} />}
    </Field>
  );
}

/** One text per language, side by side on a wide screen. */
export function LocalisedSetting({ editor, name, label, hint, locales, multiline }: {
  editor: SettingsEditor; name: string; label: string; hint?: string; locales: string[]; multiline?: boolean;
}) {
  const value = (editor.form[name] ?? {}) as Record<string, string>;
  const error = editor.errorFor(name);
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className={locales.length > 1 ? "grid gap-3 sm:grid-cols-2" : ""}>
        {locales.map((locale) => (
          <Field key={locale} label={locale.toUpperCase()} error={error && locale === locales[0] ? error : null}>
            {multiline
              ? <Textarea value={value[locale] ?? ""} rows={3} onChange={(e) => editor.setLocal(name, locale, e.target.value)} />
              : <Input value={value[locale] ?? ""} onChange={(e) => editor.setLocal(name, locale, e.target.value)} />}
          </Field>
        ))}
      </div>
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
    </fieldset>
  );
}

export function SwitchSetting({ editor, name, label, hint }: { editor: SettingsEditor; name: string; label: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-line p-3">
      <div><p className="text-sm font-medium">{label}</p>{hint && <p className="text-xs text-muted">{hint}</p>}</div>
      <Switch checked={editor.form[name] === true} onChange={(v) => editor.set(name, v)} label={label} />
    </div>
  );
}

export function AssetSetting({ editor, name, label, hint, assets }: {
  editor: SettingsEditor; name: string; label: string; hint?: string; assets: { id: string; name: string }[];
}) {
  return (
    <Field label={label} hint={hint} error={editor.errorFor(name)}>
      <Select value={String(editor.form[name] ?? "")} onChange={(e) => editor.set(name, e.target.value)}>
        <option value="">-</option>
        {assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </Select>
    </Field>
  );
}

/** Save and discard, sticky at the bottom of the tab so a long form never hides them. */
export function SaveBar({ editor }: { editor: SettingsEditor }) {
  const { t } = useTranslation("operator");
  return (
    <div className="sticky bottom-0 -mx-1 mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line bg-bg/95 px-1 py-3 backdrop-blur">
      <p className="text-xs text-muted">{editor.dirty ? t("website.unsaved") : t("website.nothingToSave")}</p>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={!editor.dirty || editor.saving} onClick={editor.discard}>{t("website.discard")}</Button>
        <Button loading={editor.saving} disabled={!editor.dirty || editor.hasProblems} onClick={editor.save}>{t("website.save")}</Button>
      </div>
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <Alert tone="info" className="mb-4">{children}</Alert>;
}
