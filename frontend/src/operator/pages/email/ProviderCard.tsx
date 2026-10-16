import { useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Select, toast, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";

export type Provider = Schemas["MailProviderOut"];

/** The body of a save: only plain fields that changed, and only secrets that were typed (an empty secret keeps the stored one). */
export function providerBody(p: Provider, values: Record<string, string>, secrets: Record<string, string>, cleared: string[]) {
  const config = Object.fromEntries(p.fields.filter((f) => !f.secret && (values[f.name] ?? "") !== (f.value ?? "")).map((f) => [f.name, values[f.name] ?? ""]));
  const typed = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v.trim() !== ""));
  return {
    ...(Object.keys(config).length ? { config } : {}),
    ...(Object.keys(typed).length ? { secrets: typed } : {}),
    ...(cleared.length ? { clear_secrets: cleared } : {}),
  };
}

/** One provider: its fields (secrets write-only), Save, test, and Make live. */
export function ProviderCard({ provider: p, editable, onChanged, onTest }: {
  provider: Provider; editable: boolean; onChanged: () => void; onTest: (provider: string) => void;
}) {
  const { t } = useTranslation("operator");
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(p.fields.filter((f) => !f.secret).map((f) => [f.name, f.value ?? ""])));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [cleared, setCleared] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const body = providerBody(p, values, secrets, cleared);
  const dirty = Object.keys(body).length > 0;
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/email/providers/{name}", { params: { path: { name: p.name } }, body })), {
    onSuccess: () => { toast(t("email.provider.saved", { name: p.label }), "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  const live = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/email/active", { body: { provider: p.name } })), {
    onSuccess: () => { toast(t("email.provider.activated", { name: p.label }), "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  return (
    <Card title={p.label} description={p.description}
      actions={<div className="flex gap-1">{p.selected && <Badge tone="ok">{t("email.provider.live")}</Badge>}<Badge tone={p.tested_ok ? "ok" : "neutral"}>{p.tested_ok ? t("email.provider.tested") : t("email.provider.notTested")}</Badge></div>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
          {p.fields.map((f) => f.secret ? (
            <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
              <div className="flex gap-2">
                <Input type="password" autoComplete="off" value={secrets[f.name] ?? ""} disabled={cleared.includes(f.name)}
                  placeholder={f.is_set ? t("email.provider.keepSecret") : t("email.provider.notSet")}
                  onChange={(e) => { setSecrets({ ...secrets, [f.name]: e.target.value }); setProblem(null); }} />
                {f.is_set && (
                  <Button type="button" size="sm" variant="ghost" onClick={() => setCleared(cleared.includes(f.name) ? cleared.filter((n) => n !== f.name) : [...cleared, f.name])}>
                    {cleared.includes(f.name) ? t("email.provider.keep") : t("email.provider.remove")}
                  </Button>
                )}
              </div>
            </Field>
          ) : f.options.length > 0 ? (
            <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
              <Select value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </Select>
            </Field>
          ) : (
            <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
              <Input value={values[f.name] ?? ""} maxLength={300} inputMode={f.kind === "number" ? "numeric" : undefined} onChange={(e) => { setValues({ ...values, [f.name]: e.target.value }); setProblem(null); }} />
            </Field>
          ))}
        </fieldset>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {editable && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="secondary" size="sm" disabled={dirty || !p.configured} onClick={() => onTest(p.name)}>{t("email.provider.test")}</Button>
            <Button type="button" variant="secondary" size="sm" loading={live.isPending} disabled={dirty || !p.tested_ok || p.selected} onClick={() => { setProblem(null); live.mutate(undefined); }}>{t("email.provider.makeLive")}</Button>
            <Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("email.provider.save")}</Button>
          </div>
        )}
      </form>
    </Card>
  );
}
