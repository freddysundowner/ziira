import { type FormEvent, useState } from "react";

import { Alert, api, Button, Checkbox, Field, FormGrid, Input, Select, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { FRESHNESS_CHOICES, type Connection, type Kind } from "../logic";

/** Rename, change the settings of a connection (a blank secret keeps the one stored), how often it is read. */
export function SettingsForm({ connection, kind }: { connection: Connection; kind: Kind | undefined }) {
  const { t } = useTranslation("connect");
  const queryClient = useQueryClient();
  const [name, setName] = useState(connection.name);
  const [minutes, setMinutes] = useState(connection.sync_every_minutes);
  const [auto, setAuto] = useState(connection.auto_create_branches);
  const [values, setValues] = useState<Record<string, string>>({});
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PATCH("/api/v1/connect/connections/{connection_id}", {
      params: { path: { connection_id: connection.id } },
      body: { name, auto_create_branches: auto, sync_every_minutes: kind?.freshness === "on_upload" ? null : minutes, config: Object.keys(values).length ? values : null },
    })),
    onSuccess: () => { setValues({}); void queryClient.invalidateQueries({ queryKey: ["connect"] }); toast(t("settings.saved"), "ok"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const disabled = connection.status === "disconnected";
  return (
    <form onSubmit={submit} className="space-y-4">
      <FormGrid>
        <Field label={t("wizard.name")}><Input value={name} minLength={2} maxLength={80} required onChange={(e) => setName(e.target.value)} /></Field>
        {kind?.freshness !== "on_upload" && (
          <Field label={t("settings.every")} hint={t("settings.everyHint")}>
            <Select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
              {[...new Set([...FRESHNESS_CHOICES, connection.sync_every_minutes])].sort((a, b) => a - b).map((m) => <option key={m} value={m}>{t("settings.minutes", { count: m })}</option>)}
            </Select>
          </Field>
        )}
        {(kind?.config_fields ?? []).map((f) => (
          <Field key={f.name} label={f.label} hint={f.secret ? (connection.secrets_set.includes(f.name) ? t("settings.secretSet") : f.help) : f.help}>
            <Input type={f.secret ? "password" : "text"} autoComplete="off" placeholder={f.secret && connection.secrets_set.includes(f.name) ? "••••••••" : f.example}
              value={values[f.name] ?? (f.secret ? "" : String(connection.config[f.name] ?? ""))}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
          </Field>
        ))}
      </FormGrid>
      <Checkbox checked={auto} onChange={(e) => setAuto(e.target.checked)} label={t("wizard.autoBranches")} />
      {save.error && <Alert tone="bad">{save.error.message}</Alert>}
      <Button type="submit" loading={save.isPending} disabled={disabled}>{t("settings.save")}</Button>
    </form>
  );
}
